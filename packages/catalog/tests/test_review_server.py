from __future__ import annotations

import importlib.util
import json
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

_MODULE_PATH = Path(__file__).resolve().parents[3] / "apps" / "review" / "review_server.py"
_SPEC = importlib.util.spec_from_file_location("review_server", _MODULE_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
load_state = _MODULE.load_state
save_selection = _MODULE.save_selection
make_handler = _MODULE.make_handler
ThreadingHTTPServer = _MODULE.ThreadingHTTPServer
PAGE = _MODULE.PAGE


def test_review_server_defaults_to_dark_with_a_persisted_theme_toggle() -> None:
    assert "networked-players-curator-theme" in PAGE
    assert "t==='light'?'light':'dark'" in PAGE
    assert 'class="theme-toggle"' in PAGE
    assert "evidence_hops" in PAGE


def test_review_server_loads_packet_and_selection(tmp_path: Path) -> None:
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    (analysis / "editorial-review.json").write_text(
        json.dumps({"status": "suggestions-only", "pair_count": 1})
    )
    selection = tmp_path / "selection.json"
    save_selection(
        selection, {"approved_pairs": [{"album_a_id": "a", "album_b_id": "b"}]}, "tester"
    )
    state = load_state(analysis, selection, "synthetic")
    assert state["source_id"] == "synthetic"
    assert state["selection"]["approved_pairs"][0]["album_a_id"] == "a"


def test_review_server_writes_atomically_shaped_selection(tmp_path: Path) -> None:
    selection = tmp_path / "nested" / "selection.json"
    save_selection(selection, {"approved_pairs": [], "review_note": "later"}, "tester")
    payload = json.loads(selection.read_text())
    assert payload["schema_version"] == 1
    assert payload["review_note"] == "later"
    assert payload["allow_flagged_pairs"] is False
    assert not selection.with_suffix(".json.tmp").exists()


def test_review_server_serves_state_and_saves_selection(tmp_path: Path) -> None:
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    (analysis / "editorial-review.json").write_text(
        json.dumps({"ranked_pairs": [], "suggested_pairs": [], "pair_count": 0})
    )
    selection = tmp_path / "selection.json"
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), make_handler(analysis, selection, "synthetic", "tester", None)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        assert json.loads(urlopen(f"{base}/api/state").read())["source_id"] == "synthetic"
        request = Request(
            f"{base}/api/selection",
            data=b'{"approved_pairs": []}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request) as response:
            assert response.status == 204
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
    assert json.loads(selection.read_text())["reviewed_by"] == "tester"


def test_review_server_api_state_returns_a_clean_error_for_a_missing_analysis_directory(
    tmp_path: Path,
) -> None:
    # A real gap this test guards against: --source-id pointing at a
    # directory that was never run through the cohort-analysis step (a
    # plausible operator typo, or starting the server too early) used to
    # raise an uncaught FileNotFoundError all the way out of do_GET -- a
    # traceback on stderr and a hard connection failure to the browser,
    # never the clean {"error": ...} JSON every workbench-mode endpoint
    # already returns for its own equivalent failures.
    analysis = tmp_path / "analysis-never-created"
    selection = tmp_path / "selection.json"
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), make_handler(analysis, selection, "synthetic", "tester", None)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            urlopen(f"{base}/api/state")
            raise AssertionError("expected an HTTPError")
        except HTTPError as exc:
            assert exc.code == 404
            assert "error" in json.loads(exc.read())
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_review_server_api_selection_returns_a_clean_error_for_a_non_object_body(
    tmp_path: Path,
) -> None:
    # save_selection immediately does payload.get("approved_pairs", []) --
    # a syntactically-valid but non-object body (a bare list, null, a
    # number) used to pass json.loads and then raise an unhandled
    # AttributeError, since the except clause only caught (ValueError,
    # json.JSONDecodeError). Mirrors the workbench's own
    # isinstance(payload, dict) guard on /api/compare.
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    (analysis / "editorial-review.json").write_text(
        json.dumps({"ranked_pairs": [], "suggested_pairs": [], "pair_count": 0})
    )
    selection = tmp_path / "selection.json"
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), make_handler(analysis, selection, "synthetic", "tester", None)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        request = Request(
            f"{base}/api/selection",
            data=b"[]",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urlopen(request)
            raise AssertionError("expected an HTTPError")
        except HTTPError as exc:
            assert exc.code == 400
            assert "error" in json.loads(exc.read())
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
    assert not selection.exists()
