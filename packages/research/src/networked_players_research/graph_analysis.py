"""Graph-structure analyses (`contributor_network`, `community_detection`,
`bridge_analysis`) built on igraph -- ADR 0055's measured selection for
offline research analytics. Reuses `graph_bench.load_edges` for real
co-credit edges (`graph.py`'s own `credit_edges_sql` semantics).

Community output is always labeled `community <n> under algorithm <a>
params <p>` -- never a human-sounding scene/era name -- per ADR 0054's
fact-vs-interpretation discipline: a human or LLM may later *suggest* a
descriptive label, recorded separately as an `"interpretation"`, but this
module never invents one itself.

`published_graph_community_detection`/`published_graph_articulation_points`
(graph-expansion Phase 0 slice 0-C) are a second, distinct data source in
this same file: they measure the real PUBLISHED `pathfinding/graph.v3.json`
artifact directly (via `route_quality.load_published_graph`'s CSR), not a
DuckDB-queried topic corpus. Dependency-free of the private one-hop corpus
-- any checkout can reproduce these from the committed artifact alone, the
same property `route_quality.py`'s own module docstring documents for its
functions.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import duckdb
import igraph as ig

from .graph_bench import _undirected_dedup, load_edges
from .route_quality import PublishedGraph, load_published_graph


def _load_graph(corpus_snapshot_root: Path) -> tuple[ig.Graph, list[int]]:
    edges = load_edges(corpus_snapshot_root)
    pairs = _undirected_dedup(edges)
    node_ids = sorted({n for edge in pairs for n in edge})
    index_of = {node_id: i for i, node_id in enumerate(node_ids)}

    graph = ig.Graph()
    graph.add_vertices(len(node_ids))
    graph.vs["artist_id"] = node_ids
    graph.add_edges([(index_of[a], index_of[b]) for a, b in pairs])
    return graph, node_ids


def _artist_names(corpus_snapshot_root: Path, artist_ids: list[int]) -> dict[int, str]:
    if not artist_ids:
        return {}
    credits_glob = str(corpus_snapshot_root / "table=credits" / "*.parquet")
    connection = duckdb.connect(database=":memory:")
    try:
        placeholders = ", ".join(str(a) for a in artist_ids)
        rows = connection.execute(
            f"""
            SELECT artist_id, arg_max(name, snapshot_date) AS name
            FROM read_parquet('{credits_glob}', hive_partitioning=false)
            WHERE artist_id IN ({placeholders})
            GROUP BY artist_id
            """
        ).fetchall()
    finally:
        connection.close()
    return {int(artist_id): name for artist_id, name in rows}


def contributor_network(corpus_snapshot_root: Path) -> dict[str, Any]:
    """The real co-credit graph as nodes (artist_id, name, degree) and
    edges (artist_a_id, artist_b_id) -- a direct, un-interpreted structural
    view; degree is the only per-node signal computed here."""
    graph, node_ids = _load_graph(corpus_snapshot_root)
    names = _artist_names(corpus_snapshot_root, node_ids)
    degrees = graph.degree()

    nodes = [
        {"artist_id": artist_id, "name": names.get(artist_id), "degree": degree}
        for artist_id, degree in zip(node_ids, degrees, strict=True)
    ]
    edges = [
        {"artist_a_id": node_ids[edge.source], "artist_b_id": node_ids[edge.target]}
        for edge in graph.es
    ]
    return {"kind": "contributor_network", "nodes": nodes, "edges": edges}


def community_detection(corpus_snapshot_root: Path) -> dict[str, Any]:
    """Leiden community detection (`igraph.Graph.community_leiden`,
    modularity objective) over the real co-credit graph. Every community is
    labeled only by its algorithm-assigned index -- see module docstring."""
    graph, node_ids = _load_graph(corpus_snapshot_root)
    names = _artist_names(corpus_snapshot_root, node_ids)

    algorithm = "leiden"
    params = {"objective_function": "modularity"}
    if graph.ecount() == 0:
        communities = []
    else:
        communities = graph.community_leiden(objective_function=params["objective_function"])

    assignments = []
    for community_index, member_indices in enumerate(communities):
        for member_index in member_indices:
            artist_id = node_ids[member_index]
            assignments.append(
                {
                    "artist_id": artist_id,
                    "name": names.get(artist_id),
                    "community": f"community {community_index} under algorithm {algorithm} "
                    f"params {params}",
                }
            )

    return {
        "kind": "community_detection",
        "algorithm": algorithm,
        "params": params,
        "community_count": len(communities),
        "assignments": assignments,
    }


def bridge_analysis(corpus_snapshot_root: Path, *, top_n: int = 25) -> dict[str, Any]:
    """Bridge-contributor ranking: betweenness centrality over the real
    co-credit graph, restricted to the top `top_n` -- contributors whose
    removal would most fragment the network, not a claim about their
    real-world importance or influence."""
    graph, node_ids = _load_graph(corpus_snapshot_root)
    names = _artist_names(corpus_snapshot_root, node_ids)

    betweenness = graph.betweenness() if graph.vcount() > 2 else [0.0] * graph.vcount()
    ranked = sorted(
        zip(node_ids, betweenness, strict=True), key=lambda pair: pair[1], reverse=True
    )[:top_n]

    return {
        "kind": "bridge_analysis",
        "signal": "betweenness_centrality",
        "ranked_contributors": [
            {"artist_id": artist_id, "name": names.get(artist_id), "betweenness": score}
            for artist_id, score in ranked
        ],
    }


def _load_published_graph_as_igraph(path: Path) -> tuple[ig.Graph, PublishedGraph]:
    """CSR -> igraph adapter for the published pathfinding graph artifact.
    `neighbors[]` values are already node INDICES (confirmed against
    `route_quality.py`'s own BFS, which uses them interchangeably with
    `start_index`/`goal_index`), so no id-to-index lookup is needed here --
    only de-duplicating the CSR's directed pairs into a plain undirected
    edge set, the same `_undirected_dedup` pattern this file already uses
    for topic-corpus edges."""
    published = load_published_graph(path)
    n = published.node_count
    edges: set[tuple[int, int]] = set()
    for i in range(n):
        for slot in published.slots(i):
            j = published.neighbors[slot]
            if i != j:
                edges.add((min(i, j), max(i, j)))
    graph = ig.Graph()
    graph.add_vertices(n)
    graph.add_edges(sorted(edges))
    return graph, published


def published_graph_community_detection(path: Path) -> dict[str, Any]:
    """Leiden over the real PUBLISHED `pathfinding/graph.v3.json` artifact
    (graph-expansion Phase 0 slice 0-C, plan section 8's "community
    detection earns its place with one cheap measurement"). Reports
    modularity, timing, and how many album-anchor nodes share a community
    with at least one other anchor -- the exact numbers the plan's
    earn/deny gate (runtime < 60s, modularity > 0.3, >= 60% of anchors in a
    majority community) is keyed on. This function only measures; deciding
    whether the gate is met, and recording that decision in ADR 0070, is a
    separate step."""
    graph, published = _load_published_graph_as_igraph(path)
    anchor_indices = set(published.virtual_id_by_album_id.values())

    start = time.perf_counter()
    communities = (
        graph.community_leiden(objective_function="modularity") if graph.ecount() > 0 else None
    )
    elapsed_s = time.perf_counter() - start

    community_of_anchor: dict[int, int] = {}
    if communities is not None:
        for community_index, members in enumerate(communities):
            for member in members:
                if member in anchor_indices:
                    community_of_anchor[member] = community_index
    anchor_counts_by_community: dict[int, int] = {}
    for community_index in community_of_anchor.values():
        anchor_counts_by_community[community_index] = (
            anchor_counts_by_community.get(community_index, 0) + 1
        )
    anchors_sharing_a_community = sum(
        1 for c in community_of_anchor.values() if anchor_counts_by_community[c] > 1
    )

    return {
        "kind": "published_graph_community_detection",
        "algorithm": "leiden",
        "objective_function": "modularity",
        "node_count": graph.vcount(),
        "edge_count": graph.ecount(),
        "elapsed_s": elapsed_s,
        "community_count": len(communities) if communities is not None else 0,
        "modularity": communities.modularity if communities is not None else None,
        "anchor_count": len(anchor_indices),
        "anchors_sharing_a_community_with_another_anchor": anchors_sharing_a_community,
        "anchor_majority_community_fraction": (
            anchors_sharing_a_community / len(anchor_indices) if anchor_indices else None
        ),
    }


def published_graph_articulation_points(path: Path) -> dict[str, Any]:
    """Cut vertices in the real PUBLISHED `pathfinding/graph.v3.json`
    artifact, filtered to ones separating >= 2 album anchors into different
    resulting components (plan section 8) -- ADR 0063's own research
    measured 140 raw cut vertices on a comparable-scale graph, and found
    EVERY one just shed a single degree-1 leaf artist, never bridging two
    real anchor-bearing regions ("the single-leaf case that sank ADR
    0063"). This reproduces that filter as real, tested code instead of
    one-off research-session arithmetic, so a future measurement can be
    re-run rather than re-derived by hand."""
    graph, published = _load_published_graph_as_igraph(path)
    anchor_indices = set(published.virtual_id_by_album_id.values())

    start = time.perf_counter()
    raw_cut_vertices = graph.articulation_points() if graph.vcount() > 2 else []
    elapsed_s = time.perf_counter() - start

    # Original vertex index is preserved as an attribute through deletion
    # (igraph reindexes the copy, not the attribute), so a component's
    # anchor membership can be traced back to the real node id afterward.
    graph.vs["orig_index"] = list(range(graph.vcount()))
    real_bridges: list[dict[str, Any]] = []
    for v in raw_cut_vertices:
        remaining = graph.copy()
        remaining.delete_vertices([v])
        components = remaining.connected_components()
        membership = components.membership
        anchor_component_ids: set[int] = set()
        for vertex in remaining.vs:
            if vertex["orig_index"] in anchor_indices:
                anchor_component_ids.add(membership[vertex.index])
        if len(anchor_component_ids) >= 2:
            real_bridges.append(
                {
                    "node_index": v,
                    "node_id": published.node_ids[v],
                    "name": published.names[v],
                    "components_with_an_anchor": len(anchor_component_ids),
                }
            )

    return {
        "kind": "published_graph_articulation_points",
        "node_count": graph.vcount(),
        "edge_count": graph.ecount(),
        "elapsed_s": elapsed_s,
        "raw_cut_vertex_count": len(raw_cut_vertices),
        "real_bridge_count": len(real_bridges),
        "real_bridges": real_bridges,
    }
