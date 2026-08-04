"""Graph-structure analyses (`contributor_network`, `community_detection`,
`bridge_analysis`) built on igraph -- ADR 0055's measured selection for
offline research analytics. Reuses `graph_bench.load_edges` for real
co-credit edges (`graph.py`'s own `credit_edges_sql` semantics).

Community output is always labeled `community <n> under algorithm <a>
params <p>` -- never a human-sounding scene/era name -- per ADR 0054's
fact-vs-interpretation discipline: a human or LLM may later *suggest* a
descriptive label, recorded separately as an `"interpretation"`, but this
module never invents one itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import igraph as ig

from .graph_bench import _undirected_dedup, load_edges


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
