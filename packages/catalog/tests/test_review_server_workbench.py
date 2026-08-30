"""Phase 7 PR D: `--mode workbench`, the third mode of apps/review's local
server. Real end-to-end HTTP tests against a real (small, synthetic)
corpus, mirroring test_review_server.py's own ThreadingHTTPServer pattern
for the pre-existing cohort mode -- this mode must not disturb that one at
all (see the cohort-mode tests there, still passing unchanged)."""

from __future__ import annotations

import importlib.util
import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from networked_players_catalog.discogs.parquet import SCHEMAS
from networked_players_graph_core.graph import GraphError

_MODULE_PATH = Path(__file__).resolve().parents[3] / "apps" / "review" / "review_server.py"
_SPEC = importlib.util.spec_from_file_location("review_server", _MODULE_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
make_workbench_handler = _MODULE.make_workbench_handler
ThreadingHTTPServer = _MODULE.ThreadingHTTPServer

SNAPSHOT_DATE = "20260601"
SEED_A = 100
SEED_B = 400
CAROL = 300


def _release(release_id: int, title: str) -> dict[str, Any]:
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "release_id": release_id,
        "status": "Accepted",
        "title": title,
        "country": None,
        "released": "1995",
        "master_id": None,
        "master_is_main_release": None,
        "data_quality": None,
        "source_url": f"https://example.invalid/release/{release_id}",
    }


def _credit(
    release_id: int,
    *,
    artist_id: int,
    name: str,
    scope: str = "release_artist",
    track_index: int | None = None,
) -> dict[str, Any]:
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "release_id": release_id,
        "track_index": track_index,
        "track_path": None if track_index is None else str(track_index),
        "track_position": None if track_index is None else str(track_index + 1),
        "track_title": None if track_index is None else f"Track {track_index + 1}",
        "credit_scope": scope,
        "artist_id": artist_id,
        "name": name,
        "anv": None,
        "join_text": None,
        "role_text": None,
        "credited_tracks_text": None,
        "is_linked": True,
        "playable_identity": True,
    }


def _performed(release_id: int, *, artist_id: int, name: str) -> list[dict[str, Any]]:
    return [
        _credit(release_id, artist_id=artist_id, name=name, scope="release_artist"),
        _credit(release_id, artist_id=artist_id, name=name, scope="track_artist", track_index=0),
    ]


def _build_corpus(
    root: Path,
    *,
    snapshot_date: str = SNAPSHOT_DATE,
    topic_corpus_version: str | None = None,
    include_release_2: bool = True,
) -> Path:
    """R1: Seed A (billed) + Carol (release-scope). R2 (unless
    `include_release_2=False`): Seed B (billed) + Carol (release-scope) --
    Carol bridges the two albums/artists/scenes. Factored out of the
    `corpus` fixture below so the graph/scope-tier cache tests can build a
    second, genuinely distinct corpus (a different root) or rewrite the
    SAME root's manifest with a new snapshot_date (a simulated
    re-ingestion) without duplicating this whole body.

    `topic_corpus_version`, when given, is written to
    `manifest["topic"]["corpus_version"]` -- the real content-hashed
    identity field a genuine `research-build-corpus` manifest carries
    (`corpus.py`'s own `corpus_version_seed`). Omitted by default so
    every pre-existing test here keeps exercising `corpus_version_string`'s
    directory-name+snapshot_date fallback unchanged; only the tests that
    specifically target the two-different-corpora identity fix below pass
    it explicitly."""
    releases = [_release(1, "Album Alpha")]
    credits = [
        *_performed(1, artist_id=SEED_A, name="Seed A"),
        _credit(1, artist_id=CAROL, name="Carol", scope="release_credit"),
    ]
    if include_release_2:
        releases.append(_release(2, "Album Beta"))
        credits += [
            *_performed(2, artist_id=SEED_B, name="Seed B"),
            _credit(2, artist_id=CAROL, name="Carol", scope="release_credit"),
        ]
    # exist_ok=True: also used to simulate a re-ingestion at an ALREADY
    # existing root (a fresh manifest.json/snapshot_date, same directory).
    (root / "table=releases").mkdir(parents=True, exist_ok=True)
    (root / "table=credits").mkdir(parents=True, exist_ok=True)
    (root / "table=tracks").mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(releases, schema=SCHEMAS["releases"]),
        root / "table=releases" / "part-00000.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist(credits, schema=SCHEMAS["credits"]),
        root / "table=credits" / "part-00000.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist([], schema=SCHEMAS["tracks"]),
        root / "table=tracks" / "part-00000.parquet",
    )
    manifest: dict[str, Any] = {"schema_version": 3, "snapshot_date": snapshot_date}
    if topic_corpus_version is not None:
        manifest["topic"] = {"corpus_version": topic_corpus_version}
    (root / "manifest.json").write_text(json.dumps(manifest))
    return root


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    return _build_corpus(tmp_path / "corpus_root" / f"snapshot={SNAPSHOT_DATE}")


@pytest.fixture
def server(corpus: Path, tmp_path: Path) -> Iterator[tuple[str, Path]]:
    research_root = tmp_path / "research"
    handler = make_workbench_handler(research_root, allowed_corpus_root=tmp_path.resolve())
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}", research_root
    finally:
        httpd.shutdown()
        thread.join()
        httpd.server_close()


def _post_compare(base: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    request = Request(
        f"{base}/api/compare",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request) as response:
            return response.status, json.loads(response.read())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _get_json(url: str) -> tuple[int, dict[str, Any]]:
    try:
        with urlopen(url) as response:
            return response.status, json.loads(response.read())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_workbench_serves_the_form_page(server: tuple[str, Path]) -> None:
    base, _ = server
    body = urlopen(f"{base}/").read().decode()
    assert "research workbench" in body
    assert 'id="form"' in body


def test_workbench_compares_two_albums_end_to_end(server: tuple[str, Path], corpus: Path) -> None:
    base, research_root = server
    status, data = _post_compare(
        base,
        {
            "mode": "albums",
            "corpus_root": str(corpus),
            "topic": "alpha-vs-beta",
            "album_a": 1,
            "album_b": 2,
        },
    )
    assert status == 200
    shared = {p["artist_id"] for p in data["comparison"]["shared_vs_unique"]["recurring_personnel"]}
    assert shared == {CAROL}
    assert (research_root / "alpha-vs-beta" / "runs" / data["run_id"] / "comparison.json").is_file()


def test_workbench_compares_two_artists_end_to_end(server: tuple[str, Path], corpus: Path) -> None:
    base, _ = server
    status, data = _post_compare(
        base,
        {
            "mode": "artists",
            "corpus_root": str(corpus),
            "topic": "seeda-vs-seedb",
            "artist_a": SEED_A,
            "artist_b": SEED_B,
        },
    )
    assert status == 200
    assert data["comparison"]["route"]["case"] == "found"


def test_workbench_compares_two_scenes_end_to_end(server: tuple[str, Path], corpus: Path) -> None:
    base, _ = server
    status, data = _post_compare(
        base,
        {
            "mode": "scenes",
            "corpus_root": str(corpus),
            "topic": "scene-a-vs-scene-b",
            "scene_a": [SEED_A],
            "scene_b": [SEED_B],
        },
    )
    assert status == 200
    assert CAROL in data["comparison"]["shared_collaborators"]["artist_ids"]


def test_workbench_compare_forwards_a_custom_max_hops_override(
    server: tuple[str, Path], corpus: Path
) -> None:
    # A real Codex-review-caught gap: the workbench form had no way to send
    # a non-default max_hops at all, so a "reproducible" saved request could
    # never actually reproduce a run that used one. Seed A and Seed B are 2
    # hops apart (via Carol) -- the default max_hops=4 finds that route (see
    # test_workbench_compares_two_artists_end_to_end), but max_hops=1 must
    # not, proving the override reaches CompareArtistsRequest rather than
    # being silently dropped.
    base, _ = server
    status, data = _post_compare(
        base,
        {
            "mode": "artists",
            "corpus_root": str(corpus),
            "topic": "seeda-vs-seedb-bounded",
            "artist_a": SEED_A,
            "artist_b": SEED_B,
            "max_hops": 1,
        },
    )
    assert status == 200
    assert data["comparison"]["route"]["case"] == "no_path_within_bound"


def test_workbench_compare_forwards_a_custom_max_route_candidate_pairs_override(
    server: tuple[str, Path], corpus: Path
) -> None:
    # Same real gap as above, for CompareScenesRequest's separate
    # max_route_candidate_pairs bound: 0 forces `_route_between` to report
    # "search_bounded" with zero pairs tried before it even looks at the
    # graph -- proof the override was forwarded, not silently dropped in
    # favor of DEFAULT_MAX_ROUTE_CANDIDATE_PAIRS.
    base, _ = server
    status, data = _post_compare(
        base,
        {
            "mode": "scenes",
            "corpus_root": str(corpus),
            "topic": "scene-a-vs-scene-b-bounded",
            "scene_a": [SEED_A],
            "scene_b": [SEED_B],
            "max_route_candidate_pairs": 0,
        },
    )
    assert status == 200
    routes = data["comparison"]["routes_between_sets"]
    assert routes["case"] == "search_bounded"
    assert routes["pairs_tried"] == 0


def test_workbench_rejects_a_real_corpus_outside_the_allowlist(
    server: tuple[str, Path], tmp_path: Path
) -> None:
    # A REAL, validly-shaped corpus (manifest.json and all), just sitting
    # outside `allowed_corpus_root` -- isolates the containment check from
    # the separate "no manifest.json" check `/etc` alone would also trip,
    # which wouldn't actually prove this specific guard fired.
    outside_root = tmp_path.parent / f"outside-{tmp_path.name}" / f"snapshot={SNAPSHOT_DATE}"
    (outside_root / "table=releases").mkdir(parents=True)
    (outside_root / "table=credits").mkdir(parents=True)
    (outside_root / "table=tracks").mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist([_release(1, "Outside")], schema=SCHEMAS["releases"]),
        outside_root / "table=releases" / "part-00000.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist([], schema=SCHEMAS["credits"]),
        outside_root / "table=credits" / "part-00000.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist([], schema=SCHEMAS["tracks"]),
        outside_root / "table=tracks" / "part-00000.parquet",
    )
    (outside_root / "manifest.json").write_text(
        json.dumps({"schema_version": 3, "snapshot_date": SNAPSHOT_DATE})
    )

    base, _ = server
    status, data = _post_compare(
        base,
        {
            "mode": "albums",
            "corpus_root": str(outside_root),
            "topic": "escape-attempt",
            "album_a": 1,
            "album_b": 2,
        },
    )
    assert status == 400
    assert "must resolve under" in data["error"]


def test_workbench_rejects_a_topic_that_is_a_path(server: tuple[str, Path], corpus: Path) -> None:
    base, _ = server
    status, data = _post_compare(
        base,
        {
            "mode": "albums",
            "corpus_root": str(corpus),
            "topic": "../escape",
            "album_a": 1,
            "album_b": 2,
        },
    )
    assert status == 400
    assert "plain name" in data["error"]


def test_workbench_rejects_an_unrecognized_mode(server: tuple[str, Path], corpus: Path) -> None:
    base, _ = server
    status, data = _post_compare(base, {"mode": "bands", "corpus_root": str(corpus), "topic": "x"})
    assert status == 400
    assert "mode" in data["error"]


def test_workbench_reports_a_clean_400_for_missing_required_fields(
    server: tuple[str, Path], corpus: Path
) -> None:
    base, _ = server
    status, data = _post_compare(
        base, {"mode": "albums", "corpus_root": str(corpus), "topic": "missing-fields"}
    )
    assert status == 400
    assert "album_a" in data["error"]


def test_workbench_lists_runs_for_a_topic(server: tuple[str, Path], corpus: Path) -> None:
    base, _ = server
    _post_compare(
        base,
        {
            "mode": "albums",
            "corpus_root": str(corpus),
            "topic": "listed-topic",
            "album_a": 1,
            "album_b": 2,
        },
    )
    with urlopen(f"{base}/api/runs?topic=listed-topic") as response:
        runs = json.loads(response.read())["runs"]
    assert len(runs) == 1
    assert runs[0]["topic"] == "listed-topic"
    assert runs[0]["request"] == {
        "mode": "albums",
        "corpus_snapshot_root": str(corpus),
        "album_a_release_id": 1,
        "album_b_release_id": 2,
        "max_hops": 4,
        "max_route_candidate_pairs": 200,
    }


def test_workbench_lists_a_pre_existing_run_with_no_request_json_as_none(
    server: tuple[str, Path],
) -> None:
    # A run written before request.json existed (or by any other future
    # writer that only produces manifest.json) must still list cleanly,
    # not crash this endpoint.
    base, research_root = server
    run_dir = research_root / "legacy-topic" / "runs" / "20260101T000000Z"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps({"run_id": "20260101T000000Z", "topic": "legacy-topic"})
    )
    with urlopen(f"{base}/api/runs?topic=legacy-topic") as response:
        runs = json.loads(response.read())["runs"]
    assert len(runs) == 1
    assert runs[0]["request"] is None


def test_workbench_runs_list_is_empty_for_an_unknown_topic(server: tuple[str, Path]) -> None:
    base, _ = server
    with urlopen(f"{base}/api/runs?topic=never-run") as response:
        assert json.loads(response.read())["runs"] == []


def test_workbench_search_and_evidence_open_the_graph_without_building_edges(
    server: tuple[str, Path], corpus: Path
) -> None:
    # A real Codex-review-caught bug: both endpoints previously opened
    # CreditGraph with the default build_edges=True, paying the ~2.5-minute
    # edge-materialization cost (CreditGraph.open's own docstring) on every
    # search/evidence request even though neither ever traverses edges.
    # Patching CreditGraph.open to record its own build_edges kwarg is the
    # only way to observe this from outside -- a correct and an incorrect
    # response body look identical; only the cost differs.
    calls: list[bool] = []
    real_open = _MODULE.CreditGraph.open

    def spying_open(*args: Any, **kwargs: Any) -> Any:
        calls.append(kwargs.get("build_edges", True))
        return real_open(*args, **kwargs)

    with mock.patch.object(_MODULE.CreditGraph, "open", staticmethod(spying_open)):
        base, _ = server
        status, _ = _get_json(f"{base}/api/search?corpus_root={corpus}&kind=albums&q=alpha")
        assert status == 200
        status, _ = _get_json(f"{base}/api/evidence?corpus_root={corpus}&kind=album&id=1")
        assert status == 200

    assert len(calls) == 2
    assert calls == [False, False]


def test_workbench_search_finds_albums_by_title_substring(
    server: tuple[str, Path], corpus: Path
) -> None:
    base, _ = server
    status, data = _get_json(f"{base}/api/search?corpus_root={corpus}&kind=albums&q=alpha")
    assert status == 200
    assert data["results"] == [
        {"release_id": 1, "title": "Album Alpha", "released": "1995", "master_id": None}
    ]


def test_workbench_search_finds_artists_by_name_substring(
    server: tuple[str, Path], corpus: Path
) -> None:
    base, _ = server
    status, data = _get_json(f"{base}/api/search?corpus_root={corpus}&kind=artists&q=carol")
    assert status == 200
    assert data["results"] == [{"artist_id": CAROL, "name": "Carol"}]


def test_workbench_search_requires_a_query(server: tuple[str, Path], corpus: Path) -> None:
    base, _ = server
    status, data = _get_json(f"{base}/api/search?corpus_root={corpus}&kind=albums&q=")
    assert status == 400
    assert "q is required" in data["error"]


def test_workbench_search_rejects_a_corpus_outside_the_allowlist(
    server: tuple[str, Path], tmp_path: Path
) -> None:
    base, _ = server
    outside = tmp_path.parent / f"outside-search-{tmp_path.name}"
    status, data = _get_json(f"{base}/api/search?corpus_root={outside}&kind=albums&q=x")
    assert status == 400
    assert "must resolve under" in data["error"]


def test_workbench_evidence_returns_album_credit_rows(
    server: tuple[str, Path], corpus: Path
) -> None:
    base, _ = server
    status, data = _get_json(f"{base}/api/evidence?corpus_root={corpus}&kind=album&id=1")
    assert status == 200
    assert data["release"]["title"] == "Album Alpha"
    assert {row["artist_id"] for row in data["credit_rows"]} == {SEED_A, CAROL}


def test_workbench_evidence_retains_a_non_linked_credit_row(
    server: tuple[str, Path], tmp_path: Path
) -> None:
    # A real Codex-review-caught bug: the plain, roster-only credit-rows
    # method drops non-linked credits entirely -- AGENTS.md requires
    # retaining them as evidence. A second corpus (still under the
    # server's allowlisted tmp_path) with its own non-linked evidence row.
    base, _ = server
    root = tmp_path / "corpus_root_with_non_linked" / f"snapshot={SNAPSHOT_DATE}"
    (root / "table=releases").mkdir(parents=True)
    (root / "table=credits").mkdir(parents=True)
    (root / "table=tracks").mkdir(parents=True)
    non_linked_credit = {
        "snapshot_date": SNAPSHOT_DATE,
        "release_id": 1,
        "track_index": None,
        "track_path": None,
        "track_position": None,
        "track_title": None,
        "credit_scope": "release_credit",
        "artist_id": None,
        "name": "Session Choir",
        "anv": None,
        "join_text": None,
        "role_text": None,
        "credited_tracks_text": None,
        "is_linked": False,
        "playable_identity": False,
    }
    pq.write_table(
        pa.Table.from_pylist([_release(1, "Album With A Choir")], schema=SCHEMAS["releases"]),
        root / "table=releases" / "part-00000.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist(
            [*_performed(1, artist_id=SEED_A, name="Seed A"), non_linked_credit],
            schema=SCHEMAS["credits"],
        ),
        root / "table=credits" / "part-00000.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist([], schema=SCHEMAS["tracks"]),
        root / "table=tracks" / "part-00000.parquet",
    )
    (root / "manifest.json").write_text(json.dumps({"schema_version": 3}))

    status, data = _get_json(f"{base}/api/evidence?corpus_root={root}&kind=album&id=1")
    assert status == 200
    assert {row["name"] for row in data["credit_rows"]} == {"Seed A", "Session Choir"}


def test_workbench_evidence_returns_artist_credit_rows_across_releases(
    server: tuple[str, Path], corpus: Path
) -> None:
    base, _ = server
    status, data = _get_json(f"{base}/api/evidence?corpus_root={corpus}&kind=artist&id={CAROL}")
    assert status == 200
    assert data["name"] == "Carol"
    assert {row["release_id"] for row in data["credit_rows"]} == {1, 2}


def test_workbench_evidence_includes_real_scope_tier_coverage_for_an_artist(
    server: tuple[str, Path], corpus: Path
) -> None:
    base, _ = server
    status, data = _get_json(f"{base}/api/evidence?corpus_root={corpus}&kind=artist&id={CAROL}")
    assert status == 200
    scope_tiers = data["scope_tiers"]
    assert scope_tiers["case"] == "measured"
    tiers = {t["tier"]: t for t in scope_tiers["tiers"]["tiers"]}
    assert set(tiers) == {"A", "B", "C"}
    # Tier A is the whole corpus snapshot, not filtered by artist (see
    # measure_scope_tiers's own docstring) -- both fixture releases count.
    assert tiers["A"]["release_count"] == 2
    # Carol is only ever release_credit-scope in this fixture, never the
    # sole release_artist -- Tier B (and therefore C) must be empty for
    # her, not a guess or a crash.
    assert tiers["B"]["release_count"] == 0
    assert tiers["C"]["release_count"] == 0


def test_workbench_evidence_artist_scope_tiers_differ_from_album_evidence(
    server: tuple[str, Path], corpus: Path
) -> None:
    # scope_tiers is an artist-only field -- album evidence must not carry
    # it (nothing to guess at for a release).
    base, _ = server
    status, data = _get_json(f"{base}/api/evidence?corpus_root={corpus}&kind=album&id=1")
    assert status == 200
    assert "scope_tiers" not in data


def test_workbench_evidence_rejects_an_unknown_album(
    server: tuple[str, Path], corpus: Path
) -> None:
    base, _ = server
    status, data = _get_json(f"{base}/api/evidence?corpus_root={corpus}&kind=album&id=999")
    assert status == 400
    assert "not found" in data["error"]


def test_workbench_evidence_rejects_an_unknown_artist(
    server: tuple[str, Path], corpus: Path
) -> None:
    base, _ = server
    status, data = _get_json(f"{base}/api/evidence?corpus_root={corpus}&kind=artist&id=999999")
    assert status == 400
    assert "not found" in data["error"]


# --- Phase 7 closeout: workbench graph/scope-tier caching (B2/B3) ---------
#
# Both confirmed still-reproducible on `main` before this closeout:
# `run_comparison_and_persist` opened a fresh `CreditGraph` (paying the
# ~2.5-minute `credit_edges` build) on every single `/api/compare` request,
# and `measure_scope_tiers` was recomputed full-corpus on every single
# artist-evidence click -- neither was part of the earlier #179-183
# retroactive Codex-review-fix arc (PR #180's own body lists exactly six
# fixed items; neither of these is among them).


def test_workbench_compare_reuses_one_graph_across_repeated_requests_against_the_same_corpus(
    server: tuple[str, Path], corpus: Path
) -> None:
    calls: list[bool] = []
    real_open = _MODULE.CreditGraph.open

    def spying_open(*args: Any, **kwargs: Any) -> Any:
        calls.append(kwargs.get("build_edges", True))
        return real_open(*args, **kwargs)

    with mock.patch.object(_MODULE.CreditGraph, "open", staticmethod(spying_open)):
        base, _ = server
        for _ in range(3):
            status, _data = _post_compare(
                base,
                {
                    "mode": "artists",
                    "corpus_root": str(corpus),
                    "topic": "reuse-check",
                    "artist_a": SEED_A,
                    "artist_b": SEED_B,
                },
            )
            assert status == 200

    # Exactly one real open (with edges, since compare needs them) despite
    # three separate HTTP requests against the same corpus root.
    assert calls == [True]


def test_workbench_compare_graph_cache_invalidates_when_the_corpus_manifest_changes(
    server: tuple[str, Path], corpus: Path
) -> None:
    real_open = _MODULE.CreditGraph.open
    open_count = 0

    def counting_open(*args: Any, **kwargs: Any) -> Any:
        nonlocal open_count
        open_count += 1
        return real_open(*args, **kwargs)

    def compare_once() -> int:
        status, _ = _post_compare(
            base,
            {
                "mode": "artists",
                "corpus_root": str(corpus),
                "topic": "invalidation-check",
                "artist_a": SEED_A,
                "artist_b": SEED_B,
            },
        )
        assert status == 200
        return status

    with mock.patch.object(_MODULE.CreditGraph, "open", staticmethod(counting_open)):
        base, _ = server
        compare_once()
        assert open_count == 1

        # A SECOND request against the UNCHANGED corpus must reuse the
        # cached graph -- proves this test can actually distinguish "reuse
        # with correct invalidation" from "no caching at all" (which would
        # also happen to show open_count==1 then ==2 across the eventual
        # manifest-changed request below, on its own, with no real cache).
        compare_once()
        assert open_count == 1

        # A re-ingestion at the SAME root rewrites manifest.json with a new
        # snapshot_date -- corpus_version_string's identity changes, so the
        # cached graph must never be silently reused for it.
        _build_corpus(corpus, snapshot_date="20260701")

        compare_once()
        assert open_count == 2


def test_workbench_compare_graph_cache_builds_a_fresh_corpus_only_once_under_concurrent_requests(
    server: tuple[str, Path], corpus: Path
) -> None:
    import time

    real_open = _MODULE.CreditGraph.open
    open_count = 0
    count_lock = threading.Lock()

    def slow_counting_open(*args: Any, **kwargs: Any) -> Any:
        nonlocal open_count
        with count_lock:
            open_count += 1
        # Widens the window a concurrent request could otherwise race into
        # a second, duplicate build if the cache's build_lock didn't
        # actually serialize the check-or-build decision per corpus root.
        time.sleep(0.2)
        return real_open(*args, **kwargs)

    with mock.patch.object(_MODULE.CreditGraph, "open", staticmethod(slow_counting_open)):
        base, _ = server
        results: list[int] = []
        results_lock = threading.Lock()

        def run_one() -> None:
            status, _ = _post_compare(
                base,
                {
                    "mode": "artists",
                    "corpus_root": str(corpus),
                    "topic": "concurrent-check",
                    "artist_a": SEED_A,
                    "artist_b": SEED_B,
                },
            )
            with results_lock:
                results.append(status)

        threads = [threading.Thread(target=run_one) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert results == [200] * 5
    assert open_count == 1


def test_workbench_graph_cache_never_caches_a_failed_build(tmp_path: Path) -> None:
    cache = _MODULE.WorkbenchGraphCache()
    bad_root = tmp_path / "not-a-corpus"
    bad_root.mkdir()

    with pytest.raises(GraphError):
        with cache.checkout(bad_root):
            pass  # pragma: no cover -- checkout() must raise before yielding

    # Nothing was written to the cache for the failed root -- confirmed by
    # checking out a REAL corpus afterward still works cleanly (the failed
    # attempt didn't leave the cache's internal locking/bookkeeping in a
    # broken state for the next, unrelated key).
    good_root = tmp_path / "corpus_root" / f"snapshot={SNAPSHOT_DATE}"
    _build_corpus(good_root)
    with cache.checkout(good_root) as graph:
        assert graph.release(1) is not None
    cache.close_all()


def test_workbench_graph_cache_evicts_the_least_recently_used_entry(tmp_path: Path) -> None:
    cache = _MODULE.WorkbenchGraphCache(max_entries=2)
    roots = [
        _build_corpus(tmp_path / f"corpus-{i}" / f"snapshot={SNAPSHOT_DATE}") for i in range(3)
    ]

    with cache.checkout(roots[0]):
        pass
    with cache.checkout(roots[1]):
        pass
    # Cache now holds roots[0] and roots[1], at max_entries=2. Checking out
    # a THIRD distinct corpus must evict one of them (both are unused --
    # refcount 0 -- at this point, so eviction is free to happen).
    with cache.checkout(roots[2]):
        pass
    assert len(cache._entries) == 2  # internal cache size -- the thing under test

    real_open = _MODULE.CreditGraph.open
    open_calls: list[Path] = []

    def recording_open(dataset_root: Path, **kwargs: Any) -> Any:
        open_calls.append(Path(dataset_root))
        return real_open(dataset_root, **kwargs)

    with mock.patch.object(_MODULE.CreditGraph, "open", staticmethod(recording_open)):
        # roots[0] was the least recently used of the three and should have
        # been the one evicted -- re-checking it out must open it again.
        with cache.checkout(roots[0]):
            pass
    assert open_calls == [roots[0]]

    cache.close_all()


def test_workbench_evidence_computes_scope_tiers_once_for_repeated_clicks_on_the_same_artist(
    server: tuple[str, Path], corpus: Path
) -> None:
    calls = 0
    real_coverage = _MODULE.corpus_coverage

    def counting_coverage(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return real_coverage(*args, **kwargs)

    with mock.patch.object(_MODULE, "corpus_coverage", counting_coverage):
        base, _ = server
        for _ in range(3):
            status, data = _get_json(
                f"{base}/api/evidence?corpus_root={corpus}&kind=artist&id={CAROL}"
            )
            assert status == 200
            assert data["scope_tiers"]["case"] == "measured"

    assert calls == 1


def test_workbench_scope_tier_cache_invalidates_when_the_corpus_manifest_changes(
    server: tuple[str, Path], corpus: Path
) -> None:
    calls = 0
    real_coverage = _MODULE.corpus_coverage

    def counting_coverage(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return real_coverage(*args, **kwargs)

    def load_once() -> None:
        status, _ = _get_json(f"{base}/api/evidence?corpus_root={corpus}&kind=artist&id={CAROL}")
        assert status == 200

    with mock.patch.object(_MODULE, "corpus_coverage", counting_coverage):
        base, _ = server
        load_once()
        assert calls == 1

        # A SECOND request against the UNCHANGED corpus must reuse the
        # cached result -- without this, "1 then 2" across the eventual
        # manifest-changed request below would pass even with no caching
        # at all, proving nothing about invalidation specifically.
        load_once()
        assert calls == 1

        _build_corpus(corpus, snapshot_date="20260701")

        load_once()
        assert calls == 2


def test_workbench_scope_tier_cache_never_caches_a_failed_computation(tmp_path: Path) -> None:
    cache = _MODULE.ScopeTierCache()
    root = _build_corpus(tmp_path / "corpus_root" / f"snapshot={SNAPSHOT_DATE}")

    call_count = 0
    real_coverage = _MODULE.corpus_coverage

    def flaky_coverage(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("simulated transient failure")
        return real_coverage(*args, **kwargs)

    with mock.patch.object(_MODULE, "corpus_coverage", flaky_coverage):
        with pytest.raises(RuntimeError, match="simulated transient failure"):
            cache.get_or_compute(root, CAROL)
        # The failed attempt must not have been cached -- a second call
        # (against the same corpus/artist key) retries rather than
        # re-raising a stale cached failure.
        result = cache.get_or_compute(root, CAROL)
    assert result["case"] == "measured"
    assert call_count == 2


# --- Codex-review follow-up fixes to PR B (#193) ---


def test_workbench_scope_tier_cache_key_distinguishes_corpora_sharing_a_dirname_and_date(
    tmp_path: Path,
) -> None:
    """A real Codex-review finding against `corpus_version_string`'s
    original identity (directory name + manifest snapshot_date only): two
    DIFFERENT topic corpora conventionally share both -- every corpus this
    file builds lives under a `.../snapshot=<date>/` leaf, and two ordinary
    topic corpora built from the same monthly snapshot share the same
    `snapshot_date` too. `ScopeTierCache`'s key is `(identity, artist_id)`
    with no path component at all, so that collision would silently serve
    one corpus's scope tiers for a DIFFERENT corpus's same artist_id.

    root_x and root_y share the exact directory basename
    (`snapshot=20260601`) and `snapshot_date`, but are real, differently
    shaped corpora (root_y omits release 2 entirely) with distinct
    `topic.corpus_version` identities -- the fixed `corpus_version_string`
    must key off that, not the directory name, so Carol's Tier A (the
    whole-snapshot release count, unfiltered by artist) correctly comes
    back as 2 for root_x and 1 for root_y instead of the first answer
    leaking into the second lookup."""
    cache = _MODULE.ScopeTierCache()
    root_x = tmp_path / "topic-x" / "corpus_root" / f"snapshot={SNAPSHOT_DATE}"
    _build_corpus(root_x, topic_corpus_version="topic-x-v1")
    root_y = tmp_path / "topic-y" / "corpus_root" / f"snapshot={SNAPSHOT_DATE}"
    _build_corpus(root_y, topic_corpus_version="topic-y-v1", include_release_2=False)
    assert root_x.name == root_y.name  # the exact collision this test guards against

    tiers_x = cache.get_or_compute(root_x, CAROL)
    tiers_y = cache.get_or_compute(root_y, CAROL)

    tier_a_x = {t["tier"]: t for t in tiers_x["tiers"]["tiers"]}["A"]
    tier_a_y = {t["tier"]: t for t in tiers_y["tiers"]["tiers"]}["A"]
    assert tier_a_x["release_count"] == 2
    assert tier_a_y["release_count"] == 1


def test_workbench_compare_graph_cache_invalidates_on_a_same_root_overwrite_with_unchanged_date(
    server: tuple[str, Path], corpus: Path
) -> None:
    """A real Codex-review finding: `research-build-corpus --overwrite` can
    replace a corpus with different seeds while retaining the same source
    snapshot -- directory name AND `manifest["snapshot_date"]` both stay
    unchanged. The original `corpus_version_string` (dir name + snapshot_date
    only) would then see no identity change at all and keep serving the
    stale cached graph forever. The manifest's real content-hashed
    `topic.corpus_version` changes on exactly this kind of overwrite even
    when snapshot_date doesn't, and must be what actually drives
    invalidation here."""
    real_open = _MODULE.CreditGraph.open
    open_count = 0

    def counting_open(*args: Any, **kwargs: Any) -> Any:
        nonlocal open_count
        open_count += 1
        return real_open(*args, **kwargs)

    def compare_once() -> None:
        status, _ = _post_compare(
            base,
            {
                "mode": "artists",
                "corpus_root": str(corpus),
                "topic": "overwrite-check",
                "artist_a": SEED_A,
                "artist_b": SEED_B,
            },
        )
        assert status == 200

    _build_corpus(corpus, topic_corpus_version="v1")
    with mock.patch.object(_MODULE.CreditGraph, "open", staticmethod(counting_open)):
        base, _ = server
        compare_once()
        assert open_count == 1

        # Reused across a second request against the SAME corpus_version.
        compare_once()
        assert open_count == 1

        # Same root, same snapshot_date, DIFFERENT topic.corpus_version --
        # simulates `--overwrite` with a different seed set.
        _build_corpus(corpus, topic_corpus_version="v2")

        compare_once()
        assert open_count == 2


def test_workbench_graph_cache_evicts_once_a_pinned_entry_that_exceeded_capacity_becomes_idle(
    tmp_path: Path,
) -> None:
    """A real Codex-review finding: eviction previously only ran on the
    insert-a-new-corpus path (inside the `else` branch of `checkout`), never
    when an existing entry's checkout finishes. A burst of concurrent
    checkouts against more distinct corpora than `max_entries` leaves every
    entry pinned (refcount > 0) at insert time, so that insert-time
    eviction has nothing to remove -- and under the old code, NOTHING ever
    retried eviction afterward, so the cache stayed oversized until some
    later, unrelated new-corpus build happened to trigger it again.

    Two corpora held open (refcount 1 each) while a third is checked out
    reproduces exactly that: all three are pinned when the third insert's
    eviction runs, so it can't evict anything, and the cache transiently
    holds 3 entries against `max_entries=2`. Every checkout then finishes
    with no fourth corpus ever built -- the cache must settle back down to
    2 on its own."""
    cache = _MODULE.WorkbenchGraphCache(max_entries=2)
    roots = [
        _build_corpus(tmp_path / f"corpus-{i}" / f"snapshot={SNAPSHOT_DATE}") for i in range(3)
    ]

    with cache.checkout(roots[0]), cache.checkout(roots[1]):
        with cache.checkout(roots[2]):
            # All three pinned right now -- insert-time eviction had no
            # idle candidate, so it transiently exceeded max_entries.
            assert len(cache._entries) == 3
        # roots[2]'s checkout just ended and nothing else changed yet --
        # this is the exact moment the old code left permanently oversized.
        assert len(cache._entries) == 2

    assert len(cache._entries) == 2
    cache.close_all()
