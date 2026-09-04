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
