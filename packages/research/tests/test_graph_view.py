"""Phase 7 closeout PR D: `build_graph_view`'s bounded one-hop ego-network
view -- the private mirror of `apps/web`'s `networkExplorer.ts` `buildView`.
Reuses `test_compare.py`'s shared synthetic corpus (SEED_A/BOB/CAROL/etc.)
rather than building a new one, since it already has real, edge-eligible
co-credit relationships with real, distinct role texts."""

from __future__ import annotations

from pathlib import Path

import pytest

from networked_players_graph_core.graph import CreditGraph
from networked_players_graph_core.role_taxonomy import RoleCategory
from networked_players_research.compare import CompareError, build_graph_view

from .test_compare import BOB, CAROL, EVE, SEED_A, _build_corpus


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    return _build_corpus(tmp_path)


def test_build_graph_view_returns_real_one_hop_neighbors_with_role_evidence(
    corpus: Path,
) -> None:
    with CreditGraph.open(corpus) as graph:
        view = build_graph_view(graph, SEED_A)

    assert view["center"]["artist_id"] == SEED_A
    assert view["center"]["name"] == "Seed A"
    assert view["center"]["degree"] >= 2
    by_id = {n["artist_id"]: n for n in view["neighbors"]}
    # Seed A (billed on R1) is joined to Bob and Carol via the
    # `release_scope` edge rule (both are release-scope contributors on
    # Seed A's album), each carrying their own real role text.
    assert by_id[BOB]["role_b"] == "Engineer"
    assert by_id[CAROL]["role_b"] == "Violin"
    assert by_id[BOB]["role_a"] == "Vocals"
    assert view["truncated"] is False


def test_build_graph_view_role_filter_is_a_hard_traversal_constraint(corpus: Path) -> None:
    with CreditGraph.open(corpus) as graph:
        strings_only = build_graph_view(
            graph, SEED_A, role_categories=frozenset({RoleCategory.STRINGS})
        )

    ids = {n["artist_id"] for n in strings_only["neighbors"]}
    # Carol (Violin -> strings) must be present; Bob (Engineer ->
    # engineering) must be excluded entirely -- not merely dimmed/flagged,
    # since a filtered traversal must never surface a non-matching edge.
    assert CAROL in ids
    assert BOB not in ids


def test_build_graph_view_truncates_to_max_neighbors_keeping_the_highest_degree(
    corpus: Path,
) -> None:
    with CreditGraph.open(corpus) as graph:
        full = build_graph_view(graph, SEED_A)
        bounded = build_graph_view(graph, SEED_A, max_neighbors=1)

    assert len(full["neighbors"]) >= 2
    assert bounded["truncated"] is True
    assert len(bounded["neighbors"]) == 1
    # Carol has real edges to Seed A, Seed B, and Dan (degree 3) in this
    # fixture; Bob has only the one edge to Seed A (degree 1) -- Carol must
    # be the one kept when only one neighbor fits.
    assert bounded["neighbors"][0]["artist_id"] == CAROL


def test_build_graph_view_reports_no_neighbors_for_a_real_but_isolated_artist(
    corpus: Path,
) -> None:
    # Eve (various-artists release, no release-scope contributor, no
    # track-level co-performer row) has a real credited presence but zero
    # graph edges -- distinct from an unknown artist_id entirely.
    with CreditGraph.open(corpus) as graph:
        view = build_graph_view(graph, EVE)

    assert view["center"]["artist_id"] == EVE
    assert view["center"]["degree"] == 0
    assert view["neighbors"] == []
    assert view["truncated"] is False


def test_build_graph_view_raises_compare_error_for_an_unknown_artist(corpus: Path) -> None:
    with CreditGraph.open(corpus) as graph, pytest.raises(CompareError):
        build_graph_view(graph, 999999)
