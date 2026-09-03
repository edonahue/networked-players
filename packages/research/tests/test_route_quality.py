"""Synthetic-fixture tests for the Phase 5 route-quality measurement.

Every graph here is hand-built and tiny, so each assertion is checkable by
eye -- the real 36,959-node artifact is measured by the CLI, never by the
test suite (AGENTS.md: keep fixtures synthetic and reproducible).
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

from networked_players_research.route_quality import (
    ALBUM_ANCHOR_SENTINEL,
    ANCHOR_HOP_BUDGET,
    PairMeasurement,
    PublishedGraph,
    bfs_first_route,
    enumerate_routes,
    load_published_graph,
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


# --- load_published_graph: schema-version-aware decode (ADR 0071) ---------


def _payload_from_graph(graph: PublishedGraph, *, schema_version: int) -> dict:
    """A minimal, valid pathfinding-graph-shaped JSON payload carrying
    `graph`'s real content -- v3 shape (edge_role_a/edge_role_b as text) or
    v4 shape (dictionary-encoded), so both can be round-tripped through
    `load_published_graph` and compared."""
    payload: dict = {
        "schema_version": schema_version,
        "node_ids": graph.node_ids,
        "names": graph.names,
        "offsets": graph.offsets,
        "neighbors": graph.neighbors,
        "evidence_release_ids": graph.evidence_release_ids,
        "album_virtual_nodes": [
            {"album_id": album_id, "virtual_artist_id": virtual_id, "main_release_id": 1}
            for album_id, virtual_id in graph.virtual_id_by_album_id.items()
        ],
    }
    if schema_version == 4:
        roles: list[str] = []
        index: dict[str, int] = {}

        def role_id(text: str) -> int:
            if text not in index:
                index[text] = len(roles)
                roles.append(text)
            return index[text]

        payload["roles"] = roles
        payload["edge_role_a"] = [role_id(t) for t in graph.edge_role_a]
        payload["edge_role_b"] = [role_id(t) for t in graph.edge_role_b]
    else:
        payload["edge_role_a"] = graph.edge_role_a
        payload["edge_role_b"] = graph.edge_role_b
    return payload


def test_load_published_graph_v3_matches_the_reference_object(tmp_path: Path) -> None:
    reference = two_album_graph()
    path = tmp_path / "graph.v3.json"
    path.write_text(json.dumps(_payload_from_graph(reference, schema_version=3)))
    assert load_published_graph(path) == reference


def test_load_published_graph_v4_decodes_the_role_dictionary(tmp_path: Path) -> None:
    """The whole point of the decode step: a v4 file's raw edge_role_a/
    edge_role_b are `roles` indices on disk, but `load_published_graph`
    must still produce the exact same PublishedGraph a v3 file with
    identical content would -- proving this isn't just "doesn't crash" but
    a genuine, lossless re-encoding. Without the decode step, `str(index)`
    would silently produce "0"/"1"/... instead of real role text."""
    reference = two_album_graph()
    path = tmp_path / "graph.v4.json"
    path.write_text(json.dumps(_payload_from_graph(reference, schema_version=4)))
    loaded = load_published_graph(path)
    assert loaded == reference
    assert all(isinstance(r, str) for r in loaded.edge_role_a)
    assert all(isinstance(r, str) for r in loaded.edge_role_b)
    # Never numeric-string garbage -- a real role/sentinel string.
    assert ALBUM_ANCHOR_SENTINEL in loaded.edge_role_a


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


def test_a_partial_shortest_layer_still_suppresses_the_hub_signal() -> None:
    """The harder case the first review fix missed: the cap fires AFTER
    some shortest routes are collected. `best_equal_hop_by_degree` is then
    the best of an arbitrary CSR-ordered prefix, so the hub claim must
    still be withheld -- otherwise summarize() folds an unfounded claim
    into the headline count.

    max_expansions=18 is calibrated against this fixture: 14 slots go to
    the reverse-distance precompute (which is charged to the same budget),
    leaving just enough forward walk to find the first of its two shortest
    routes but not the second."""
    graph = two_album_graph()
    partial = enumerate_routes(
        graph,
        graph.index_by_node_id[-1],
        graph.index_by_node_id[-2],
        max_user_hops=4,
        max_expansions=18,
    )
    shortest = min(r.user_hop_count for r in partial.routes)
    assert len([r for r in partial.routes if r.user_hop_count == shortest]) == 1
    assert not partial.shortest_layer_complete

    measurement = measure_pair(graph, "album-a", "album-b", max_user_hops=4, max_expansions=18)
    assert measurement is not None
    assert not measurement.shortest_layer_complete
    assert measurement.equal_hop_improves_hub is False


def test_summary_median_matches_a_true_median_on_an_even_sample() -> None:
    """The ADR quotes this figure, so the reproducible report has to agree
    with it: on an even sample with differing central values the median is
    the average of both, not the upper-middle element."""
    counts = [1, 2, 4, 5]
    measurements = [
        PairMeasurement(
            from_album_id=f"a{i}",
            to_album_id=f"b{i}",
            shortest_user_hops=1,
            equal_hop_route_count=count,
            routes_within_one_extra_hop=count,
            bfs_first=None,
            best_equal_hop_by_degree=None,
            enumeration_expansions=0,
            shortest_layer_expansions=0,
            reverse_expansions=0,
            truncated_at_user_hops=None,
            enumeration_seconds=0.0,
            enumeration_truncated=False,
            truncated_by_route_cap=False,
            shortest_layer_complete=True,
            equal_hop_improves_hub=False,
        )
        for i, count in enumerate(counts)
    ]
    summary = summarize(measurements)
    assert summary["equal_hop_alternatives"]["median"] == statistics.median(counts)
    assert summary["equal_hop_alternatives"]["median"] == 3.0


def test_routes_never_pass_through_another_albums_anchor() -> None:
    """A virtual anchor is an endpoint, never an interior step. Walking
    through one would mean "album A to some other album's anchor to album
    B" -- not a contributor-to-contributor route -- and since
    stripAlbumAnchors only removes the first and last hop, an interior
    anchor would survive into the rendered route as a synthetic
    'contributor'. Measured against the real artifact before this guard: 4
    of 40 sampled pairs had their best equal-hop route routed through one,
    and all 4 inflated the hub-improvement headline."""
    # album-a -- 10 -- [album-c's anchor] -- 20 -- album-b is a 2-hop route
    # through -3 that must never be enumerated; the honest route is the
    # 3-hop one through the real contributor 900.
    graph = build_graph(
        node_ids=[-3, -2, -1, 10, 20, 900],
        edges=[
            (-1, 10, 1001),
            (-2, 20, 2001),
            (-3, 10, 3001),
            (-3, 20, 3002),
            (10, 900, 5001),
            (900, 20, 5002),
        ],
        album_anchors={"album-a": -1, "album-b": -2, "album-c": -3},
    )
    start, goal = graph.index_by_node_id[-1], graph.index_by_node_id[-2]
    result = enumerate_routes(graph, start, goal, max_user_hops=4)
    assert result.routes
    for route in result.routes:
        interior = route.node_indices[1:-1]
        assert all(graph.node_ids[i] > 0 for i in interior), (
            "an album anchor was walked through as an interior step"
        )
    # The only honest route runs through the real contributor.
    assert {route_metrics(graph, r).contributor_node_ids for r in result.routes} == {(10, 900, 20)}


def test_a_capped_pair_is_unknown_reachability_not_routeless() -> None:
    """Truncation before the first route means reachability is unknown --
    bfs_first_route (uncapped) may well have found one. Counting it as
    'no route exists' would overstate what was observed."""
    graph = two_album_graph()
    measurement = measure_pair(graph, "album-a", "album-b", max_user_hops=4, max_expansions=2)
    assert measurement is not None
    assert measurement.shortest_user_hops is None
    assert measurement.reachability_unknown
    # The uncapped baseline did find a route, which is exactly why "no
    # route" would have been the wrong conclusion.
    assert measurement.bfs_first is not None

    summary = summarize([measurement])
    assert summary["pairs_without_a_route"] == 0
    assert summary["pairs_reachability_unknown"] == 1


def test_a_genuinely_disconnected_pair_is_reported_as_routeless() -> None:
    graph = build_graph(
        node_ids=[-2, -1, 10, 20],
        edges=[(-1, 10, 1001), (-2, 20, 2001)],
        album_anchors={"a": -1, "b": -2},
    )
    measurement = measure_pair(graph, "a", "b", max_user_hops=4)
    assert measurement is not None
    assert measurement.shortest_user_hops is None
    assert not measurement.reachability_unknown
    summary = summarize([measurement])
    assert summary["pairs_without_a_route"] == 1
    assert summary["pairs_reachability_unknown"] == 0


def test_the_route_cap_is_never_exceeded_beyond_the_shortest_layer() -> None:
    """The shortest layer is exempt, but a longer route must not be
    appended past the cap: check before appending, not after."""
    graph = two_album_graph()
    start = graph.index_by_node_id[-1]
    goal = graph.index_by_node_id[-2]
    result = enumerate_routes(graph, start, goal, max_user_hops=4, max_routes=1)
    shortest = min(r.user_hop_count for r in result.routes)
    longer = [r for r in result.routes if r.user_hop_count > shortest]
    assert longer == [], "a longer route was appended despite the cap"


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
    assert (
        summary["equal_hop_hub_improvable"]["share_of_pairs_with_a_complete_shortest_layer"] == 1.0
    )
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


def test_incomplete_shortest_layers_are_excluded_from_aggregates() -> None:
    """A partial layer contributes an arbitrary prefix's count to the
    distribution, and -- since its hub claim is correctly withheld -- would
    otherwise sit in the improvement denominator as a false
    non-improvement, biasing a capped run's headline downward."""
    graph = two_album_graph()
    complete = measure_pair(graph, "album-a", "album-b", max_user_hops=4)
    partial = measure_pair(graph, "album-a", "album-b", max_user_hops=4, max_expansions=18)
    assert complete is not None and partial is not None
    assert complete.shortest_layer_complete
    assert not partial.shortest_layer_complete
    assert partial.shortest_user_hops is not None  # it did find a route

    summary = summarize([complete, partial])
    assert summary["pairs_with_a_route"] == 2
    assert summary["pairs_shortest_layer_incomplete"] == 1
    # Aggregates cover only the complete pair.
    assert summary["equal_hop_alternatives"]["measured_over_pairs"] == 1
    assert summary["equal_hop_alternatives"]["max"] == complete.equal_hop_route_count
    assert summary["equal_hop_hub_improvable"]["measured_over_pairs"] == 1
    assert (
        summary["equal_hop_hub_improvable"]["share_of_pairs_with_a_complete_shortest_layer"] == 1.0
    )


def test_shortest_layer_expansions_are_snapshotted_not_the_whole_search() -> None:
    """ADR 0059 states its bound in shortest-layer expansions, so the CLI
    has to report that figure -- `expansions` keeps counting through the
    deeper layers and answers a different question."""
    graph = two_album_graph()
    start = graph.index_by_node_id[-1]
    goal = graph.index_by_node_id[-2]
    result = enumerate_routes(graph, start, goal, max_user_hops=4)
    assert result.shortest_layer_complete
    assert 0 < result.shortest_layer_expansions < result.expansions

    shortest_only = enumerate_routes(graph, start, goal, max_user_hops=1)
    assert result.shortest_layer_expansions == shortest_only.shortest_layer_expansions


def test_the_reverse_precompute_is_counted_and_capped() -> None:
    """The reverse-distance BFS dominates the forward walk it guides -- on
    the committed graph it scans ~125,900 slots against a forward walk of a
    few hundred. Leaving it uncounted made the advertised cap bound about
    0.3% of the real work, so it is charged to the same budget and can stop
    the search on its own."""
    graph = two_album_graph()
    start = graph.index_by_node_id[-1]
    goal = graph.index_by_node_id[-2]

    full = enumerate_routes(graph, start, goal, max_user_hops=4)
    assert full.reverse_expansions > 0
    # Total covers the precompute; the shortest-layer figure does not.
    assert full.expansions > full.reverse_expansions
    # The shortest-layer figure is forward-walk only, so it must be
    # strictly smaller than the total that includes the precompute.
    assert 0 < full.shortest_layer_expansions < full.expansions
    assert full.shortest_layer_expansions <= full.expansions - full.reverse_expansions

    # A budget smaller than the precompute stops the search there, and says so.
    starved = enumerate_routes(
        graph, start, goal, max_user_hops=4, max_expansions=full.reverse_expansions - 1
    )
    assert starved.truncated_by_expansion_cap
    assert starved.routes == []
    assert not starved.shortest_layer_complete


def test_an_exact_budget_permits_exactly_that_many_operations() -> None:
    """A cap of N must allow N slot scans, not N-1: increment-then-compare
    aborted the very operation the budget was meant to permit, so an
    exact-bound run reported itself truncated."""
    graph = two_album_graph()
    start = graph.index_by_node_id[-1]
    goal = graph.index_by_node_id[-2]
    full = enumerate_routes(graph, start, goal, max_user_hops=4)
    assert not full.truncated

    exact = enumerate_routes(graph, start, goal, max_user_hops=4, max_expansions=full.expansions)
    assert not exact.truncated_by_expansion_cap
    assert exact.expansions == full.expansions
    assert len(exact.routes) == len(full.routes)


def test_truncation_depth_is_recorded_so_shallower_counts_stay_exact() -> None:
    """Enumeration is shortest-first, so a cap firing at a DEEPER layer
    means every shallower layer already finished and its counts are exact.
    Without the depth, a deep truncation was misreported as saturating the
    +1 layer."""
    graph = two_album_graph()
    start = graph.index_by_node_id[-1]
    goal = graph.index_by_node_id[-2]

    full = enumerate_routes(graph, start, goal, max_user_hops=4)
    assert full.truncated_at_user_hops is None

    # Cap low enough to stop at a layer beyond the shortest.
    capped = enumerate_routes(graph, start, goal, max_user_hops=4, max_routes=2)
    assert capped.truncated_by_route_cap
    assert capped.truncated_at_user_hops is not None
    shortest = min(r.user_hop_count for r in capped.routes)
    assert capped.truncated_at_user_hops > shortest, (
        "the shortest layer completed, so truncation must be recorded deeper"
    )


def test_plus_one_saturation_counts_only_truncation_at_that_layer() -> None:
    graph = two_album_graph()
    deep = measure_pair(graph, "album-a", "album-b", max_user_hops=4, max_routes=2)
    assert deep is not None
    assert deep.truncated_by_route_cap
    summary = summarize([deep])
    # Truncation happened beyond shortest+1, so the +1 count is exact and
    # must NOT be reported as saturated.
    if deep.truncated_at_user_hops is not None and deep.shortest_user_hops is not None:
        beyond = deep.truncated_at_user_hops > deep.shortest_user_hops + 1
        if beyond:
            assert summary["routes_within_one_extra_hop"]["saturated_within_plus_one_pairs"] == 0
