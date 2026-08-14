"""Route-quality measurement over the PUBLISHED pathfinding graph.

Phase 5 measures before it redesigns. Connect Two Records currently shows
whichever route BFS touches first, and `findPath`'s tie-break is an
accident of data layout, not a choice: the CSR neighbour list is sorted by
node index, node index is ascending `artist_id`, and `visited` is set at
*discovery*, so the lowest-numbered Discogs artist permanently claims each
node. This module quantifies what that costs across the real catalog,
which is what lets ADR 0059 pick a hop allowance and a candidate bound
from evidence instead of taste.

Deliberately dependency-free of `graph-core`'s builder and of DuckDB: it
reads only the published artifacts (`pathfinding/graph.v2.json`,
`evidence/release-registry.v1.json`, `catalog/albums.v1.json`), so any
checkout can reproduce a measurement without the private one-hop corpus.
The one graph-core import is `role_taxonomy.classify_role`, reused rather
than reimplemented so role composition here means exactly what it means in
the product's own role filters.

Enumeration is bounded on BOTH axes and reports when a bound was hit --
a truncated measurement that silently looks complete would be worse than
no measurement. The bounds exist because this graph is brutally
heavy-tailed: 71% of its 36,819 real nodes are leaves while 42 nodes carry
500+ edges, so unbounded simple-path enumeration through a hub does not
terminate in useful time.
"""

from __future__ import annotations

import json
import time
from collections import deque
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from networked_players_graph_core.role_taxonomy import classify_role

ALBUM_ANCHOR_SENTINEL = "__np_album_anchor__"

#: The four categories in `RoleCategory` that mean somebody actually
#: performed. The other seven (production, engineering, arrangement,
#: composition, rework, packaging_business, unknown) are real credits but
#: not performances, and must not be counted as such.
PERFORMANCE_CATEGORIES = frozenset({"vocals", "strings", "percussion_keys", "brass_woodwind"})

#: Anchor edges (album -> first contributor, last contributor -> album) are
#: not user-visible hops but do consume BFS depth, matching
#: `pathfindingGraph.ts`'s own ALBUM_ANCHOR_HOP_BUDGET.
ANCHOR_HOP_BUDGET = 2


@dataclass(frozen=True)
class PublishedGraph:
    """The published CSR pathfinding graph, indexed for traversal."""

    node_ids: list[int]
    names: list[str]
    offsets: list[int]
    neighbors: list[int]
    evidence_release_ids: list[int]
    edge_role_a: list[str]
    edge_role_b: list[str]
    index_by_node_id: dict[int, int]
    virtual_id_by_album_id: dict[str, int]

    @property
    def node_count(self) -> int:
        return len(self.node_ids)

    def degree(self, index: int) -> int:
        """Edge count for a node -- the hub signal, available for 100% of
        nodes straight from the CSR. (The contributor index that the
        removed `scorePath` relied on covered 1.46% of them.)"""
        return self.offsets[index + 1] - self.offsets[index]

    def slots(self, index: int) -> range:
        return range(self.offsets[index], self.offsets[index + 1])


def load_published_graph(path: Path) -> PublishedGraph:
    payload = json.loads(Path(path).read_text())
    node_ids = [int(n) for n in payload["node_ids"]]
    return PublishedGraph(
        node_ids=node_ids,
        names=[str(n) for n in payload["names"]],
        offsets=[int(o) for o in payload["offsets"]],
        neighbors=[int(n) for n in payload["neighbors"]],
        evidence_release_ids=[int(r) for r in payload["evidence_release_ids"]],
        edge_role_a=[str(r) for r in payload["edge_role_a"]],
        edge_role_b=[str(r) for r in payload["edge_role_b"]],
        index_by_node_id={node_id: i for i, node_id in enumerate(node_ids)},
        virtual_id_by_album_id={
            str(entry["album_id"]): int(entry["virtual_artist_id"])
            for entry in payload.get("album_virtual_nodes", [])
        },
    )


@dataclass(frozen=True)
class RouteCandidate:
    """One enumerated route, still including its two anchor steps."""

    node_indices: tuple[int, ...]
    slots: tuple[int, ...]

    @property
    def user_hop_count(self) -> int:
        """Hops a player actually sees, i.e. excluding the two anchors."""
        return max(0, len(self.slots) - ANCHOR_HOP_BUDGET)


@dataclass
class EnumerationResult:
    routes: list[RouteCandidate] = field(default_factory=list)
    expansions: int = 0
    truncated_by_route_cap: bool = False
    truncated_by_expansion_cap: bool = False
    elapsed_seconds: float = 0.0
    #: True only when every route at the shortest reachable depth was
    #: collected. Every equal-hop statistic derived downstream is
    #: meaningless without this, so it is reported rather than assumed --
    #: a partially-enumerated shortest layer is an arbitrary CSR-ordered
    #: prefix, not a sample.
    shortest_layer_complete: bool = False

    @property
    def truncated(self) -> bool:
        return self.truncated_by_route_cap or self.truncated_by_expansion_cap


def _reverse_distances(graph: PublishedGraph, goal_index: int, max_depth: int) -> dict[int, int]:
    """Hops from every reachable node to `goal_index`, capped at
    `max_depth`. The graph is undirected (every edge is stored in both
    directions), so a plain BFS from the goal gives the admissible
    remaining-budget bound that keeps enumeration tractable."""
    distances = {goal_index: 0}
    frontier = deque([goal_index])
    while frontier:
        node = frontier.popleft()
        depth = distances[node]
        if depth >= max_depth:
            continue
        for slot in graph.slots(node):
            neighbor = graph.neighbors[slot]
            if neighbor not in distances:
                distances[neighbor] = depth + 1
                frontier.append(neighbor)
    return distances


def enumerate_routes(
    graph: PublishedGraph,
    start_index: int,
    goal_index: int,
    *,
    max_user_hops: int,
    max_routes: int = 200,
    max_expansions: int = 200_000,
    edge_filter: Any = None,
) -> EnumerationResult:
    """Every simple route from `start_index` to `goal_index` within the hop
    budget, bounded on route count and expansion count.

    Distance-guided ITERATIVE DEEPENING, not plain DFS. Two mechanisms:

    * A reverse BFS from the goal gives each node its minimum remaining
      hops, so any branch that cannot reach the goal inside the remaining
      budget is pruned before it is walked. Without that guide a single
      degree-1696 hub makes enumeration intractable.
    * Routes are collected shortest-length-first, one exact depth at a
      time. A plain deep-first walk would fill the route cap with whatever
      long branch it happened to descend into and then report a "shortest"
      that isn't -- measured for real against Discovery -> The Joshua Tree,
      which reported 2 hops while a 1-hop route existed. Deepening makes
      truncation only ever drop routes LONGER than ones already collected,
      which is the only honest way to cap this.

    Unlike `findPath`, nothing is claimed irreversibly -- this returns the
    bounded candidate set rather than the first route to touch the goal,
    which is the whole point of the measurement.
    """
    result = EnumerationResult()
    started = time.perf_counter()
    max_depth = max_user_hops + ANCHOR_HOP_BUDGET
    distances = _reverse_distances(graph, goal_index, max_depth)
    shortest_possible = distances.get(start_index)
    if shortest_possible is None:
        result.elapsed_seconds = time.perf_counter() - started
        return result

    path_nodes = [start_index]
    path_slots: list[int] = []
    on_path = {start_index}

    def walk(node: int, depth: int, target_depth: int, *, enforce_cap: bool) -> bool:
        """Collect routes of EXACTLY `target_depth`. Returns False to
        signal an enumeration bound was hit."""
        if node == goal_index:
            if depth == target_depth:
                result.routes.append(RouteCandidate(tuple(path_nodes), tuple(path_slots)))
                return (not enforce_cap) or len(result.routes) < max_routes
            return True

        remaining = target_depth - depth
        if remaining <= 0:
            return True
        for slot in graph.slots(node):
            neighbor = graph.neighbors[slot]
            if neighbor in on_path:
                continue
            reachable = distances.get(neighbor)
            if reachable is None or reachable > remaining - 1:
                continue
            if edge_filter is not None and not edge_filter(
                graph.edge_role_a[slot], graph.edge_role_b[slot]
            ):
                continue

            result.expansions += 1
            if result.expansions >= max_expansions:
                result.truncated_by_expansion_cap = True
                return False

            on_path.add(neighbor)
            path_nodes.append(neighbor)
            path_slots.append(slot)
            keep_going = walk(neighbor, depth + 1, target_depth, enforce_cap=enforce_cap)
            path_nodes.pop()
            path_slots.pop()
            on_path.discard(neighbor)
            if not keep_going:
                return False
        return True

    for target_depth in range(shortest_possible, max_depth + 1):
        # The shortest layer is never cut off mid-depth. Every equal-hop
        # statistic downstream (candidate count, best-by-degree, the
        # hub-improvement signal) is computed over that layer, and a
        # partial layer is an arbitrary CSR-ordered prefix rather than a
        # sample -- it would silently understate the count and could miss
        # the best route entirely. Measured worst case is 223 routes at
        # 639 expansions, so completing it is cheap; the expansion cap
        # still bounds a pathological graph, and when IT fires the layer
        # is honestly reported as incomplete.
        is_shortest_layer = target_depth == shortest_possible
        completed = walk(start_index, 0, target_depth, enforce_cap=not is_shortest_layer)
        if is_shortest_layer:
            # Only the expansion cap can cut the shortest layer short now.
            result.shortest_layer_complete = completed
        if not completed:
            if not result.truncated_by_expansion_cap:
                result.truncated_by_route_cap = True
            break
    result.elapsed_seconds = time.perf_counter() - started
    return result


@dataclass(frozen=True)
class RouteMetrics:
    """Facts about one route. Deliberately facts, not a score -- the
    scoring policy is ADR 0059's decision, derived FROM these."""

    user_hop_count: int
    contributor_node_ids: tuple[int, ...]
    contributor_names: tuple[str, ...]
    evidence_release_ids: tuple[int, ...]
    max_contributor_degree: int
    mean_contributor_degree: float
    role_categories: tuple[str, ...]
    performer_hop_share: float


def route_metrics(graph: PublishedGraph, route: RouteCandidate) -> RouteMetrics:
    """Per-route facts, measured over the user-visible portion only."""
    inner = route.node_indices[1:-1] if len(route.node_indices) >= 2 else ()
    user_slots = route.slots[1:-1] if len(route.slots) > ANCHOR_HOP_BUDGET else ()
    degrees = [graph.degree(i) for i in inner]
    categories: list[str] = []
    performer_hops = 0
    for slot in user_slots:
        hop_categories = {
            category.value
            for role_text in (graph.edge_role_a[slot], graph.edge_role_b[slot])
            for category in classify_role(role_text)
        }
        categories.extend(sorted(hop_categories))
        if hop_categories & PERFORMANCE_CATEGORIES:
            performer_hops += 1
    return RouteMetrics(
        user_hop_count=route.user_hop_count,
        contributor_node_ids=tuple(graph.node_ids[i] for i in inner),
        contributor_names=tuple(graph.names[i] for i in inner),
        evidence_release_ids=tuple(graph.evidence_release_ids[slot] for slot in user_slots),
        max_contributor_degree=max(degrees, default=0),
        mean_contributor_degree=(sum(degrees) / len(degrees)) if degrees else 0.0,
        role_categories=tuple(sorted(set(categories))),
        performer_hop_share=(performer_hops / len(user_slots)) if user_slots else 0.0,
    )


def bfs_first_route(
    graph: PublishedGraph,
    start_index: int,
    goal_index: int,
    *,
    max_user_hops: int,
) -> RouteCandidate | None:
    """The route production shows today: a faithful port of
    `pathfindingGraph.ts::findPath`, including `visited`-at-discovery and
    the return-on-first-goal-touch. Kept as the measurement's baseline so
    every comparison is against what players really see, not an idealized
    shortest path."""
    if start_index == goal_index:
        return RouteCandidate((start_index,), ())
    parent_of: dict[int, tuple[int, int]] = {}
    visited = {start_index}
    frontier = [start_index]
    max_depth = max_user_hops + ANCHOR_HOP_BUDGET

    for _ in range(max_depth):
        nxt: list[int] = []
        for node in frontier:
            for slot in graph.slots(node):
                neighbor = graph.neighbors[slot]
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                parent_of[neighbor] = (node, slot)
                if neighbor == goal_index:
                    nodes = [goal_index]
                    slots: list[int] = []
                    cursor = goal_index
                    while cursor != start_index:
                        parent, used = parent_of[cursor]
                        slots.append(used)
                        nodes.append(parent)
                        cursor = parent
                    return RouteCandidate(tuple(reversed(nodes)), tuple(reversed(slots)))
                nxt.append(neighbor)
        frontier = nxt
        if not frontier:
            break
    return None


@dataclass(frozen=True)
class PairMeasurement:
    from_album_id: str
    to_album_id: str
    shortest_user_hops: int | None
    equal_hop_route_count: int
    routes_within_one_extra_hop: int
    bfs_first: RouteMetrics | None
    best_equal_hop_by_degree: RouteMetrics | None
    enumeration_expansions: int
    enumeration_seconds: float
    enumeration_truncated: bool
    #: Was every route at the shortest depth collected? Every equal-hop
    #: figure below is only meaningful when this is True.
    shortest_layer_complete: bool
    #: Did an equal-hop alternative strictly reduce the worst hub on the
    #: route? This is the headline disagreement signal -- it says the
    #: current first-found answer was avoidably hub-heavy. Only ever set
    #: when the shortest layer was fully enumerated.
    equal_hop_improves_hub: bool


def measure_pair(
    graph: PublishedGraph,
    from_album_id: str,
    to_album_id: str,
    *,
    max_user_hops: int = 4,
    max_routes: int = 200,
    max_expansions: int = 200_000,
) -> PairMeasurement | None:
    """Measure one real album pair end to end. Returns None when either
    endpoint is outside the graph's scope (not a failure -- a fact about
    the catalog, recorded by the caller)."""
    from_virtual = graph.virtual_id_by_album_id.get(from_album_id)
    to_virtual = graph.virtual_id_by_album_id.get(to_album_id)
    if from_virtual is None or to_virtual is None:
        return None
    start = graph.index_by_node_id.get(from_virtual)
    goal = graph.index_by_node_id.get(to_virtual)
    if start is None or goal is None:
        return None

    enumeration = enumerate_routes(
        graph,
        start,
        goal,
        max_user_hops=max_user_hops,
        max_routes=max_routes,
        max_expansions=max_expansions,
    )
    baseline = bfs_first_route(graph, start, goal, max_user_hops=max_user_hops)
    baseline_metrics = route_metrics(graph, baseline) if baseline else None

    if not enumeration.routes:
        return PairMeasurement(
            from_album_id=from_album_id,
            to_album_id=to_album_id,
            shortest_user_hops=None,
            equal_hop_route_count=0,
            routes_within_one_extra_hop=0,
            bfs_first=baseline_metrics,
            best_equal_hop_by_degree=None,
            enumeration_expansions=enumeration.expansions,
            enumeration_seconds=enumeration.elapsed_seconds,
            enumeration_truncated=enumeration.truncated,
            shortest_layer_complete=enumeration.shortest_layer_complete,
            equal_hop_improves_hub=False,
        )

    all_metrics = [route_metrics(graph, route) for route in enumeration.routes]
    shortest = min(m.user_hop_count for m in all_metrics)
    equal_hop = [m for m in all_metrics if m.user_hop_count == shortest]
    within_one = [m for m in all_metrics if m.user_hop_count <= shortest + 1]
    best_by_degree = min(
        equal_hop,
        key=lambda m: (m.max_contributor_degree, m.contributor_node_ids),
    )
    improves = bool(
        baseline_metrics
        and baseline_metrics.user_hop_count == shortest
        and best_by_degree.max_contributor_degree < baseline_metrics.max_contributor_degree
    )
    return PairMeasurement(
        from_album_id=from_album_id,
        to_album_id=to_album_id,
        shortest_user_hops=shortest,
        equal_hop_route_count=len(equal_hop),
        routes_within_one_extra_hop=len(within_one),
        bfs_first=baseline_metrics,
        best_equal_hop_by_degree=best_by_degree,
        enumeration_expansions=enumeration.expansions,
        enumeration_seconds=enumeration.elapsed_seconds,
        enumeration_truncated=enumeration.truncated,
        shortest_layer_complete=enumeration.shortest_layer_complete,
        equal_hop_improves_hub=improves,
    )


def stratified_album_pairs(
    graph: PublishedGraph,
    album_ids: Sequence[str],
    *,
    limit: int,
) -> list[tuple[str, str]]:
    """Deterministic pairs spanning every anchor-degree topology --
    chosen programmatically rather than hand-picked, so the measurement
    cannot be accused of selecting flattering examples.

    Albums are ranked by their anchor's degree (how many in-scope
    contributors the album has), split into terciles, and sampled from
    every stratum combination: sparse/sparse, sparse/mid, sparse/dense,
    mid/mid, mid/dense and dense/dense.
    """
    scored: list[tuple[int, str]] = []
    for album_id in album_ids:
        virtual = graph.virtual_id_by_album_id.get(album_id)
        if virtual is None:
            continue
        index = graph.index_by_node_id.get(virtual)
        if index is None:
            continue
        scored.append((graph.degree(index), album_id))
    scored.sort(key=lambda pair: (pair[0], pair[1]))
    ordered = [album_id for _, album_id in scored]
    if len(ordered) < 2:
        return []

    # Split into terciles by anchor degree, then walk EVERY stratum
    # combination -- low/low, low/mid, low/high, mid/mid, mid/high,
    # high/high -- rather than pairing rank i with rank n-1-i. That
    # complementary-rank walk only ever produces sparse/dense (plus
    # middle/middle where the two ends meet), which would bias the
    # route-count and hub-improvement statistics ADR 0059 rests on toward
    # one topology.
    count = len(ordered)
    cut_low = count // 3
    cut_high = (2 * count) // 3
    strata = [
        ordered[:cut_low] or ordered[:1],
        ordered[cut_low:cut_high] or ordered[:1],
        ordered[cut_high:] or ordered[-1:],
    ]
    combinations = [(0, 0), (0, 1), (0, 2), (1, 1), (1, 2), (2, 2)]

    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    # Round-robin across combinations so a small `limit` still samples
    # every topology rather than exhausting the first combination.
    for step in range(limit * len(combinations)):
        if len(pairs) >= limit:
            break
        left_stratum, right_stratum = combinations[step % len(combinations)]
        offset = step // len(combinations)
        left_pool = strata[left_stratum]
        right_pool = strata[right_stratum]
        if not left_pool or not right_pool:
            continue
        left = left_pool[offset % len(left_pool)]
        # Offset the right index so a same-stratum combination does not
        # simply pair an album with itself.
        right = right_pool[(offset + 1 + step) % len(right_pool)]
        if left == right:
            continue
        key = (min(left, right), max(left, right))
        if key in seen:
            continue
        seen.add(key)
        pairs.append((left, right))
    return pairs


def iter_measurements(
    graph: PublishedGraph,
    pairs: Sequence[tuple[str, str]],
    **kwargs: Any,
) -> Iterator[PairMeasurement]:
    for from_album_id, to_album_id in pairs:
        measurement = measure_pair(graph, from_album_id, to_album_id, **kwargs)
        if measurement is not None:
            yield measurement


def summarize(measurements: Sequence[PairMeasurement]) -> dict[str, Any]:
    """Corpus-level rollup -- the numbers ADR 0059 needs to choose a hop
    allowance and a candidate bound."""
    if not measurements:
        return {"pairs_measured": 0}
    with_route = [m for m in measurements if m.shortest_user_hops is not None]
    hub_improvable = [m for m in with_route if m.equal_hop_improves_hub]
    truncated = [m for m in measurements if m.enumeration_truncated]
    equal_hop_counts = sorted(m.equal_hop_route_count for m in with_route)
    return {
        "pairs_measured": len(measurements),
        "pairs_with_a_route": len(with_route),
        "pairs_without_a_route": len(measurements) - len(with_route),
        "shortest_hop_histogram": _histogram(m.shortest_user_hops for m in with_route),
        "equal_hop_alternatives": {
            "min": equal_hop_counts[0] if equal_hop_counts else 0,
            "median": (equal_hop_counts[len(equal_hop_counts) // 2] if equal_hop_counts else 0),
            "max": equal_hop_counts[-1] if equal_hop_counts else 0,
        },
        "equal_hop_hub_improvable": {
            "count": len(hub_improvable),
            "share_of_pairs_with_a_route": (
                len(hub_improvable) / len(with_route) if with_route else 0.0
            ),
        },
        "enumeration": {
            "truncated_pairs": len(truncated),
            "max_expansions": max((m.enumeration_expansions for m in measurements), default=0),
            "max_seconds": max((m.enumeration_seconds for m in measurements), default=0.0),
        },
    }


def _histogram(values: Iterator[int] | Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))
