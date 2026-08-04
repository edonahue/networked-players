"""Graph-library benchmark (Phase 3 Slice C): compares the existing
DuckDB-backed `CreditGraph`/CSR representations against three general-
purpose graph libraries (NetworkX, python-igraph, rustworkx) at
topic-corpus scale -- closing `docs/ROADMAP.md` section 7's open item
("compare compact arrays with at least one optimized graph library").

Real edges are loaded via `graph.py`'s own public `credit_edges_sql` --
the exact same co-credit semantics the production game traversal uses
(same_recording/co_performers/release_scope, placeholder/compilation
guards), never a simplified re-derivation. This module answers "what
structure exists in this network" (components, communities, degree) --
DuckDB/CSR already answer "how does A connect to B" well; nothing here
replaces `graph.py`'s production path.

Method is public; real numbers on real hardware never get committed here
or transcribed into a doc (ADR 0018) -- results belong in
`local/benchmarks/` only. `docs/RESEARCH_GRAPH_BENCHMARK_METHOD.md` is the
public methodology this module implements.
"""

from __future__ import annotations

import time
import tracemalloc
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

import duckdb

from networked_players_graph_core.graph import credit_edges_sql

Edge = tuple[int, int, int]


def load_edges(corpus_snapshot_root: Path, *, max_artists_per_release: int = 50) -> list[Edge]:
    """Real `(artist_a_id, artist_b_id, release_id)` co-credit edges for a
    topic corpus, via `graph.py`'s own `credit_edges_sql` -- which reads
    both `credits` and `releases` (the latter for its non-studio-release
    title guard), mirroring `CreditGraph.open()`'s own view setup."""
    credits_glob = str(corpus_snapshot_root / "table=credits" / "*.parquet")
    releases_glob = str(corpus_snapshot_root / "table=releases" / "*.parquet")
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(
            "CREATE VIEW credits AS SELECT * FROM "
            f"read_parquet('{credits_glob}', hive_partitioning=false)"
        )
        connection.execute(
            "CREATE VIEW releases AS SELECT * FROM "
            f"read_parquet('{releases_glob}', hive_partitioning=false)"
        )
        sql = credit_edges_sql(max_artists_per_release=max_artists_per_release)
        rows = connection.execute(
            f"SELECT artist_a_id, artist_b_id, release_id FROM ({sql})"
        ).fetchall()
    finally:
        connection.close()
    return [(int(a), int(b), int(r)) for a, b, r in rows]


def _undirected_dedup(edges: list[Edge]) -> set[tuple[int, int]]:
    """`credit_edges_sql` returns a directed relation (both `(a,b)` and
    `(b,a)` rows); every downstream library here wants a plain undirected
    edge set."""
    return {(min(a, b), max(a, b)) for a, b, _release_id in edges}


@dataclass(frozen=True)
class LibraryBenchmark:
    library: str
    node_count: int
    edge_count: int
    construction_time_s: float
    peak_memory_bytes: int
    component_count: int
    largest_component_size: int
    community_count: int | None
    community_time_s: float | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _timed_peak_memory[T](fn: Callable[[], T]) -> tuple[T, float, int]:
    tracemalloc.start()
    start = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - start
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return result, elapsed, peak


def benchmark_networkx(pairs: set[tuple[int, int]]) -> LibraryBenchmark:
    import networkx as nx
    from networkx.algorithms.community import greedy_modularity_communities

    def build() -> nx.Graph:
        g = nx.Graph()
        g.add_edges_from(pairs)
        return g

    graph, construction_s, peak = _timed_peak_memory(build)
    components = list(nx.connected_components(graph))
    community_start = time.perf_counter()
    communities = list(greedy_modularity_communities(graph)) if graph.number_of_edges() else []
    community_s = time.perf_counter() - community_start

    return LibraryBenchmark(
        library="networkx",
        node_count=graph.number_of_nodes(),
        edge_count=graph.number_of_edges(),
        construction_time_s=construction_s,
        peak_memory_bytes=peak,
        component_count=len(components),
        largest_component_size=max((len(c) for c in components), default=0),
        community_count=len(communities),
        community_time_s=community_s,
    )


def benchmark_igraph(pairs: set[tuple[int, int]]) -> LibraryBenchmark:
    import igraph as ig

    node_ids = sorted({n for edge in pairs for n in edge})
    index_of = {node_id: i for i, node_id in enumerate(node_ids)}

    def build() -> ig.Graph:
        g = ig.Graph()
        g.add_vertices(len(node_ids))
        g.add_edges([(index_of[a], index_of[b]) for a, b in pairs])
        return g

    graph, construction_s, peak = _timed_peak_memory(build)
    components = graph.connected_components()
    community_start = time.perf_counter()
    communities = graph.community_leiden(objective_function="modularity") if graph.ecount() else []
    community_s = time.perf_counter() - community_start

    return LibraryBenchmark(
        library="igraph",
        node_count=graph.vcount(),
        edge_count=graph.ecount(),
        construction_time_s=construction_s,
        peak_memory_bytes=peak,
        component_count=len(components),
        largest_component_size=max((len(c) for c in components), default=0),
        community_count=len(communities),
        community_time_s=community_s,
    )


def benchmark_rustworkx(pairs: set[tuple[int, int]]) -> LibraryBenchmark:
    import rustworkx as rx

    node_ids = sorted({n for edge in pairs for n in edge})
    index_of = {node_id: i for i, node_id in enumerate(node_ids)}

    def build() -> rx.PyGraph:
        g = rx.PyGraph()
        g.add_nodes_from(node_ids)
        g.add_edges_from_no_data([(index_of[a], index_of[b]) for a, b in pairs])
        return g

    graph, construction_s, peak = _timed_peak_memory(build)
    components = rx.connected_components(graph)
    # rustworkx has no built-in Leiden/Louvain as of this pass -- community
    # detection is reported as unavailable for this library rather than
    # substituting a different algorithm quietly.
    return LibraryBenchmark(
        library="rustworkx",
        node_count=graph.num_nodes(),
        edge_count=graph.num_edges(),
        construction_time_s=construction_s,
        peak_memory_bytes=peak,
        component_count=len(components),
        largest_component_size=max((len(c) for c in components), default=0),
        community_count=None,
        community_time_s=None,
    )


def run_benchmark(corpus_snapshot_root: Path) -> dict[str, object]:
    edges = load_edges(corpus_snapshot_root)
    pairs = _undirected_dedup(edges)
    results = [
        benchmark_networkx(pairs).to_dict(),
        benchmark_igraph(pairs).to_dict(),
        benchmark_rustworkx(pairs).to_dict(),
    ]
    return {
        "schema_version": 1,
        "raw_edge_count": len(edges),
        "undirected_edge_count": len(pairs),
        "libraries": results,
    }
