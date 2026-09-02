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

from .test_compare import BOB, CAROL, DEB, EVE, SEED_A, _build_corpus


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
    # Seed A (billed on R1) is joined to Deb and Carol via the
    # `release_scope` edge rule (both are release-scope contributors whose
    # role text documents a real performance -- ADR 0068), each carrying
    # their own real role text. Bob's release-scope "Engineer" credit
    # documents no performance, so he is never a neighbor at all.
    assert by_id[DEB]["role_b"] == "Drums"
    assert by_id[CAROL]["role_b"] == "Violin"
    assert by_id[DEB]["role_a"] == "Vocals"
    assert BOB not in by_id
    assert view["truncated"] is False


def test_build_graph_view_role_filter_is_a_hard_traversal_constraint(corpus: Path) -> None:
    with CreditGraph.open(corpus) as graph:
        strings_only = build_graph_view(
            graph, SEED_A, role_categories=frozenset({RoleCategory.STRINGS})
        )

    ids = {n["artist_id"] for n in strings_only["neighbors"]}
    # Carol (Violin -> strings) must be present; Deb (Drums ->
    # percussion_keys, a real edge just not a STRINGS one) must be excluded
    # entirely -- not merely dimmed/flagged, since a filtered traversal must
    # never surface a non-matching edge. Bob was never a neighbor to begin
    # with (Engineer documents no performance, ADR 0068).
    assert CAROL in ids
    assert DEB not in ids
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
    # fixture; Deb has only the one edge to Seed A (degree 1) -- Carol must
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


def test_graph_view_traversal_breadth_follows_the_graphs_own_performer_gate(
    corpus: Path,
) -> None:
    """ADR 0068 / PR 6: `compare.py` inherits its traversal breadth from the
    `CreditGraph` it is handed rather than re-implementing the gate, so the
    same `build_graph_view` call answers differently depending on how the
    graph was opened.

    Bob is credited on release 1 at `release_credit` scope with role text
    "Engineer" -- an extra credit that is edge-eligible under ADR 0035's
    denylist but fails `is_performer_role`. He is therefore invisible to
    the default (public-matching) performer graph, and visible in the
    broader private research view. Carol ("Violin", also `release_credit`)
    is the control: a real performer extra-credit, present in both."""
    with CreditGraph.open(corpus) as graph:
        public_view = build_graph_view(graph, SEED_A)
    with CreditGraph.open(corpus, performer_only=False) as graph:
        research_view = build_graph_view(graph, SEED_A)

    public_ids = {n["artist_id"] for n in public_view["neighbors"]}
    research_ids = {n["artist_id"] for n in research_view["neighbors"]}

    # The public default matches the site: an engineering-only credit
    # cannot reach the graph at all.
    assert BOB not in public_ids
    # The broader research view retains it, clearly as the wider relation.
    assert BOB in research_ids
    # Same corpus, same center: the performer graph is a strict subset.
    assert public_ids < research_ids
    # A real performer extra-credit is unaffected by the toggle.
    assert CAROL in public_ids and CAROL in research_ids
