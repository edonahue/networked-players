"""Tests for the exact, production-equivalent marginal-value evaluator
(Phase 7 Workstream 1B) -- reuses `credit_edges_sql` directly, scoped to a
specific release-id set, so both these tests and a real run measure the
same rules the actual catalog build uses.

Uses the shared `dataset_root` fixture (conftest.py's FIXTURE_RELEASES/
FIXTURE_CREDITS) so the hand-computed expectations below are independently
checkable against the same fixture other graph-core tests already document:

  R1 "First Light" (master 901): Alice(100) <-> Bob(200)               1 edge
  R3 "Third Wave"  (master 903): Cara(300) <-> Dan(400)                1 edge
  R4 "Large Ensemble" (master 904): Alice(100), Eve(500), PlusOne(501),
      PlusTwo(502) all co-perform on the same track -> a 4-clique         6 edges
  R6 "Sixth Sense" (master 906): Dan(400) <-> Eve(500)                 1 edge
"""

from __future__ import annotations

from pathlib import Path

from networked_players_graph_core.marginal_evaluation import (
    edges_by_release,
    edges_for_release_scope,
    greedy_marginal_selection,
)


def test_edges_for_release_scope_is_empty_for_no_releases(dataset_root: Path) -> None:
    assert edges_for_release_scope(dataset_root, frozenset()) == frozenset()


def test_edges_for_release_scope_over_a_single_release(dataset_root: Path) -> None:
    assert edges_for_release_scope(dataset_root, frozenset({1})) == frozenset({(100, 200)})


def test_edges_for_release_scope_forms_the_real_clique_on_an_album_shaped_release(
    dataset_root: Path,
) -> None:
    """Release 4's four co-performers on one track form a real
    credit_edges_sql clique (6 edges among 4 nodes) -- proof this reuses the
    actual rule, not a simplified "one edge per pair of billed artists"
    approximation."""
    edges = edges_for_release_scope(dataset_root, frozenset({4}))
    nodes = {100, 500, 501, 502}
    expected = {(a, b) for a in nodes for b in nodes if a < b}
    assert edges == frozenset(expected)
    assert len(edges) == 6


def test_edges_for_release_scope_is_undirected_and_order_independent(dataset_root: Path) -> None:
    a = edges_for_release_scope(dataset_root, frozenset({1, 3}))
    b = edges_for_release_scope(dataset_root, frozenset({3, 1}))
    assert a == b == frozenset({(100, 200), (300, 400)})


def test_edges_by_release_is_empty_for_no_releases(dataset_root: Path) -> None:
    assert edges_by_release(dataset_root, frozenset()) == {}


def test_edges_by_release_matches_per_release_isolation(dataset_root: Path) -> None:
    per_release = edges_by_release(dataset_root, frozenset({1, 3, 4}))
    assert per_release[1] == frozenset({(100, 200)})
    assert per_release[3] == frozenset({(300, 400)})
    assert len(per_release[4]) == 6


def test_edges_by_release_decomposes_exactly_into_the_combined_scope(dataset_root: Path) -> None:
    """The correctness property the whole performance design depends on:
    the union of each release's OWN isolated edge set must equal the edge
    set of the combined scope, since credit_edges_sql's rules are all
    GROUP BY release_id with no cross-release join."""
    release_ids = frozenset({1, 3, 4, 6})
    per_release = edges_by_release(dataset_root, release_ids)
    union_of_isolated = frozenset.union(*per_release.values())
    combined = edges_for_release_scope(dataset_root, release_ids)
    assert union_of_isolated == combined


def test_greedy_selection_picks_the_true_marginal_leader_not_raw_score(
    dataset_root: Path,
) -> None:
    """Master 904 (release 4) is the correct first pick despite having the
    LOWEST score of the three finalists -- it adds 6 real edges (the clique)
    against baseline {1}, versus 1 edge each for the other two. Raw score
    would have picked wrong; true marginal edge count picks right."""
    finalists = [
        {"master_id": 903, "main_release_id": 3, "artist_id": 300, "score": 100},
        {"master_id": 904, "main_release_id": 4, "artist_id": 100, "score": 1},
        {"master_id": 906, "main_release_id": 6, "artist_id": 400, "score": 50},
    ]
    selected = greedy_marginal_selection(
        dataset_root,
        baseline_release_ids=frozenset({1}),
        baseline_artist_ids=frozenset(),
        finalists=finalists,
        count=2,
    )
    assert [c["master_id"] for c in selected] == [904, 903]
    assert selected[0]["marginal_new_edges"] == 6
    assert selected[0]["marginal_new_contributors"] == 3  # 500, 501, 502 (100 already present)
    assert selected[1]["marginal_new_edges"] == 1
    assert selected[1]["marginal_new_contributors"] == 2  # 300, 400 both new


def test_greedy_selection_second_pick_breaks_an_edge_tie_by_new_contributor_count(
    dataset_root: Path,
) -> None:
    """After picking 904, both remaining finalists (903, 906) add exactly 1
    new edge -- but 903 (Cara<->Dan) introduces 2 brand-new contributors,
    while 906 (Dan<->Eve) introduces only 1 (Eve is already present from the
    904 clique). The tie-break must prefer the genuinely broader addition."""
    finalists = [
        {"master_id": 903, "main_release_id": 3, "artist_id": 300},
        {"master_id": 904, "main_release_id": 4, "artist_id": 100},
        {"master_id": 906, "main_release_id": 6, "artist_id": 400},
    ]
    selected = greedy_marginal_selection(
        dataset_root,
        baseline_release_ids=frozenset({1}),
        baseline_artist_ids=frozenset(),
        finalists=finalists,
        count=3,
    )
    assert [c["master_id"] for c in selected] == [904, 903, 906]


def test_greedy_selection_ties_on_edges_and_nodes_break_by_score_then_master_id(
    dataset_root: Path,
) -> None:
    """903 and 906 both add exactly 1 edge and, against an empty baseline,
    exactly 2 new nodes each -- a full tie down to score."""
    finalists = [
        {"master_id": 906, "main_release_id": 6, "artist_id": 400, "score": 5},
        {"master_id": 903, "main_release_id": 3, "artist_id": 300, "score": 10},
    ]
    selected = greedy_marginal_selection(
        dataset_root,
        baseline_release_ids=frozenset(),
        baseline_artist_ids=frozenset(),
        finalists=finalists,
        count=1,
    )
    assert selected[0]["master_id"] == 903
    assert selected[0]["marginal_new_edges"] == 1
    assert selected[0]["marginal_new_contributors"] == 2


def test_greedy_selection_final_tiebreak_is_master_id_ascending(dataset_root: Path) -> None:
    finalists = [
        {"master_id": 906, "main_release_id": 6, "artist_id": 400, "score": 5},
        {"master_id": 903, "main_release_id": 3, "artist_id": 300, "score": 5},
    ]
    selected = greedy_marginal_selection(
        dataset_root,
        baseline_release_ids=frozenset(),
        baseline_artist_ids=frozenset(),
        finalists=finalists,
        count=1,
    )
    assert selected[0]["master_id"] == 903


def test_greedy_selection_is_deterministic_across_repeated_runs(dataset_root: Path) -> None:
    finalists = [
        {"master_id": 903, "main_release_id": 3, "artist_id": 300, "score": 10},
        {"master_id": 904, "main_release_id": 4, "artist_id": 100, "score": 1},
        {"master_id": 906, "main_release_id": 6, "artist_id": 400, "score": 50},
    ]
    first = greedy_marginal_selection(
        dataset_root,
        baseline_release_ids=frozenset({1}),
        baseline_artist_ids=frozenset(),
        finalists=finalists,
        count=3,
    )
    second = greedy_marginal_selection(
        dataset_root,
        baseline_release_ids=frozenset({1}),
        baseline_artist_ids=frozenset(),
        finalists=list(reversed(finalists)),
        count=3,
    )
    assert [c["master_id"] for c in first] == [c["master_id"] for c in second]


def test_greedy_selection_never_exceeds_the_finalist_count(dataset_root: Path) -> None:
    finalists = [{"master_id": 903, "main_release_id": 3, "artist_id": 300}]
    selected = greedy_marginal_selection(
        dataset_root,
        baseline_release_ids=frozenset({1}),
        baseline_artist_ids=frozenset(),
        finalists=finalists,
        count=5,
    )
    assert len(selected) == 1


def test_greedy_selection_count_zero_selects_nothing(dataset_root: Path) -> None:
    finalists = [{"master_id": 903, "main_release_id": 3, "artist_id": 300}]
    assert (
        greedy_marginal_selection(
            dataset_root,
            baseline_release_ids=frozenset({1}),
            baseline_artist_ids=frozenset(),
            finalists=finalists,
            count=0,
        )
        == []
    )


def test_greedy_selection_preserves_extra_candidate_fields(dataset_root: Path) -> None:
    finalists = [{"master_id": 903, "main_release_id": 3, "artist_id": 300, "artist_name": "Cara"}]
    selected = greedy_marginal_selection(
        dataset_root,
        baseline_release_ids=frozenset({1}),
        baseline_artist_ids=frozenset(),
        finalists=finalists,
        count=1,
    )
    assert selected[0]["artist_name"] == "Cara"


def test_baseline_artist_ids_excludes_a_finalist_upfront_regardless_of_score(
    dataset_root: Path,
) -> None:
    """A finalist whose artist is already in the catalog/Bucket A must never
    be selected, no matter how high its declared score is -- mirrors
    assemble_album_catalog's own editorial-artist exclusion (ADR 0038), so
    this evaluator's output can never promise a slot the real catalog build
    would refuse to keep."""
    finalists = [
        {"master_id": 903, "main_release_id": 3, "artist_id": 300, "score": 100_000},
        {"master_id": 906, "main_release_id": 6, "artist_id": 400, "score": 1},
    ]
    selected = greedy_marginal_selection(
        dataset_root,
        baseline_release_ids=frozenset(),
        baseline_artist_ids=frozenset({300}),
        finalists=finalists,
        count=2,
    )
    assert [c["master_id"] for c in selected] == [906]


def test_at_most_one_selection_per_artist_within_a_single_run(dataset_root: Path) -> None:
    """Two finalists nominally by the same artist (artist_id=300): only the
    higher-value one is selected, and the run does NOT pad the remaining
    slot with the second one -- exactly mirroring assemble_album_catalog's
    added_candidate_ids dedup for the graph-rich bucket, so a real Bucket B
    run can never report two albums by the same artist."""
    finalists = [
        {"master_id": 903, "main_release_id": 3, "artist_id": 300, "score": 100},
        {"master_id": 906, "main_release_id": 6, "artist_id": 300, "score": 200},
    ]
    selected = greedy_marginal_selection(
        dataset_root,
        baseline_release_ids=frozenset(),
        baseline_artist_ids=frozenset(),
        finalists=finalists,
        count=2,
    )
    assert [c["master_id"] for c in selected] == [906]
