"""Unit tests for graph-expansion Phase 0 slice 0-B's master-level
eligibility gate: `master_studio_eligibility_reason` and
`select_master_main_release_id`."""

from __future__ import annotations

from pathlib import Path

from conftest import SNAPSHOT_DATE, write_synthetic_dataset, write_synthetic_masters
from networked_players_graph_core.graph import CreditGraph
from networked_players_graph_core.master_eligibility import (
    master_studio_eligibility_reason,
    select_master_main_release_id,
)


def _release(release_id: int, *, master_id: int, is_main: bool, released: str = "2001"):
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "release_id": release_id,
        "status": "Accepted",
        "title": f"Release {release_id}",
        "country": None,
        "released": released,
        "master_id": master_id,
        "master_is_main_release": is_main,
        "data_quality": None,
        "source_url": f"https://example.invalid/release/{release_id}",
    }


def _credit(release_id: int, *, artist_id: int = 700, name: str = "Gina"):
    return {
        "snapshot_date": SNAPSHOT_DATE,
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


def _graph_with(tmp_path: Path, *, release_rows, credit_rows, master_rows) -> CreditGraph:
    dataset_root = write_synthetic_dataset(
        tmp_path / "snapshot=20260601", release_rows=release_rows, credit_rows=credit_rows
    )
    masters_root = write_synthetic_masters(tmp_path / "masters", master_rows=master_rows)
    graph = CreditGraph.open(dataset_root)
    graph.attach_masters(masters_root)
    return graph


def test_eligible_when_genre_style_clean_and_main_release_allowed(tmp_path: Path) -> None:
    with _graph_with(
        tmp_path,
        release_rows=[_release(10, master_id=900, is_main=True)],
        credit_rows=[_credit(10)],
        master_rows=[_master_row(900, main_release_id=10)],
    ) as graph:
        reason = master_studio_eligibility_reason(graph, 900, allowed_release_ids=frozenset({10}))
        assert reason is None
        release_id, why = select_master_main_release_id(
            graph, 900, allowed_release_ids=frozenset({10})
        )
    assert (release_id, why) == (10, "master_main_release")


def test_curated_exclusion_wins_before_any_other_check(tmp_path: Path) -> None:
    with _graph_with(
        tmp_path,
        release_rows=[_release(10, master_id=900, is_main=True)],
        credit_rows=[_credit(10)],
        master_rows=[_master_row(900, main_release_id=10)],
    ) as graph:
        reason = master_studio_eligibility_reason(
            graph,
            900,
            allowed_release_ids=frozenset({10}),
            master_exclusions=frozenset({900}),
        )
    assert reason == "curated_master_exclusion"


def test_missing_master_is_not_eligible(tmp_path: Path) -> None:
    with _graph_with(
        tmp_path,
        release_rows=[_release(10, master_id=900, is_main=True)],
        credit_rows=[_credit(10)],
        master_rows=[_master_row(900, main_release_id=10)],
    ) as graph:
        reason = master_studio_eligibility_reason(
            graph, 999_999, allowed_release_ids=frozenset({10})
        )
        release_id, why = select_master_main_release_id(
            graph, 999_999, allowed_release_ids=frozenset({10})
        )
    assert reason == "master_not_in_working_set"
    assert (release_id, why) == (None, "master_not_in_working_set")


def test_non_studio_genre_style_excludes_even_with_an_allowed_release(tmp_path: Path) -> None:
    with _graph_with(
        tmp_path,
        release_rows=[_release(10, master_id=900, is_main=True)],
        credit_rows=[_credit(10)],
        master_rows=[
            _master_row(900, main_release_id=10, genres=["Stage & Screen"], styles=["Soundtrack"])
        ],
    ) as graph:
        reason = master_studio_eligibility_reason(graph, 900, allowed_release_ids=frozenset({10}))
    assert reason is not None
    assert reason.startswith("non_studio_master_genre_style")


def test_no_release_under_the_master_is_format_allowed(tmp_path: Path) -> None:
    with _graph_with(
        tmp_path,
        release_rows=[_release(10, master_id=900, is_main=True)],
        credit_rows=[_credit(10)],
        master_rows=[_master_row(900, main_release_id=10)],
    ) as graph:
        # allowed_release_ids never includes 10 -- nothing under the master passes.
        reason = master_studio_eligibility_reason(graph, 900, allowed_release_ids=frozenset({999}))
        release_id, why = select_master_main_release_id(
            graph, 900, allowed_release_ids=frozenset({999})
        )
    assert reason == "no_format_allowed_release_under_master"
    assert (release_id, why) == (None, "main_release_not_in_working_set")


def test_falls_back_to_earliest_allowed_release_when_main_release_is_not_allowed(
    tmp_path: Path,
) -> None:
    """The measured false negative this module fixes: the master's own
    `main_release_id` (11, a 2010 remaster) fails the format allow-list, but
    an earlier pressing (10, the 2001 original) is allowed -- eligibility
    and main-release selection must both use it, not silently reject the
    whole master."""
    with _graph_with(
        tmp_path,
        release_rows=[
            _release(10, master_id=900, is_main=False, released="2001"),
            _release(11, master_id=900, is_main=True, released="2010"),
        ],
        credit_rows=[_credit(10), _credit(11)],
        master_rows=[_master_row(900, main_release_id=11)],
    ) as graph:
        reason = master_studio_eligibility_reason(graph, 900, allowed_release_ids=frozenset({10}))
        release_id, why = select_master_main_release_id(
            graph, 900, allowed_release_ids=frozenset({10})
        )
    assert reason is None
    assert (release_id, why) == (10, "earliest_allowed_release")


def test_earliest_allowed_release_breaks_ties_by_release_id(tmp_path: Path) -> None:
    with _graph_with(
        tmp_path,
        release_rows=[
            _release(21, master_id=900, is_main=False, released="2001"),
            _release(20, master_id=900, is_main=False, released="2001"),
            _release(30, master_id=900, is_main=True, released="2015"),
        ],
        credit_rows=[_credit(20), _credit(21), _credit(30)],
        master_rows=[_master_row(900, main_release_id=30)],
    ) as graph:
        release_id, why = select_master_main_release_id(
            graph, 900, allowed_release_ids=frozenset({20, 21})
        )
    assert (release_id, why) == (20, "earliest_allowed_release")
