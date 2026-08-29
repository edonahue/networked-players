"""Phase 7 PR D, Slice 2: `compare_artists`, reusing test_compare.py's
synthetic fixture (SEED_A/CAROL/SEED_B/etc.) -- artists are given directly
here, no release resolution needed, unlike compare_albums."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from networked_players_graph_core.graph import CreditGraph
from networked_players_research.compare import (
    CompareArtistsRequest,
    CompareError,
    _era_counts,
    compare_artists,
)

from .test_compare import BOB, CAROL, DAN, SEED_A, SEED_B, SEED_F, _build_corpus


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    return _build_corpus(tmp_path)


def test_shared_collaborators_finds_a_real_common_neighbor(corpus: Path) -> None:
    # Carol is release_credit on both R1 (Seed A) and R2 (Seed B), which
    # gives her a release_scope edge to each of them -- a real, documented
    # collaborator shared by both artists.
    with CreditGraph.open(corpus) as graph:
        result = compare_artists(graph, CompareArtistsRequest(corpus, SEED_A, SEED_B))

    assert CAROL in result["shared_collaborators"]["artist_ids"]


def test_route_found_between_two_artists_bridged_through_a_third(corpus: Path) -> None:
    # Seed A -> Carol (R1 release_scope edge) -> Dan (R4 co-performance) --
    # a real 2-hop route, no direct edge between Seed A and Dan themselves.
    with CreditGraph.open(corpus) as graph:
        result = compare_artists(graph, CompareArtistsRequest(corpus, SEED_A, DAN))

    assert result["route"]["case"] == "found"
    assert len(result["route"]["hops"]) == 2
    assert result["route"]["hops"][0]["artist_a_id"] == SEED_A
    assert result["route"]["hops"][-1]["artist_b_id"] == DAN


def test_route_no_path_within_bound_for_fully_isolated_artists(corpus: Path) -> None:
    with CreditGraph.open(corpus) as graph:
        result = compare_artists(graph, CompareArtistsRequest(corpus, SEED_A, SEED_F))
    assert result["route"]["case"] == "no_path_within_bound"


def test_hub_dependence_reports_a_real_nonzero_degree_for_a_connected_artist(
    corpus: Path,
) -> None:
    with CreditGraph.open(corpus) as graph:
        result = compare_artists(graph, CompareArtistsRequest(corpus, SEED_A, SEED_B))
    assert result["artist_a"]["hub_dependence"]["degree"] > 0
    assert result["artist_b"]["hub_dependence"]["degree"] > 0


def test_corpus_coverage_is_measured_for_a_real_artist(corpus: Path) -> None:
    with CreditGraph.open(corpus) as graph:
        result = compare_artists(graph, CompareArtistsRequest(corpus, SEED_A, SEED_B))
    assert result["artist_a"]["corpus_coverage"]["case"] == "measured"
    assert result["artist_a"]["corpus_coverage"]["tiers"]["seed_artist_id"] == SEED_A


def test_role_category_counts_reflect_this_artists_own_credits(corpus: Path) -> None:
    with CreditGraph.open(corpus) as graph:
        result = compare_artists(graph, CompareArtistsRequest(corpus, SEED_A, BOB))
    # Bob is only ever credited "Engineer" in the fixture.
    assert result["artist_b"]["role_category_counts"] == {"engineering": 1}


def test_unresolvable_artist_raises_compare_error(corpus: Path) -> None:
    with CreditGraph.open(corpus) as graph:
        with pytest.raises(CompareError):
            compare_artists(graph, CompareArtistsRequest(corpus, SEED_A, 999_999))


def test_comparing_an_artist_to_themselves_raises_compare_error(corpus: Path) -> None:
    with CreditGraph.open(corpus) as graph:
        with pytest.raises(CompareError):
            compare_artists(graph, CompareArtistsRequest(corpus, SEED_A, SEED_A))


def test_era_counts_buckets_by_decade_and_keeps_an_unknown_bucket_for_unresolvable_years() -> None:
    credit_rows = [
        {"release_id": 1},
        {"release_id": 2},
        {"release_id": 3},
        {"release_id": 4},
    ]
    releases: dict[int, dict[str, Any]] = {
        1: {"released": "1975-03-01"},
        2: {"released": "1978"},
        3: {"released": "1990-01-01"},
        4: {"released": None},
    }
    assert _era_counts(credit_rows, releases) == {"1970s": 2, "1990s": 1, "unknown": 1}


def test_era_counts_total_always_equals_the_release_count() -> None:
    credit_rows = [{"release_id": 1}, {"release_id": 1}, {"release_id": 2}]  # dup row, same release
    releases = {1: {"released": "2001"}, 2: {"released": "2005"}}
    counts = _era_counts(credit_rows, releases)
    assert sum(counts.values()) == 2  # 2 distinct releases, not 3 credit rows
