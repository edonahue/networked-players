"""Synthetic-fixture tests for the Phase 5 route-quality measurement.

Every graph here is hand-built and tiny, so each assertion is checkable by
eye -- the real 36,959-node artifact is measured by the CLI, never by the
test suite (AGENTS.md: keep fixtures synthetic and reproducible).
"""

from __future__ import annotations

from networked_players_research.route_quality import (
    ALBUM_ANCHOR_SENTINEL,
    ANCHOR_HOP_BUDGET,
    PublishedGraph,
    bfs_first_route,
    enumerate_routes,
    measure_pair,
    route_metrics,
    stratified_album_pairs,
    summarize,
)


def build_graph(
    node_ids: list[int],
    edges: list[tuple[int, int, int]],
    *,
    names: dict[int, str] | None = None,
    roles: dict[tuple[int, int], tuple[str, str]] | None = None,
    album_anchors: dict[str, int] | None = None,
) -> PublishedGraph:
    """Build a valid CSR from an undirected edge list, mirroring the real
    builder's layout: node_ids sorted ascending (negatives, i.e. album
    anchors, first) and each node's neighbour slots sorted by node index --
    the layout that makes the production tie-break 'lowest artist id wins'."""
    node_ids = sorted(node_ids)
    index_of = {node_id: i for i, node_id in enumerate(node_ids)}
    roles = roles or {}

    adjacency: dict[int, list[tuple[int, int]]] = {i: [] for i in range(len(node_ids))}
    for a_id, b_id, release_id in edges:
        a, b = index_of[a_id], index_of[b_id]
        adjacency[a].append((b, release_id))
        adjacency[b].append((a, release_id))

    offsets = [0]
    neighbors: list[int] = []
    evidence_release_ids: list[int] = []
    edge_role_a: list[str] = []
    edge_role_b: list[str] = []
    for i in range(len(node_ids)):
        for neighbor, release_id in sorted(adjacency[i], key=lambda p: p[0]):
            neighbors.append(neighbor)
            evidence_release_ids.append(release_id)
            pair = (node_ids[i], node_ids[neighbor])
            role_a, role_b = roles.get(pair, ("Credited artist", "Credited artist"))
            # Anchor edges carry the sentinel on the virtual side only.
            if node_ids[i] < 0:
                role_a = ALBUM_ANCHOR_SENTINEL
            if node_ids[neighbor] < 0:
                role_b = ALBUM_ANCHOR_SENTINEL
            edge_role_a.append(role_a)
            edge_role_b.append(role_b)
        offsets.append(len(neighbors))

    return PublishedGraph(
        node_ids=node_ids,
        names=[(names or {}).get(n, f"Artist {n}") for n in node_ids],
        offsets=offsets,
        neighbors=neighbors,
        evidence_release_ids=evidence_release_ids,
        edge_role_a=edge_role_a,
        edge_role_b=edge_role_b,
        index_by_node_id=index_of,
        virtual_id_by_album_id=album_anchors or {},
    )


def two_album_graph() -> PublishedGraph:
    """Album A (anchor -1) and album B (anchor -2) with DISJOINT
    contributor sets, joined by two competing one-hop routes:

        A --10-- 20 --B     hub route,  ids 10/20, degree 3 each
        A --500-- 600 --B   leaf route, ids 500/600, degree 2 each

    Mirrors the real topology (a user-visible hop is a real edge BETWEEN
    two different contributors; a *shared* contributor would instead be a
    zero-hop route, since both anchor edges strip). The hub route holds the
    lower artist ids, so production's ascending-id tie-break picks the
    hub -- precisely the bias this measurement exists to quantify."""
    return build_graph(
        node_ids=[-2, -1, 10, 20, 500, 600, 900],
        edges=[
            (-1, 10, 1001),  # album A -> hub side
            (-1, 500, 1002),  # album A -> leaf side
            (-2, 20, 2001),  # album B -> hub side
            (-2, 600, 2002),  # album B -> leaf side
            (10, 20, 5001),  # the hub one-hop route
            (500, 600, 5002),  # the leaf one-hop route
            (10, 900, 3001),  # padding, raises hub degree above the leaves
            (20, 900, 3002),
        ],
        album_anchors={"album-a": -1, "album-b": -2},
    )


def test_enumerate_finds_every_route_in_a_tiny_graph() -> None:
    graph = two_album_graph()
    start = graph.index_by_node_id[-1]
    goal = graph.index_by_node_id[-2]
    result = enumerate_routes(graph, start, goal, max_user_hops=4)
    assert not result.truncated
    one_hop = [r for r in result.routes if r.user_hop_count == 1]
    assert len(one_hop) == 2
    contributors = {route_metrics(graph, r).contributor_node_ids for r in one_hop}
    assert contributors == {(10, 20), (500, 600)}


def test_bfs_first_reproduces_the_production_lowest_artist_id_tie_break() -> None:
    """`findPath` claims each node at discovery and never revises, walking
    neighbours in ascending-node-index (= ascending artist id) order. With
    two equally short routes it must take the lower-id contributor."""
    graph = two_album_graph()
    start = graph.index_by_node_id[-1]
    goal = graph.index_by_node_id[-2]
    route = bfs_first_route(graph, start, goal, max_user_hops=4)
    assert route is not None
    metrics = route_metrics(graph, route)
    assert metrics.user_hop_count == 1
    # The hub route wins purely because 10 < 500, not because it is better.
    assert metrics.contributor_node_ids == (10, 20)


def test_measurement_reports_the_lower_hub_alternative() -> None:
    graph = two_album_graph()
    measurement = measure_pair(graph, "album-a", "album-b", max_user_hops=4)
    assert measurement is not None
    assert measurement.shortest_user_hops == 1
    assert measurement.equal_hop_route_count == 2
    assert measurement.bfs_first is not None
    assert measurement.bfs_first.contributor_node_ids == (10, 20)
    assert measurement.best_equal_hop_by_degree is not None
    assert measurement.best_equal_hop_by_degree.contributor_node_ids == (500, 600)
    assert measurement.equal_hop_improves_hub is True


def test_deepening_collects_shortest_routes_before_a_cap_can_drop_them() -> None:
    """Regression for a real defect found against the live artifact: a
    deep-first walk filled the route cap with long branches and then
    reported a 'shortest' of 2 for a pair that has a 1-hop route.
    Truncation must only ever drop routes LONGER than ones already held."""
    graph = two_album_graph()
    start = graph.index_by_node_id[-1]
    goal = graph.index_by_node_id[-2]
    capped = enumerate_routes(graph, start, goal, max_user_hops=4, max_routes=1)
    assert capped.truncated_by_route_cap
    uncapped = enumerate_routes(graph, start, goal, max_user_hops=4)

    # The invariant: a cap may drop LONGER routes, never shorter ones. The
    # capped run must still report the true shortest length and hold every
    # route at that length (the shortest layer is exempt from the cap --
    # see test_shortest_layer_completes_even_when_the_route_cap_is_smaller).
    shortest_capped = min(r.user_hop_count for r in capped.routes)
    shortest_uncapped = min(r.user_hop_count for r in uncapped.routes)
    assert shortest_capped == shortest_uncapped
    assert len([r for r in capped.routes if r.user_hop_count == shortest_capped]) == len(
        [r for r in uncapped.routes if r.user_hop_count == shortest_uncapped]
    )


def test_expansion_cap_is_enforced_and_reported() -> None:
    graph = two_album_graph()
    start = graph.index_by_node_id[-1]
    goal = graph.index_by_node_id[-2]
    result = enumerate_routes(graph, start, goal, max_user_hops=4, max_expansions=3)
    assert result.truncated_by_expansion_cap
    assert result.truncated
    assert result.expansions <= 3


def test_hop_budget_excludes_the_two_anchor_steps() -> None:
    graph = two_album_graph()
    start = graph.index_by_node_id[-1]
    goal = graph.index_by_node_id[-2]
    result = enumerate_routes(graph, start, goal, max_user_hops=1)
    assert result.routes
    assert all(r.user_hop_count <= 1 for r in result.routes)
    assert all(len(r.slots) <= 1 + ANCHOR_HOP_BUDGET for r in result.routes)


def test_route_metrics_measures_degree_and_roles_over_visible_hops_only() -> None:
    graph = build_graph(
        node_ids=[-2, -1, 10, 20],
        edges=[(-1, 10, 1001), (10, 20, 5005), (-2, 20, 2001)],
        names={10: "Alice", 20: "Bob"},
        roles={(10, 20): ("Drums", "Producer"), (20, 10): ("Producer", "Drums")},
        album_anchors={"a": -1, "b": -2},
    )
    start, goal = graph.index_by_node_id[-1], graph.index_by_node_id[-2]
    route = bfs_first_route(graph, start, goal, max_user_hops=4)
    assert route is not None
    metrics = route_metrics(graph, route)
    assert metrics.user_hop_count == 1
    assert metrics.contributor_node_ids == (10, 20)
    assert metrics.contributor_names == ("Alice", "Bob")
    # Only the real hop's release, never the two anchor releases.
    assert metrics.evidence_release_ids == (5005,)
    assert "production" in metrics.role_categories
    assert metrics.performer_hop_share == 1.0  # Drums is a performing role


def test_unknown_album_measures_as_none_not_an_error() -> None:
    graph = two_album_graph()
    assert measure_pair(graph, "album-a", "album-missing") is None
    assert measure_pair(graph, "album-missing", "album-b") is None


def test_disconnected_pair_reports_no_route_without_raising() -> None:
    graph = build_graph(
        node_ids=[-2, -1, 10, 20],
        edges=[(-1, 10, 1001), (-2, 20, 2001)],
        album_anchors={"a": -1, "b": -2},
    )
    measurement = measure_pair(graph, "a", "b", max_user_hops=4)
    assert measurement is not None
    assert measurement.shortest_user_hops is None
    assert measurement.equal_hop_route_count == 0
    assert measurement.bfs_first is None


def test_stratified_pairs_are_deterministic_and_span_the_degree_range() -> None:
    graph = two_album_graph()
    first = stratified_album_pairs(graph, ["album-a", "album-b"], limit=5)
    second = stratified_album_pairs(graph, ["album-a", "album-b"], limit=5)
    assert first == second
    assert first == [("album-a", "album-b")] or first == [("album-b", "album-a")]


def test_stratified_pairs_ignore_albums_outside_the_graph() -> None:
    graph = two_album_graph()
    pairs = stratified_album_pairs(graph, ["album-a", "album-b", "nope"], limit=5)
    flattened = {album_id for pair in pairs for album_id in pair}
    assert "nope" not in flattened


def test_summarize_reports_the_hub_improvable_share() -> None:
    graph = two_album_graph()
    measurement = measure_pair(graph, "album-a", "album-b", max_user_hops=4)
    assert measurement is not None
    summary = summarize([measurement])
    assert summary["pairs_measured"] == 1
    assert summary["pairs_with_a_route"] == 1
    assert summary["equal_hop_hub_improvable"]["count"] == 1
    assert summary["equal_hop_hub_improvable"]["share_of_pairs_with_a_route"] == 1.0
    assert summary["shortest_hop_histogram"] == {"1": 1}


def test_summarize_handles_an_empty_measurement_set() -> None:
    assert summarize([])["pairs_measured"] == 0


# --- review follow-ups (PR #112) ---------------------------------------


def test_shortest_layer_completes_even_when_the_route_cap_is_smaller() -> None:
    """The route cap must never cut the shortest layer mid-depth: every
    equal-hop statistic is computed over that layer, and a partial layer is
    an arbitrary CSR-ordered prefix, not a sample. With max_routes=1 and
    two equal-hop routes, BOTH must still be collected."""
    graph = two_album_graph()
    start = graph.index_by_node_id[-1]
    goal = graph.index_by_node_id[-2]
    result = enumerate_routes(graph, start, goal, max_user_hops=4, max_routes=1)
    shortest = min(r.user_hop_count for r in result.routes)
    at_shortest = [r for r in result.routes if r.user_hop_count == shortest]
    assert len(at_shortest) == 2
    assert result.shortest_layer_complete


def test_equal_hop_statistics_are_computed_over_a_complete_layer() -> None:
    graph = two_album_graph()
    measurement = measure_pair(graph, "album-a", "album-b", max_user_hops=4, max_routes=1)
    assert measurement is not None
    assert measurement.shortest_layer_complete
    assert measurement.equal_hop_route_count == 2
    # The better alternative is still found despite the tiny route cap.
    assert measurement.equal_hop_improves_hub is True


def test_an_incomplete_shortest_layer_suppresses_the_hub_signal() -> None:
    """If the expansion cap fires inside the shortest layer, the layer is
    reported incomplete and the derived hub claim is withheld rather than
    asserted from a prefix."""
    graph = two_album_graph()
    measurement = measure_pair(graph, "album-a", "album-b", max_user_hops=4, max_expansions=2)
    assert measurement is not None
    assert not measurement.shortest_layer_complete
    assert measurement.equal_hop_improves_hub is False


def test_performer_share_counts_only_real_performance_categories() -> None:
    """production/engineering/composition etc. are real credits but not
    performances -- a hop credited solely to them must not count."""
    graph = build_graph(
        node_ids=[-2, -1, 10, 20],
        edges=[(-1, 10, 1001), (10, 20, 5005), (-2, 20, 2001)],
        roles={
            (10, 20): ("Producer", "Engineer"),
            (20, 10): ("Engineer", "Producer"),
        },
        album_anchors={"a": -1, "b": -2},
    )
    start, goal = graph.index_by_node_id[-1], graph.index_by_node_id[-2]
    route = bfs_first_route(graph, start, goal, max_user_hops=4)
    assert route is not None
    metrics = route_metrics(graph, route)
    assert metrics.performer_hop_share == 0.0
    assert "production" in metrics.role_categories


def test_stratified_pairs_span_every_degree_stratum_combination() -> None:
    """Complementary-rank pairing (i with n-1-i) only ever yields
    sparse/dense; the sample must also contain sparse/sparse and
    dense/dense or the statistics are biased toward one topology."""
    graph = build_graph(
        node_ids=[-9, -8, -7, -6, -5, -4, -3, -2, -1, 100],
        edges=[(-i, 100, 1000 + i) for i in range(1, 10)],
        album_anchors={f"album-{i}": -i for i in range(1, 10)},
    )
    album_ids = [f"album-{i}" for i in range(1, 10)]
    pairs = stratified_album_pairs(graph, album_ids, limit=6)
    assert pairs == stratified_album_pairs(graph, album_ids, limit=6)

    ranked = sorted(
        album_ids,
        key=lambda a: (
            graph.degree(graph.index_by_node_id[graph.virtual_id_by_album_id[a]]),
            a,
        ),
    )
    stratum_of = {album_id: min(2, (3 * i) // len(ranked)) for i, album_id in enumerate(ranked)}
    combinations = {tuple(sorted((stratum_of[left], stratum_of[right]))) for left, right in pairs}
    # Not merely the complementary-rank diagonal.
    assert len(combinations) >= 3
    assert any(a == b for a, b in combinations), "no same-stratum pair sampled"
