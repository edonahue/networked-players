"""Unit tests for graph-expansion Phase 2 slice 5.2's expansion-candidate
scorer -- the hub-trap-guard components (eligibility, roster_size,
overlap_existing, new_performers) this slice covers."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import SNAPSHOT_DATE, write_synthetic_dataset, write_synthetic_masters
from networked_players_graph_core.graph import CreditGraph
from networked_players_graph_core.score_expansion_candidates import score_expansion_candidates


def _release(release_id: int, *, master_id: int, is_main: bool = True):
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "release_id": release_id,
        "status": "Accepted",
        "title": f"Release {release_id}",
        "country": None,
        "released": "2001",
        "master_id": master_id,
        "master_is_main_release": is_main,
        "data_quality": None,
        "source_url": f"https://example.invalid/release/{release_id}",
    }


def _credit(
    release_id: int,
    *,
    artist_id: int,
    name: str,
    credit_scope: str,
    role_text: str | None,
):
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "release_id": release_id,
        "track_index": None,
        "track_path": None,
        "track_position": None,
        "track_title": None,
        "credit_scope": credit_scope,
        "artist_id": artist_id,
        "name": name,
        "anv": None,
        "join_text": None,
        "role_text": role_text,
        "credited_tracks_text": None,
        "is_linked": True,
        "playable_identity": True,
    }


def _master_row(master_id: int, *, main_release_id: int, genres=None, styles=None, year=2001):
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "master_id": master_id,
        "main_release_id": main_release_id,
        "title": f"Master {master_id}",
        "year": year,
        "genres": genres or ["Rock"],
        "styles": styles or ["Pop Rock"],
        "data_quality": None,
        "source_url": f"https://example.invalid/master/{master_id}",
    }


@pytest.fixture
def graph(tmp_path: Path) -> CreditGraph:
    dataset_root = write_synthetic_dataset(
        tmp_path / "snapshot=20260601",
        release_rows=[_release(10, master_id=900), _release(11, master_id=901)],
        credit_rows=[
            # Master 900's roster: Alice (billing, existing), Bob (billing,
            # new), Cara (a pure non-performer credit -- must NOT count
            # toward the roster at all).
            _credit(10, artist_id=100, name="Alice", credit_scope="release_artist", role_text=None),
            _credit(10, artist_id=200, name="Bob", credit_scope="track_artist", role_text=None),
            _credit(
                10, artist_id=300, name="Cara", credit_scope="release_credit", role_text="Producer"
            ),
            _credit(11, artist_id=400, name="Dan", credit_scope="release_artist", role_text=None),
        ],
    )
    masters_root = write_synthetic_masters(
        tmp_path / "masters",
        master_rows=[
            _master_row(900, main_release_id=10),
            _master_row(901, main_release_id=11),
        ],
    )
    g = CreditGraph.open(dataset_root)
    g.attach_masters(masters_root)
    yield g
    g.close()


def test_eligible_candidate_reports_real_roster_and_overlap(graph: CreditGraph) -> None:
    rows = score_expansion_candidates(
        graph,
        [
            {
                "master_id": 900,
                "artist_id": 100,
                "artist_name": "Alice",
                "sample_title": "Release 10",
            }
        ],
        existing_node_ids=frozenset({100}),
        allowed_release_ids=frozenset({10, 11}),
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["master_id"] == 900
    assert row["artist_id"] == 100
    assert row["artist_name"] == "Alice"
    assert row["sample_title"] == "Release 10"
    assert row["eligibility"] == "eligible"
    assert row["main_release_id"] == 10
    assert row["main_release_selection_reason"] == "master_main_release"
    # Cara's pure-Producer credit must be excluded from the roster entirely.
    assert row["roster_artist_ids"] == [100, 200]
    assert row["roster_size"] == 2
    assert row["overlap_existing"] == 1
    assert row["new_performers"] == 1
    assert row["new_performer_density"] == pytest.approx(0.5)


def test_ineligible_candidate_still_scored_with_no_roster_fields(graph: CreditGraph) -> None:
    rows = score_expansion_candidates(
        graph,
        [{"master_id": 900}],
        existing_node_ids=frozenset(),
        allowed_release_ids=frozenset({10, 11}),
        master_exclusions=frozenset({900}),
    )
    row = rows[0]
    assert row["eligibility"] == "curated_master_exclusion"
    assert row["main_release_id"] is None
    assert row["roster_size"] is None
    assert row["roster_artist_ids"] is None
    assert row["overlap_existing"] is None
    assert row["new_performers"] is None
    assert row["new_performer_density"] is None


def test_editorial_and_private_seed_flags_are_pure_pass_through(graph: CreditGraph) -> None:
    rows = score_expansion_candidates(
        graph,
        [{"master_id": 900}, {"master_id": 901}],
        existing_node_ids=frozenset(),
        allowed_release_ids=frozenset({10, 11}),
        editorial_master_ids=frozenset({900}),
        private_seed_master_ids=frozenset({901}),
    )
    by_master = {row["master_id"]: row for row in rows}
    assert by_master[900]["editorial"] == 1
    assert by_master[900]["in_private_seed"] == 0
    assert by_master[901]["editorial"] == 0
    assert by_master[901]["in_private_seed"] == 1


def test_output_order_matches_input_order(graph: CreditGraph) -> None:
    rows = score_expansion_candidates(
        graph,
        [{"master_id": 901}, {"master_id": 900}],
        existing_node_ids=frozenset(),
        allowed_release_ids=frozenset({10, 11}),
    )
    assert [row["master_id"] for row in rows] == [901, 900]


def test_roster_query_is_one_batched_call_not_one_per_candidate(
    graph: CreditGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[int]] = []
    real = graph.credit_rows_for_releases

    def counting(release_ids):  # type: ignore[no-untyped-def]
        calls.append(sorted(release_ids))
        return real(release_ids)

    monkeypatch.setattr(graph, "credit_rows_for_releases", counting)
    score_expansion_candidates(
        graph,
        [{"master_id": 900}, {"master_id": 901}],
        existing_node_ids=frozenset(),
        allowed_release_ids=frozenset({10, 11}),
    )
    assert calls == [[10, 11]]


def test_quiet_suppresses_progress_output_default_does_not(
    graph: CreditGraph, capsys: pytest.CaptureFixture[str]
) -> None:
    score_expansion_candidates(
        graph,
        [{"master_id": 900}],
        existing_node_ids=frozenset(),
        allowed_release_ids=frozenset({10, 11}),
        quiet=False,
    )
    assert "scoring" in capsys.readouterr().err

    score_expansion_candidates(
        graph,
        [{"master_id": 900}],
        existing_node_ids=frozenset(),
        allowed_release_ids=frozenset({10, 11}),
        quiet=True,
    )
    assert capsys.readouterr().err == ""


# Slice B: bridge_span and coverage_delta.


def _pathfinding_graph_with_anchors() -> dict:
    """Alice (100) is connected to two distinct virtual album-anchor nodes
    (-1, -2, ADR 0058) -- Bob (200) has no graph presence at all. Real CSR
    shape: `neighbors[slot]` is an INDEX into `node_ids`, never the raw
    (possibly negative) node id itself."""
    return {
        "node_ids": [100, 200, -1, -2],
        "offsets": [0, 2, 2, 2, 2],
        "neighbors": [2, 3],
    }


def test_bridge_span_counts_distinct_anchors_reachable_from_the_roster(
    graph: CreditGraph,
) -> None:
    rows = score_expansion_candidates(
        graph,
        [{"master_id": 900}],
        existing_node_ids=frozenset({100}),
        allowed_release_ids=frozenset({10, 11}),
        pathfinding_graph=_pathfinding_graph_with_anchors(),
    )
    assert rows[0]["bridge_span"] == 2


def test_bridge_span_ignores_a_roster_member_absent_from_the_graph(
    graph: CreditGraph,
) -> None:
    """Bob (200) has no row in `node_ids` at all in this fixture -- his
    absence must not raise, and must not silently contribute anchors."""
    pathfinding_graph = _pathfinding_graph_with_anchors()
    pathfinding_graph["node_ids"] = [100, -1]  # Bob (200) is not a node here
    pathfinding_graph["offsets"] = [0, 1, 1]
    pathfinding_graph["neighbors"] = [1]
    rows = score_expansion_candidates(
        graph,
        [{"master_id": 900}],
        existing_node_ids=frozenset({100}),
        allowed_release_ids=frozenset({10, 11}),
        pathfinding_graph=pathfinding_graph,
    )
    assert rows[0]["bridge_span"] == 1


def test_bridge_span_and_coverage_delta_default_to_honest_absence_and_zero(
    graph: CreditGraph,
) -> None:
    """Without a pathfinding_graph, bridge_span is genuinely unknown (None,
    not 0). Without underrepresented_buckets, coverage_delta is really 0
    (an empty gap set and "closes no gap" are the same real answer)."""
    rows = score_expansion_candidates(
        graph,
        [{"master_id": 900}],
        existing_node_ids=frozenset({100}),
        allowed_release_ids=frozenset({10, 11}),
    )
    assert rows[0]["bridge_span"] is None
    assert rows[0]["coverage_delta"] == 0


def test_coverage_delta_counts_matching_underrepresented_buckets(graph: CreditGraph) -> None:
    # Master 900 (from _master_row's defaults): genres=["Rock"],
    # styles=["Pop Rock"], year=2001 -> decade "2000s".
    rows = score_expansion_candidates(
        graph,
        [{"master_id": 900}],
        existing_node_ids=frozenset(),
        allowed_release_ids=frozenset({10, 11}),
        underrepresented_buckets=frozenset({("genres", "Rock"), ("decades", "1990s")}),
    )
    # "Rock" matches; "2000s" (the real decade) does not match "1990s"; the
    # style "Pop Rock" matches nothing in the set -- exactly one real hit.
    assert rows[0]["coverage_delta"] == 1


def test_coverage_delta_adds_no_extra_master_lookup_beyond_eligibility_s_own(
    graph: CreditGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`master_studio_eligibility_reason` and `select_master_main_release_id`
    (existing, reused code) already call `graph.master` once each per
    candidate for their own checks -- this test's real point is that
    `coverage_delta` doesn't add a THIRD, wasted lookup when no
    `underrepresented_buckets` was requested, not that `graph.master` is
    never called at all."""
    calls: list[int] = []
    real_master = graph.master

    def counting_master(master_id: int):  # type: ignore[no-untyped-def]
        calls.append(master_id)
        return real_master(master_id)

    monkeypatch.setattr(graph, "master", counting_master)
    rows = score_expansion_candidates(
        graph,
        [{"master_id": 900}],
        existing_node_ids=frozenset(),
        allowed_release_ids=frozenset({10, 11}),
    )
    assert rows[0]["coverage_delta"] == 0
    # eligibility + main-release-selection's own two calls; nothing extra.
    assert calls == [900, 900]
