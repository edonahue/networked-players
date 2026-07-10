from __future__ import annotations

import importlib.util
import json
import threading
from pathlib import Path
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
