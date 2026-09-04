"""Unit tests for the collection-candidate supply stage (graph-expansion
Phase 2, plan section 4 / section 21.3 slice X1) -- seed releases -> masters ->
eligibility -> not already published."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import SNAPSHOT_DATE, write_synthetic_dataset, write_synthetic_masters
from networked_players_graph_core.collection_candidates import derive_collection_candidates
from networked_players_graph_core.graph import CreditGraph


def _release(release_id: int, *, master_id: int | None, released: str = "2001"):
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "release_id": release_id,
        "status": "Accepted",
        "title": f"Release {release_id}",
        "country": None,
        "released": released,
        "master_id": master_id,
        "master_is_main_release": master_id is not None,
        "data_quality": None,
        "source_url": f"https://example.invalid/release/{release_id}",
    }


def _credit(release_id: int, *, artist_id: int, name: str, credit_scope: str = "release_artist"):
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
        "role_text": None,
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
    """Four masters reachable from the seed:

    900 -- clean, eligible, two seed pressings point at it
    901 -- already published (the caller excludes it)
    902 -- non-studio genre (Stage & Screen), so ineligible
    903 -- eligible master, but its main release has no release-artist credit
    """
    dataset_root = write_synthetic_dataset(
        tmp_path / "snapshot=20260601",
        release_rows=[
            _release(10, master_id=900),
            _release(11, master_id=900, released="2005"),  # a second pressing, same master
            _release(20, master_id=901),
            _release(30, master_id=902),
            _release(40, master_id=903),
            _release(50, master_id=None),  # a seed release with no master at all
        ],
        credit_rows=[
            _credit(10, artist_id=100, name="Alice"),
            _credit(11, artist_id=100, name="Alice"),
            _credit(20, artist_id=200, name="Bob"),
            _credit(30, artist_id=300, name="Cara"),
            # Master 903's main release carries only a non-billing credit.
            _credit(40, artist_id=400, name="Dan", credit_scope="release_credit"),
            _credit(50, artist_id=500, name="Eve"),
        ],
    )
    masters_root = write_synthetic_masters(
        tmp_path / "masters",
        master_rows=[
            _master_row(900, main_release_id=10),
            _master_row(901, main_release_id=20),
            _master_row(902, main_release_id=30, genres=["Stage & Screen"]),
            _master_row(903, main_release_id=40),
        ],
    )
    g = CreditGraph.open(dataset_root)
    g.attach_masters(masters_root)
    yield g
    g.close()


_ALLOWED = frozenset({10, 11, 20, 30, 40, 50})
_SEED = [10, 11, 20, 30, 40, 50]


def test_maps_seed_releases_to_unpublished_eligible_masters(graph: CreditGraph) -> None:
    rows = derive_collection_candidates(
        graph,
        _SEED,
        allowed_release_ids=_ALLOWED,
        already_published_master_ids=frozenset({901}),
        quiet=True,
    )

    by_master = {row["master_id"]: row for row in rows}
    # 901 is already published and 50 has no master at all -- neither appears.
    assert sorted(by_master) == [900, 902, 903]

    clean = by_master[900]
    assert clean["eligibility"] == "eligible"
    assert clean["artist_id"] == 100
    assert clean["artist_name"] == "Alice"
    assert clean["main_release_id"] == 10
    assert clean["main_release_selection_reason"] == "master_main_release"
    assert clean["sample_title"] == "Master 900"
    assert clean["year"] == 2001
    # Two seed pressings pointed at this one master.
    assert clean["seed_release_count"] == 2


def test_ineligible_candidates_are_returned_with_a_reason_never_dropped(
    graph: CreditGraph,
) -> None:
    """ "Never hidden from the packet" -- the same discipline
    score_expansion_candidates states. A reviewer must be able to see that a
    collection album was considered and why it cannot be published."""
    rows = derive_collection_candidates(
        graph,
        _SEED,
        allowed_release_ids=_ALLOWED,
        already_published_master_ids=frozenset({901}),
        quiet=True,
    )
    by_master = {row["master_id"]: row for row in rows}

    assert by_master[902]["eligibility"] == "non_studio_master_genre_style: stage & screen"
    assert by_master[902]["main_release_id"] is None

    # Eligible master, but nothing billed on its main release to publish under.
    assert by_master[903]["eligibility"] == "no_release_artist_credit"
    assert by_master[903]["artist_id"] is None


def test_a_curated_master_exclusion_is_honoured(graph: CreditGraph) -> None:
    rows = derive_collection_candidates(
        graph,
        _SEED,
        allowed_release_ids=_ALLOWED,
        master_exclusions=frozenset({900}),
        quiet=True,
    )
    by_master = {row["master_id"]: row for row in rows}
    assert by_master[900]["eligibility"] == "curated_master_exclusion"


def test_already_published_masters_are_excluded_before_eligibility_runs(
    graph: CreditGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Excluding at the source, not after, is what keeps every downstream
    count honest -- and it must not spend a per-master eligibility lookup on
    an album that cannot be added in the first place."""
    import networked_players_graph_core.collection_candidates as module

    checked: list[int] = []
    real = module.master_studio_eligibility_reason

    def counting(graph_arg, master_id, **kwargs):
        checked.append(master_id)
        return real(graph_arg, master_id, **kwargs)

    monkeypatch.setattr(module, "master_studio_eligibility_reason", counting)

    derive_collection_candidates(
        graph,
        _SEED,
        allowed_release_ids=_ALLOWED,
        already_published_master_ids=frozenset({901}),
        quiet=True,
    )
    assert 901 not in checked


def test_rows_are_deterministic_and_shaped_for_the_existing_consumers(
    graph: CreditGraph,
) -> None:
    """Output must be `rank-album-candidates`-shaped so it feeds
    score_expansion_candidates and greedy_marginal_selection unchanged, and
    stable across runs so a round is reproducible."""
    first = derive_collection_candidates(graph, _SEED, allowed_release_ids=_ALLOWED, quiet=True)
    second = derive_collection_candidates(
        graph, list(reversed(_SEED)), allowed_release_ids=_ALLOWED, quiet=True
    )
    assert first == second
    assert [row["master_id"] for row in first] == sorted(row["master_id"] for row in first)

    required = {"master_id", "artist_id", "artist_name", "sample_title", "main_release_id", "year"}
    for row in first:
        assert required <= set(row)

    # greedy_marginal_selection indexes artist_id/main_release_id/master_id
    # directly, so every row the caller forwards to it must carry all three.
    publishable = [row for row in first if row["eligibility"] == "eligible"]
    assert publishable
    for row in publishable:
        assert row["artist_id"] is not None
        assert row["main_release_id"] is not None
