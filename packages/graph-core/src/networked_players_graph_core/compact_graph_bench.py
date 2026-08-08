"""Public benchmark methodology for Phase 2 Slice E: a compact, browser-
plausible graph representation and BFS, measured against three candidate
architectures for Connect Two Records (fully browser-local, DuckDB-WASM, or
a bounded Cloudflare Worker) -- see docs/GRAPH_BENCHMARK_METHOD.md for the
decision framework and docs/decisions/0050-*.md for the outcome.

Real measured numbers on real hardware are never committed here or in any
public doc (ADR 0018) -- this module is the reproducible *method*; results
live in local/benchmarks/, gitignored. Prototype/one-off scripts that drive
this module against real data live in local/experiments/graph-benchmark/,
also gitignored -- this module is the only piece of the benchmark that is a
real, tested, committed package, precisely so it never becomes "a fake
supported package" nobody can verify.

This is a genuinely separate representation from `graph.py`'s DuckDB-backed
`CreditGraph` -- it does not replace it, and nothing in the real product
depends on this module today. It exists to measure whether a compact,
in-memory, sorted-integer-array representation is a viable alternative for
client-side pathfinding, mirroring `CreditGraph.find_path`'s contract
(including the inconclusive-vs-no-path distinction) closely enough that the
comparison is meaningful.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field


class FrontierTooLargeBench(RuntimeError):
    """Bench-side mirror of `graph.FrontierTooLargeError`: raised when a
    frontier expansion would exceed `max_frontier_nodes`, so a caller can
    distinguish "gave up because the search space was too large" from
    "confirmed no path exists" -- CreditGraph.find_path's contract, which any
    replacement architecture must preserve rather than silently collapsing
    the two into one "no connection" outcome."""


@dataclass(frozen=True)
class CompactGraph:
    """A CSR (compressed sparse row) adjacency structure over artist_id
    nodes. `node_ids[i]` is the real artist_id for node index `i`;
    `offsets`/`neighbors`/`evidence_release_ids` are parallel CSR arrays --
    `neighbors[offsets[i]:offsets[i+1]]` are node index of every neighbor
    of node `i`, `evidence_release_ids[same slice]` is the release_id
    evidencing each edge. Symmetric: every edge appears in both directions,
    matching `graph.py`'s `credit_edges` (both directions stored)."""

    node_ids: list[int]
    offsets: list[int]
    neighbors: list[int]
    evidence_release_ids: list[int]
    id_to_index: dict[int, int] = field(repr=False)

    def degree(self, index: int) -> int:
        return self.offsets[index + 1] - self.offsets[index]


def build_csr_adjacency(
    edges: list[tuple[int, int, int]], *, extra_node_ids: Iterable[int] = ()
) -> CompactGraph:
    """Build a `CompactGraph` from `(artist_a_id, artist_b_id, release_id)`
    triples -- one row per undirected edge (do not pre-duplicate both
    directions; this function adds both). Deterministic: `node_ids` is
    sorted, and each node's neighbor slice is sorted by neighbor node index,
    so two calls with the same edge set (in any order) produce byte-identical
    arrays -- the property the actual published payload's reproducibility
    depends on.

    `extra_node_ids`: node ids to include even if they appear in no edge at
    all (degree 0). Without this, a node with zero edges is simply absent
    from the graph rather than present-but-isolated -- the pathfinding
    graph's virtual album-anchor nodes (ADR 0058) need the latter for an
    album with no in-scope credited contributors, so the endpoint search
    can report a real "no-path" rather than "unknown-album"."""
    node_id_set: set[int] = set(extra_node_ids)
    for a, b, _release_id in edges:
        node_id_set.add(a)
        node_id_set.add(b)
    node_ids = sorted(node_id_set)
    id_to_index = {node_id: index for index, node_id in enumerate(node_ids)}

    adjacency: list[list[tuple[int, int]]] = [[] for _ in node_ids]
    for a, b, release_id in edges:
        ia, ib = id_to_index[a], id_to_index[b]
        adjacency[ia].append((ib, release_id))
        adjacency[ib].append((ia, release_id))

    offsets = [0] * (len(node_ids) + 1)
    neighbors: list[int] = []
    evidence_release_ids: list[int] = []
    for index, neighbor_list in enumerate(adjacency):
        neighbor_list.sort(key=lambda pair: pair[0])
        offsets[index + 1] = offsets[index] + len(neighbor_list)
        for neighbor_index, release_id in neighbor_list:
            neighbors.append(neighbor_index)
            evidence_release_ids.append(release_id)

    return CompactGraph(
        node_ids=node_ids,
        offsets=offsets,
        neighbors=neighbors,
        evidence_release_ids=evidence_release_ids,
        id_to_index=id_to_index,
    )


def bfs_over_csr(
    graph: CompactGraph,
    from_artist_id: int,
    to_artist_id: int,
    *,
    max_hops: int = 4,
    max_frontier_nodes: int | None = None,
) -> list[dict[str, int]] | None:
    """Breadth-first search over `graph`, mirroring
    `CreditGraph.find_path`'s contract: returns a list of
    `{artist_a_id, artist_b_id, release_id}` hop dicts on success, `None` when
    the search space was fully exhausted within `max_hops` with no path
    found (a *confirmed* no-path), or raises `FrontierTooLargeBench` when
    `max_frontier_nodes` would be exceeded (an *inconclusive* result -- must
    never be reported to a caller as "no connection exists").

    Raises `KeyError`-free `ValueError` if either endpoint isn't in the
    graph -- a caller-visible, typed failure rather than a silent empty
    result.
    """
    if from_artist_id not in graph.id_to_index:
        raise ValueError(f"from_artist_id {from_artist_id} is not in this graph")
    if to_artist_id not in graph.id_to_index:
        raise ValueError(f"to_artist_id {to_artist_id} is not in this graph")

    start = graph.id_to_index[from_artist_id]
    goal = graph.id_to_index[to_artist_id]
    if start == goal:
        return []

    parent: dict[int, tuple[int, int]] = {}  # node index -> (parent index, release_id)
    visited = {start}
    frontier = [start]

    for _hop in range(max_hops):
        if max_frontier_nodes is not None and len(frontier) > max_frontier_nodes:
            raise FrontierTooLargeBench(
                f"frontier of {len(frontier)} nodes exceeds max_frontier_nodes="
                f"{max_frontier_nodes}; search is inconclusive, not a confirmed no-path"
            )
        next_frontier: list[int] = []
        for node in frontier:
            start_offset, end_offset = graph.offsets[node], graph.offsets[node + 1]
            for slot in range(start_offset, end_offset):
                neighbor = graph.neighbors[slot]
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                parent[neighbor] = (node, graph.evidence_release_ids[slot])
                if neighbor == goal:
                    return _reconstruct_path(graph, parent, start, goal)
                next_frontier.append(neighbor)
        frontier = next_frontier
        if not frontier:
            break

    return None


def _reconstruct_path(
    graph: CompactGraph, parent: dict[int, tuple[int, int]], start: int, goal: int
) -> list[dict[str, int]]:
    hops: list[dict[str, int]] = []
    node = goal
    while node != start:
        parent_node, release_id = parent[node]
        hops.append(
            {
                "artist_a_id": graph.node_ids[parent_node],
                "artist_b_id": graph.node_ids[node],
                "release_id": release_id,
            }
        )
        node = parent_node
    hops.reverse()
    return hops


def payload_size_bytes(graph: CompactGraph) -> dict[str, int]:
    """Raw byte counts for the three CSR arrays as they'd be serialized to
    fixed-width typed arrays (Int32Array-equivalent: 4 bytes/element) in the
    actual published payload -- the number the benchmark's gzip/brotli
    measurement (run separately, in `local/experiments/graph-benchmark/`)
    starts from."""
    return {
        "node_ids_bytes": len(graph.node_ids) * 4,
        "offsets_bytes": len(graph.offsets) * 4,
        "neighbors_bytes": len(graph.neighbors) * 4,
        "evidence_release_ids_bytes": len(graph.evidence_release_ids) * 4,
        "total_bytes": (
            len(graph.node_ids) * 4
            + len(graph.offsets) * 4
            + len(graph.neighbors) * 4
            + len(graph.evidence_release_ids) * 4
        ),
    }
