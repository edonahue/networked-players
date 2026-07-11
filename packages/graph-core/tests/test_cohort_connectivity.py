"""Tests for cohort connectivity scoring."""

from __future__ import annotations

import itertools
import time
from pathlib import Path

import duckdb
import pytest

from networked_players_graph_core import cohort_connectivity
from networked_players_graph_core.cohort_connectivity import (
    CohortConnectivityError,
    _bfs_from_seed,
    _run_with_timeout,
    build_connectivity_cohort,
    classify_hop_quality,
    score_pairs,
    seed_results_from_job_output,
    summarize_connectivity,
    validate_connectivity,
)
from networked_players_graph_core.graph import CreditGraph

SOURCE = {
    "source_url": "https://example.invalid/fake-digs-post",
    "page_title": "Fake Digs Post",
    "saved_at": "2026-07-05",
    "operator_note": "",
}


def _resolved_album(*, artist_id: int, release_id: int, master_id: int | None = None):
    return {
        "rank": 1,
        "artist_query": None,
        "title_query": None,
        "resolution_method": "release_id_hint",
        "master_id": master_id,
        "release_id": release_id,
        "title": "Some Title",
        "artist_id": artist_id,
        "artist_name": "Some Artist",
        "year": None,
        "extraction_confidence": "high",
        "warnings": [],
    }


def _resolved(albums, unresolved=None):
    return {
        "schema_version": 1,
        "source": SOURCE,
        "resolver_version": 1,
        "generated_at": "2026-07-05T00:00:00+00:00",
        "dataset_snapshot_date": "20260601",
        "resolved": albums,
        "unresolved": unresolved or [],
    }


def _row(*, artist_id: int, credit_scope: str, role_text: str | None, track_index: int | None = 0):
    """A `CreditGraph.credit_rows` row. `track_index` decides the scope flag
    (ADR 0035): shared -> `same_recording`, otherwise `release_scope_credit`."""
    return {
        "artist_id": artist_id,
        "credit_scope": credit_scope,
        "role_text": role_text,
        "track_index": track_index,
    }


# --- classify_hop_quality: unit tests, no dataset needed ---


def test_classify_co_billed_release_artists() -> None:
    rows_a = [_row(artist_id=100, credit_scope="release_artist", role_text=None)]
    rows_b = [_row(artist_id=200, credit_scope="release_artist", role_text=None)]
    flags = classify_hop_quality(rows_a, rows_b, artist_a_id=100, artist_b_id=200)
    assert flags == ["co_billed_release_artists", "same_recording"]


def test_classify_performer_credit_when_one_side_is_track_performer() -> None:
    rows_a = [_row(artist_id=100, credit_scope="release_artist", role_text=None)]
    rows_b = [_row(artist_id=200, credit_scope="track_credit", role_text="Guitar")]
    flags = classify_hop_quality(rows_a, rows_b, artist_a_id=100, artist_b_id=200)
    assert flags == ["performer_credit", "same_recording"]


def test_classify_billed_artist_fallback_as_same_recording() -> None:
    """A billed artist can be the implicit performer for a guest track."""
    rows_a = [_row(artist_id=100, credit_scope="release_artist", role_text=None, track_index=None)]
    rows_b = [_row(artist_id=200, credit_scope="track_credit", role_text="Featuring")]
    flags = classify_hop_quality(rows_a, rows_b, artist_a_id=100, artist_b_id=200)
    assert flags == ["performer_credit", "same_recording"]


def test_classify_non_performer_only() -> None:
    rows_a = [_row(artist_id=800, credit_scope="release_credit", role_text="Mastered By")]
    rows_b = [_row(artist_id=900, credit_scope="release_credit", role_text="Producer, Engineer")]
    flags = classify_hop_quality(rows_a, rows_b, artist_a_id=800, artist_b_id=900)
    assert flags == ["non_performer_only", "same_recording"]


def test_classify_placeholder_stacks_with_strength_flag() -> None:
    rows_a = [_row(artist_id=1000, credit_scope="release_artist", role_text=None)]
    rows_b = [_row(artist_id=151641, credit_scope="release_artist", role_text=None)]
    flags = classify_hop_quality(rows_a, rows_b, artist_a_id=1000, artist_b_id=151641)
    assert set(flags) == {"co_billed_release_artists", "same_recording", "placeholder_artist_hop"}


def test_classify_release_scope_credit_when_artists_share_no_track() -> None:
    """An album-wide producer never appears on a track_index, so the hop is
    real but weaker than same-recording evidence."""
    rows_a = [_row(artist_id=100, credit_scope="release_artist", role_text=None, track_index=None)]
    rows_b = [
        _row(artist_id=200, credit_scope="release_credit", role_text="Producer", track_index=None)
    ]
    flags = classify_hop_quality(rows_a, rows_b, artist_a_id=100, artist_b_id=200)
    assert flags == ["performer_credit", "release_scope_credit"]


def test_classify_release_scope_credit_when_artists_are_on_different_tracks() -> None:
    rows_a = [_row(artist_id=100, credit_scope="track_artist", role_text=None, track_index=0)]
    rows_b = [_row(artist_id=200, credit_scope="track_artist", role_text=None, track_index=7)]
    flags = classify_hop_quality(rows_a, rows_b, artist_a_id=100, artist_b_id=200)
    assert flags == ["performer_credit", "release_scope_credit"]


# --- _run_with_timeout: unit tests, no dataset/real timing race needed ---


def test_run_with_timeout_returns_value_when_uncapped() -> None:
    assert _run_with_timeout(lambda: None, lambda: 42, timeout_seconds=None) == 42


def test_run_with_timeout_returns_value_when_fast_enough() -> None:
    assert _run_with_timeout(lambda: None, lambda: 42, timeout_seconds=5.0) == 42


def test_run_with_timeout_classifies_interrupted_duckdb_error_as_timeout() -> None:
    # fn() takes far longer than the timeout and then raises duckdb.Error,
    # simulating a query that was actually cancelled by interrupt() -- the
    # timer will have already fired by the time fn() raises.
    def slow_and_erroring() -> None:
        time.sleep(0.2)
        raise duckdb.Error("simulated interrupted query")

    with pytest.raises(TimeoutError):
        _run_with_timeout(lambda: None, slow_and_erroring, timeout_seconds=0.02)


def test_run_with_timeout_reraises_unrelated_duckdb_error() -> None:
    def raises_immediately() -> None:
        raise duckdb.Error("unrelated failure, not a timeout")

    # A generous timeout that will never fire before fn() raises on its own.
    with pytest.raises(duckdb.Error, match="unrelated failure"):
        _run_with_timeout(lambda: None, raises_immediately, timeout_seconds=5.0)


# --- _bfs_from_seed: unit tests ---


def test_bfs_from_seed_raises_timeout_when_deadline_already_passed(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        with pytest.raises(TimeoutError):
            _bfs_from_seed(
                graph,
                100,
                max_hops=3,
                max_frontier_expansion=None,
                neighbor_cache={},
                deadline=time.monotonic() - 1.0,
            )


def test_bfs_from_seed_matches_neighbors_with_uncapped_deadline(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        parent, capped = _bfs_from_seed(
            graph, 100, max_hops=1, max_frontier_expansion=None, neighbor_cache={}, deadline=None
        )
        assert capped == frozenset()
        assert set(parent) == set(graph.neighbors(100))


# --- score_pairs / build_connectivity_cohort: integration, shared dataset_root fixture ---


def test_one_hop_pair_is_easy(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        pairs = score_pairs(
            graph,
            [
                _resolved_album(artist_id=100, release_id=1),
                _resolved_album(artist_id=200, release_id=1),
            ],
            max_hops=3,
        )
    assert len(pairs) == 1
    pair = pairs[0]
    assert pair["status"] == "found"
    assert pair["hop_count"] == 1
    assert pair["difficulty"] == "easy"
    assert pair["hops"][0]["quality_flags"] == ["co_billed_release_artists", "same_recording"]
    assert pair["warnings"] == []


def test_two_hop_pair_is_medium(dataset_root: Path) -> None:
    # Alice(100) -> Cara(300): 2 hops via Bob (R1 then R2), same pair
    # test_graph.py's test_find_path_two_hop already verifies.
    with CreditGraph.open(dataset_root) as graph:
        pairs = score_pairs(
            graph,
            [
                _resolved_album(artist_id=100, release_id=1),
                _resolved_album(artist_id=300, release_id=2),
            ],
            max_hops=3,
        )
    pair = pairs[0]
    assert pair["status"] == "found"
    assert pair["hop_count"] == 2
    assert pair["difficulty"] == "medium"


def test_no_path_pair_kept_not_dropped(dataset_root: Path) -> None:
    # Same pair as above, but max_hops=1 makes it unreachable -- test_graph.py's
    # test_find_path_none_when_max_hops_too_small already verifies this at the
    # CreditGraph level.
    with CreditGraph.open(dataset_root) as graph:
        pairs = score_pairs(
            graph,
            [
                _resolved_album(artist_id=100, release_id=1),
                _resolved_album(artist_id=300, release_id=2),
            ],
            max_hops=1,
        )
    assert len(pairs) == 1
    pair = pairs[0]
    assert pair["status"] == "no_path"
    assert pair["hop_count"] is None
    assert pair["difficulty"] is None
    assert pair["hops"] == []
    assert pair["skip_reason"] is None


def test_score_pairs_matches_find_path_on_shared_fixture(dataset_root: Path) -> None:
    """score_pairs no longer calls CreditGraph.find_path per pair (see ADR
    0030) -- this proves the BFS-with-shared-cache substrate it uses instead
    produces identical results to the reference per-pair implementation."""
    albums = [
        _resolved_album(artist_id=100, release_id=1),  # Alice
        _resolved_album(artist_id=300, release_id=2),  # Cara
        _resolved_album(artist_id=500, release_id=4),  # Eve
        _resolved_album(artist_id=400, release_id=3),  # Dan
    ]
    with CreditGraph.open(dataset_root) as graph:
        pairs = score_pairs(graph, albums, max_hops=4)

        for pair in pairs:
            assert pair["status"] != "skipped"
            expected = graph.find_path(pair["artist_a_id"], pair["artist_b_id"], max_hops=4)
            if expected is None:
                assert pair["status"] == "no_path"
            else:
                assert pair["status"] == "found"
                assert pair["hop_count"] == len(expected.hops)
                assert [h["release_id"] for h in pair["hops"]] == [
                    h.release_id for h in expected.hops
                ]


def test_score_pairs_concurrent_matches_sequential(dataset_root: Path) -> None:
    """max_workers > 1 must produce byte-for-byte the same pairs as the
    default sequential path -- concurrency is purely a performance lever
    (each seed's own cursor shares the same materialized tables), never a
    source of different results."""
    albums = [
        _resolved_album(artist_id=100, release_id=1),  # Alice
        _resolved_album(artist_id=300, release_id=2),  # Cara
        _resolved_album(artist_id=500, release_id=4),  # Eve
        _resolved_album(artist_id=400, release_id=3),  # Dan
        _resolved_album(artist_id=600, release_id=7),  # Frank
    ]
    with CreditGraph.open(dataset_root) as graph:
        sequential = score_pairs(graph, albums, max_hops=4, max_workers=1)
        concurrent = score_pairs(graph, albums, max_hops=4, max_workers=4)

    assert concurrent == sequential


def test_score_pairs_with_precomputed_seed_results_matches_local(dataset_root: Path) -> None:
    """Keep the legacy precomputed seed representation as a correctness reference."""
    albums = [
        _resolved_album(artist_id=100, release_id=1),  # Alice
        _resolved_album(artist_id=300, release_id=2),  # Cara
        _resolved_album(artist_id=500, release_id=4),  # Eve
        _resolved_album(artist_id=400, release_id=3),  # Dan
    ]
    artist_ids = sorted({a["artist_id"] for a in albums})

    with CreditGraph.open(dataset_root) as graph:
        local = score_pairs(graph, albums, max_hops=4)

        neighbor_cache: dict[int, dict[int, tuple[int, ...]]] = {}
        raw_job_output = {}
        for artist_id in artist_ids:
            parent, capped = _bfs_from_seed(
                graph,
                artist_id,
                max_hops=4,
                max_frontier_expansion=300,
                neighbor_cache=neighbor_cache,
                deadline=None,
            )
            raw_job_output[str(artist_id)] = {
                "status": "ok",
                "parent": [[a, p, r] for a, (p, r) in parent.items()],
                "capped": sorted(capped),
            }

        precomputed = seed_results_from_job_output(raw_job_output)
        via_fleet = score_pairs(graph, albums, max_hops=4, precomputed_seed_results=precomputed)

    assert via_fleet == local


def test_score_pairs_rejects_precomputed_seed_results_missing_an_artist(
    dataset_root: Path,
) -> None:
    albums = [
        _resolved_album(artist_id=100, release_id=1),
        _resolved_album(artist_id=300, release_id=2),
    ]
    with CreditGraph.open(dataset_root) as graph:
        with pytest.raises(CohortConnectivityError, match="missing artist_id"):
            score_pairs(graph, albums, precomputed_seed_results={100: (100, {}, frozenset(), None)})


def test_credit_graph_cursor_shares_materialized_tables(dataset_root: Path) -> None:
    """A cursor must see the same data as the graph it was made from,
    including tables materialized at open() time (not just views)."""
    with CreditGraph.open(dataset_root) as graph:
        cursor_graph = graph.cursor()
        assert cursor_graph.degree(100) == graph.degree(100)
        assert cursor_graph.neighbors(100) == graph.neighbors(100)


def _skip_release(release_id: int, *, master_id: int) -> dict[str, object]:
    return {
        "snapshot_date": "20260601",
        "release_id": release_id,
        "status": "Accepted",
        "title": f"Release {release_id}",
        "country": None,
        "released": "2001",
        "master_id": master_id,
        "master_is_main_release": True,
        "data_quality": None,
        "source_url": f"https://example.invalid/release/{release_id}",
    }


def _skip_credit(release_id: int, *, artist_id: int, name: str) -> list[dict[str, object]]:
    """A billed artist who also performs on the release's one track. Two rows:
    since ADR 0035 an edge needs same-recording evidence, a credit with no
    `track_index` makes nobody adjacent. Splat into a `credit_rows` list."""
    base: dict[str, object] = {
        "snapshot_date": "20260601",
        "release_id": release_id,
        "track_index": None,
        "track_path": None,
        "track_position": None,
        "track_title": None,
        "credit_scope": "release_artist",
        "artist_id": artist_id,
        "name": name,
        "anv": None,
        "join_text": None,
        "role_text": "Performer",
        "credited_tracks_text": None,
        "is_linked": True,
        "playable_identity": True,
    }
    track: dict[str, object] = {
        **base,
        "track_index": 0,
        "track_path": "0",
        "track_position": "1",
        "track_title": "Track 1",
        "credit_scope": "track_artist",
        "role_text": None,
    }
    return [base, track]


def test_pair_meeting_at_a_capped_hub_is_found(tmp_path: Path) -> None:
    """S and T are only connected via Hub at hop 2, and Hub's release count
    (4) exceeds max_frontier_expansion (2). Under the single-direction BFS
    this was unprovable (skipped/frontier_too_large: finding T required
    *expanding* Hub). Bidirectional reach scoring finds it: both sides reach
    Hub as a *target* -- which the cap has always explicitly allowed -- and
    the pair meets there with real shared-credit evidence on both hops."""
    from conftest import write_synthetic_dataset

    root = write_synthetic_dataset(
        tmp_path / "snapshot=20260601",
        release_rows=[_skip_release(i, master_id=900 + i) for i in range(1, 5)],
        credit_rows=[
            *_skip_credit(1, artist_id=1000, name="S"),
            *_skip_credit(1, artist_id=2000, name="Hub"),
            *_skip_credit(2, artist_id=2000, name="Hub"),
            *_skip_credit(2, artist_id=3001, name="P1"),
            *_skip_credit(3, artist_id=2000, name="Hub"),
            *_skip_credit(3, artist_id=3002, name="P2"),
            *_skip_credit(4, artist_id=2000, name="Hub"),
            *_skip_credit(4, artist_id=4000, name="T"),
        ],
    )
    with CreditGraph.open(root) as graph:
        pairs = score_pairs(
            graph,
            [
                _resolved_album(artist_id=1000, release_id=1),
                _resolved_album(artist_id=4000, release_id=4),
            ],
            max_hops=2,
            max_frontier_expansion=2,
            pair_timeout_seconds=None,
        )
    assert len(pairs) == 1
    pair = pairs[0]
    assert pair["status"] == "found"
    assert pair["hop_count"] == 2
    assert [(h["artist_a_id"], h["artist_b_id"]) for h in pair["hops"]] == [
        (1000, 2000),
        (2000, 4000),
    ]
    assert [h["release_id"] for h in pair["hops"]] == [1, 4]


def test_score_pairs_reports_frontier_too_large_not_no_path(tmp_path: Path) -> None:
    """S and T are only connected through TWO consecutive capped hubs
    (S - HubA - HubB - T): the HubA-HubB edge can only be discovered by
    expanding a capped artist, which neither side may do, so even the
    bidirectional meet cannot prove reachability -- and an unprovable pair
    must never be reported as a confirmed no_path."""
    from conftest import write_synthetic_dataset

    hub_a, hub_b = 2000, 2500
    credit_rows = [
        *_skip_credit(1, artist_id=1000, name="S"),
        *_skip_credit(1, artist_id=hub_a, name="HubA"),
        *_skip_credit(2, artist_id=hub_a, name="HubA"),
        *_skip_credit(2, artist_id=hub_b, name="HubB"),
        *_skip_credit(3, artist_id=hub_b, name="HubB"),
        *_skip_credit(3, artist_id=4000, name="T"),
    ]
    # Pad both hubs past the cap with filler releases.
    for i, hub in enumerate((hub_a, hub_a, hub_b, hub_b)):
        release_id = 10 + i
        credit_rows.extend(_skip_credit(release_id, artist_id=hub, name="Hub"))
        credit_rows.extend(_skip_credit(release_id, artist_id=5000 + i, name=f"F{i}"))
    release_rows = [_skip_release(i, master_id=900 + i) for i in (1, 2, 3, 10, 11, 12, 13)]

    root = write_synthetic_dataset(
        tmp_path / "snapshot=20260601", release_rows=release_rows, credit_rows=credit_rows
    )
    with CreditGraph.open(root) as graph:
        pairs = score_pairs(
            graph,
            [
                _resolved_album(artist_id=1000, release_id=1),
                _resolved_album(artist_id=4000, release_id=3),
            ],
            max_hops=3,
            max_frontier_expansion=2,
            pair_timeout_seconds=None,
        )
    assert len(pairs) == 1
    pair = pairs[0]
    assert pair["status"] == "skipped"
    assert pair["skip_reason"] == "frontier_too_large"
    assert pair["hop_count"] is None
    assert pair["difficulty"] is None
    assert pair["hops"] == []


def test_score_pairs_reports_seed_expansion_timeout(
    dataset_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Local scoring's hot path is _ReachScorer._expand_hop (one DuckDB
    # statement per hop) -- mock the method actually on the hot path, or this
    # deterministically-slow mock silently stops applying and the test's 50ms
    # budget becomes a real-timing race against unmocked DuckDB overhead
    # instead of a reliable timeout trigger. The timeout fires via
    # expand_seed's cooperative deadline check between hops, the same
    # mechanism a real run relies on when a hop finishes but the budget is
    # already spent.
    original_expand_hop = cohort_connectivity._ReachScorer._expand_hop

    def slow_expand_hop(self: cohort_connectivity._ReachScorer, seed_artist_id: int, dist: int):
        time.sleep(0.2)
        return original_expand_hop(self, seed_artist_id, dist)

    monkeypatch.setattr(cohort_connectivity._ReachScorer, "_expand_hop", slow_expand_hop)

    with CreditGraph.open(dataset_root) as graph:
        pairs = score_pairs(
            graph,
            [
                _resolved_album(artist_id=100, release_id=1),  # Alice
                _resolved_album(artist_id=300, release_id=2),  # Cara, 2 hops away
            ],
            max_hops=3,
            pair_timeout_seconds=0.05,
        )
    assert len(pairs) == 1
    assert pairs[0]["status"] == "skipped"
    assert pairs[0]["skip_reason"] == "seed_expansion_timeout"


def test_placeholder_artist_is_no_longer_a_live_hop_endpoint(tmp_path: Path) -> None:
    """The inverse of the old ADR 0029 regression test. `CreditGraph` used to
    exclude only artist 194, so 151641 ("Trad.") was a live `find_path`
    endpoint and the scorer could only flag it after the fact. ADR 0035 keeps
    both out of `credit_edges`, so the hop cannot be built at all."""
    from conftest import write_synthetic_dataset

    def _release(release_id, title, master_id=None, master_is_main_release=None):
        return {
            "snapshot_date": "20260601",
            "release_id": release_id,
            "status": "Accepted",
            "title": title,
            "country": None,
            "released": "2001",
            "master_id": master_id,
            "master_is_main_release": master_is_main_release,
            "data_quality": None,
            "source_url": f"https://example.invalid/release/{release_id}",
        }

    def _credit(release_id, artist_id, name, *, scope="release_artist", track_index=None):
        return {
            "snapshot_date": "20260601",
            "release_id": release_id,
            "track_index": track_index,
            "track_path": None if track_index is None else str(track_index),
            "track_position": None if track_index is None else "1",
            "track_title": None if track_index is None else "Track 1",
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

    root = write_synthetic_dataset(
        tmp_path / "snapshot=20260601",
        release_rows=[_release(30, "Traditional Session")],
        credit_rows=[
            _credit(30, 1000, "Zed"),
            _credit(30, 1000, "Zed", scope="track_artist", track_index=0),
            _credit(30, 151641, "Trad."),
            _credit(30, 151641, "Trad.", scope="track_artist", track_index=0),
        ],
    )
    with CreditGraph.open(root) as graph:
        # Both hold a playable credit on the same track, yet no edge exists.
        assert graph.neighbors(1000) == {}
        assert graph.degree(151641) == 0
        assert graph.find_path(1000, 151641) is None


def test_dataset_snapshot_date_mismatch_raises(dataset_root: Path) -> None:
    resolved = _resolved(
        [_resolved_album(artist_id=100, release_id=1), _resolved_album(artist_id=200, release_id=1)]
    )
    resolved["dataset_snapshot_date"] = "20250101"
    with CreditGraph.open(dataset_root) as graph, pytest.raises(CohortConnectivityError):
        build_connectivity_cohort(graph, resolved, dataset_snapshot_date="20260601")


def test_max_pairs_safety_valve_aborts(dataset_root: Path) -> None:
    albums = [
        _resolved_album(artist_id=100, release_id=1),
        _resolved_album(artist_id=200, release_id=1),
        _resolved_album(artist_id=300, release_id=2),
    ]
    resolved = _resolved(albums)  # 3 albums -> 3 pairs
    with (
        CreditGraph.open(dataset_root) as graph,
        pytest.raises(CohortConnectivityError) as exc_info,
    ):
        build_connectivity_cohort(graph, resolved, dataset_snapshot_date="20260601", max_pairs=2)
    assert "3" in str(exc_info.value)


def test_build_connectivity_cohort_round_trips_through_validation(dataset_root: Path) -> None:
    resolved = _resolved(
        [
            _resolved_album(artist_id=100, release_id=1),
            _resolved_album(artist_id=200, release_id=1),
        ],
        unresolved=[{"artist": "Ghost", "title": "Nowhere", "reason": "no match"}],
    )
    with CreditGraph.open(dataset_root) as graph:
        artifact = build_connectivity_cohort(graph, resolved, dataset_snapshot_date="20260601")
    validate_connectivity(artifact)
    assert artifact["source"] == SOURCE
    assert artifact["unresolved"] == resolved["unresolved"]


# --- validate_connectivity rejections ---


def _valid_artifact():
    return {
        "schema_version": 1,
        "source": SOURCE,
        "scorer_version": 1,
        "generated_at": "2026-07-05T00:00:00+00:00",
        "dataset_snapshot_date": "20260601",
        "max_hops": 3,
        "pairs": [
            {
                "album_a_id": "release-1",
                "album_b_id": "release-2",
                "artist_a_id": 100,
                "artist_b_id": 200,
                "status": "found",
                "hop_count": 1,
                "difficulty": "easy",
                "hops": [
                    {
                        "release_id": 1,
                        "artist_a_id": 100,
                        "artist_b_id": 200,
                        "quality_flags": ["co_billed_release_artists"],
                    }
                ],
                "warnings": [],
                "skip_reason": None,
            }
        ],
        "unresolved": [],
    }


def test_validate_rejects_bad_status() -> None:
    artifact = _valid_artifact()
    artifact["pairs"][0]["status"] = "maybe"
    with pytest.raises(CohortConnectivityError):
        validate_connectivity(artifact)


def test_validate_rejects_bad_difficulty() -> None:
    artifact = _valid_artifact()
    artifact["pairs"][0]["difficulty"] = "impossible"
    with pytest.raises(CohortConnectivityError):
        validate_connectivity(artifact)


def test_validate_rejects_no_path_pair_with_hop_count() -> None:
    artifact = _valid_artifact()
    artifact["pairs"][0]["status"] = "no_path"
    # hop_count/difficulty left non-null -- invalid for no_path.
    with pytest.raises(CohortConnectivityError):
        validate_connectivity(artifact)


def test_validate_rejects_hop_without_strength_flag() -> None:
    artifact = _valid_artifact()
    artifact["pairs"][0]["hops"][0]["quality_flags"] = ["placeholder_artist_hop"]
    with pytest.raises(CohortConnectivityError):
        validate_connectivity(artifact)


def test_validate_rejects_skipped_pair_without_skip_reason() -> None:
    artifact = _valid_artifact()
    artifact["pairs"][0]["status"] = "skipped"
    artifact["pairs"][0]["hop_count"] = None
    artifact["pairs"][0]["difficulty"] = None
    # skip_reason left None -- invalid for skipped.
    with pytest.raises(CohortConnectivityError):
        validate_connectivity(artifact)


def test_validate_rejects_skipped_pair_with_invalid_skip_reason() -> None:
    artifact = _valid_artifact()
    artifact["pairs"][0]["status"] = "skipped"
    artifact["pairs"][0]["hop_count"] = None
    artifact["pairs"][0]["difficulty"] = None
    artifact["pairs"][0]["skip_reason"] = "vibes"
    with pytest.raises(CohortConnectivityError):
        validate_connectivity(artifact)


def test_validate_rejects_found_pair_with_nonnull_skip_reason() -> None:
    artifact = _valid_artifact()
    artifact["pairs"][0]["skip_reason"] = "frontier_too_large"
    with pytest.raises(CohortConnectivityError):
        validate_connectivity(artifact)


def test_validate_accepts_well_formed_skipped_pair() -> None:
    artifact = _valid_artifact()
    artifact["pairs"][0]["status"] = "skipped"
    artifact["pairs"][0]["hop_count"] = None
    artifact["pairs"][0]["difficulty"] = None
    artifact["pairs"][0]["hops"] = []
    artifact["pairs"][0]["skip_reason"] = "seed_expansion_timeout"
    validate_connectivity(artifact)  # must not raise


def test_validate_rejects_forbidden_substring() -> None:
    artifact = _valid_artifact()
    artifact["source"] = {**SOURCE, "operator_note": "see local/analysis/x"}
    with pytest.raises(CohortConnectivityError):
        validate_connectivity(artifact)


# --- summarize_connectivity: pure Python, no graph dependency ---


def test_summarize_connectivity_filters_and_sorts_playable_pairs() -> None:
    artifact = _valid_artifact()
    artifact["pairs"].append(
        {
            "album_a_id": "release-3",
            "album_b_id": "release-4",
            "artist_a_id": 300,
            "artist_b_id": 400,
            "status": "no_path",
            "hop_count": None,
            "difficulty": None,
            "hops": [],
            "warnings": [],
            "skip_reason": None,
        }
    )
    playable_pairs, _ = summarize_connectivity(artifact)
    assert len(playable_pairs) == 1
    assert playable_pairs[0]["album_a_id"] == "release-1"


def test_summarize_connectivity_report_sections_and_tone() -> None:
    artifact = _valid_artifact()
    artifact["pairs"][0]["warnings"] = [
        "hop 1 (release 1) connects artist 100 and 200 only via ..."
    ]
    artifact["unresolved"] = [{"artist": "Ghost", "title": "Nowhere", "reason": "no match"}]
    _, report = summarize_connectivity(artifact)
    for heading in (
        "## Header",
        "## Summary counts",
        "## Flagged pairs",
        "## No-path pairs",
        "## Skipped pairs",
        "## Unresolved albums carried forward",
    ):
        assert heading in report
    assert "Ghost" in report
    assert "worked with" not in report.lower()
    assert "collaborated with" not in report.lower()


def test_summarize_connectivity_reports_skipped_pairs_with_reason() -> None:
    artifact = _valid_artifact()
    artifact["pairs"].append(
        {
            "album_a_id": "release-5",
            "album_b_id": "release-6",
            "artist_a_id": 500,
            "artist_b_id": 600,
            "status": "skipped",
            "hop_count": None,
            "difficulty": None,
            "hops": [],
            "warnings": [],
            "skip_reason": "frontier_too_large",
        }
    )
    playable_pairs, report = summarize_connectivity(artifact)
    # Skipped pairs are never in the playable pool.
    assert all(p["album_a_id"] != "release-5" for p in playable_pairs)
    assert "Skipped (reachability not confirmed): 1" in report
    assert "frontier_too_large" in report
    assert "release-5" in report and "release-6" in report


# --- ADR 0033: bidirectional reach scoring behaviors ---


def _chain_dataset(tmp_path: Path) -> Path:
    """A 4-hop chain 1000 - 2000 - 3000 - 4000 - 5000, one release per edge."""
    from conftest import write_synthetic_dataset

    artists = [1000, 2000, 3000, 4000, 5000]
    credit_rows = []
    for edge_index, (left, right) in enumerate(itertools.pairwise(artists)):
        release_id = edge_index + 1
        credit_rows.extend(_skip_credit(release_id, artist_id=left, name=f"A{left}"))
        credit_rows.extend(_skip_credit(release_id, artist_id=right, name=f"A{right}"))
    release_rows = [_skip_release(i, master_id=900 + i) for i in range(1, 5)]
    return write_synthetic_dataset(
        tmp_path / "snapshot=20260601", release_rows=release_rows, credit_rows=credit_rows
    )


def test_three_hop_pair_found_by_meeting_in_the_middle(tmp_path: Path) -> None:
    """At max_hops=3 each seed only expands 2 hops (expansion_depth) -- a
    3-hop pair is only discoverable where the two reaches meet (2+1), never
    by either side alone. Also proves a 1-hop pair and a genuinely-too-far
    pair (4 hops) resolve correctly in the same run."""
    root = _chain_dataset(tmp_path)
    with CreditGraph.open(root) as graph:
        pairs = score_pairs(
            graph,
            [
                _resolved_album(artist_id=1000, release_id=1),
                _resolved_album(artist_id=4000, release_id=3),
                _resolved_album(artist_id=5000, release_id=4),
            ],
            max_hops=3,
            pair_timeout_seconds=None,
        )
    by_artists = {(p["artist_a_id"], p["artist_b_id"]): p for p in pairs}

    three_hop = by_artists[(1000, 4000)]
    assert three_hop["status"] == "found"
    assert three_hop["hop_count"] == 3
    assert [h["release_id"] for h in three_hop["hops"]] == [1, 2, 3]

    one_hop = by_artists[(4000, 5000)]
    assert one_hop["status"] == "found"
    assert one_hop["hop_count"] == 1

    # 4 hops apart, nothing capped, nothing failed: a trusted no_path within
    # max_hops -- both sides' complete depth-2 reaches prove any path would
    # have produced a meeting artist at combined distance <= 4 > 3 is the
    # minimum, so no <=3-hop path exists.
    four_hop = by_artists[(1000, 5000)]
    assert four_hop["status"] == "no_path"
    assert four_hop["skip_reason"] is None


def test_seed_over_the_frontier_cap_still_expands(tmp_path: Path) -> None:
    """Every real cohort seed measured is a hub by the release-count proxy
    (min 712 vs the default cap of 300) -- the cap must never apply to the
    seed itself at dist 0, or no cohort BFS can ever start."""
    from conftest import write_synthetic_dataset

    credit_rows = [
        *_skip_credit(1, artist_id=1000, name="S"),
        *_skip_credit(1, artist_id=4000, name="T"),
    ]
    # Pad S past the cap of 2 with filler releases.
    for i in range(4):
        release_id = 10 + i
        credit_rows.extend(_skip_credit(release_id, artist_id=1000, name="S"))
        credit_rows.extend(_skip_credit(release_id, artist_id=5000 + i, name=f"F{i}"))
    release_rows = [_skip_release(i, master_id=900 + i) for i in (1, 10, 11, 12, 13)]
    root = write_synthetic_dataset(
        tmp_path / "snapshot=20260601", release_rows=release_rows, credit_rows=credit_rows
    )
    with CreditGraph.open(root) as graph:
        assert graph.degree(1000) == 5  # would be capped at 2 as a non-seed
        pairs = score_pairs(
            graph,
            [
                _resolved_album(artist_id=1000, release_id=1),
                _resolved_album(artist_id=4000, release_id=1),
            ],
            max_hops=2,
            max_frontier_expansion=2,
            pair_timeout_seconds=None,
        )
    assert pairs[0]["status"] == "found"
    assert pairs[0]["hop_count"] == 1


def test_score_pairs_reports_reach_too_large(dataset_root: Path) -> None:
    """A seed whose materialized reach exceeds max_reach_rows is reported
    skipped/reach_too_large -- refused, never ground on or truncated."""
    with CreditGraph.open(dataset_root) as graph:
        pairs = score_pairs(
            graph,
            [
                _resolved_album(artist_id=100, release_id=1),
                _resolved_album(artist_id=300, release_id=2),
            ],
            max_hops=3,
            max_reach_rows=1,
            pair_timeout_seconds=None,
        )
    assert pairs[0]["status"] == "skipped"
    assert pairs[0]["skip_reason"] == "reach_too_large"


def test_validate_accepts_reach_too_large_skip_reason() -> None:
    artifact = _valid_artifact()
    artifact["pairs"][0]["status"] = "skipped"
    artifact["pairs"][0]["hop_count"] = None
    artifact["pairs"][0]["difficulty"] = None
    artifact["pairs"][0]["hops"] = []
    artifact["pairs"][0]["skip_reason"] = "reach_too_large"
    validate_connectivity(artifact)  # must not raise


def test_validate_rejects_non_dict_scoring_params() -> None:
    artifact = _valid_artifact()
    artifact["scoring_params"] = "max_hops=3"
    with pytest.raises(CohortConnectivityError, match="scoring_params"):
        validate_connectivity(artifact)


def test_artifact_records_scoring_params_and_fills_diagnostics(dataset_root: Path) -> None:
    """A run's parameters must be recoverable from the artifact itself (the
    crashed real run's settings were not), and the diagnostics side-channel
    must carry the per-seed telemetry the artifact deliberately omits."""
    resolved = _resolved(
        [
            _resolved_album(artist_id=100, release_id=1),
            _resolved_album(artist_id=300, release_id=2),
        ]
    )
    diagnostics: dict = {}
    with CreditGraph.open(dataset_root) as graph:
        artifact = build_connectivity_cohort(
            graph,
            resolved,
            dataset_snapshot_date="20260601",
            max_hops=3,
            duckdb_settings={"memory_limit": "1GB", "threads": 2},
            diagnostics=diagnostics,
        )
    validate_connectivity(artifact)

    params = artifact["scoring_params"]
    assert params["strategy"] == "bidirectional_reach"
    assert params["expansion_depth"] == 2
    assert params["max_frontier_expansion"] == 300
    assert params["memory_limit"] == "1GB"
    assert params["threads"] == 2

    assert diagnostics["strategy"] == "bidirectional_reach"
    assert diagnostics["seed_count"] == 2
    assert {entry["artist_id"] for entry in diagnostics["seeds"]} == {100, 300}
    for entry in diagnostics["seeds"]:
        assert entry["status"] == "ok"
        assert entry["reach_rows_by_dist"]["0"] == 1
    assert diagnostics["reach_total_rows"] >= 2
    assert diagnostics["wall_s"] >= 0

    # The params line must surface in the operator-facing review report too.
    _, report = summarize_connectivity(artifact)
    assert "- Scoring params: " in report
    assert "strategy=bidirectional_reach" in report
