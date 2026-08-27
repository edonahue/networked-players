"""Exact, production-equivalent marginal-value evaluation for Phase 7's
graph-rich candidate bucket (Workstream 1B).

The existing readiness report's `new_contributor_count`
(`candidate_review.py`) is a directional proxy, by its own documented design:
it applies only the base eligibility filter, not `credit_edges_sql`'s real
track-shape and compilation-clique guards, and it never accounts for
candidates already selected in the same run -- each candidate is scored
against the published graph alone, so two candidates that would add the
SAME new contributor both report full credit for that contributor.

This module closes both gaps by reusing `credit_edges_sql` directly --
never a second copy of its rules -- scoped to a specific release-id set at
each step, so the edge set "already selected" and the edge set "one more
candidate would add" are both computed by the exact production logic the
real catalog build uses, not an approximation of it.

Approximation boundary, stated honestly: this measures real edge/contributor
structure, not the downstream Connection Guesser/Record Routes round-generation
yield those edges would produce -- that requires running the actual round
generators, which this module deliberately does not do (see the module's own
docstring in `connection_rounds.py`/`record_routes.py` for why round
generation is a separate, heavier step). A candidate's structural marginal
value here is a real measurement; its projected game-mode yield is not.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

from .graph import credit_edges_sql, read_parquet_sql


def _scoped_connection(
    dataset_root: Path,
    release_ids: frozenset[int],
    *,
    memory_limit: str,
    threads: int,
) -> duckdb.DuckDBPyConnection:
    """A DuckDB connection whose `credits`/`releases` views are restricted to
    exactly `release_ids` -- everything `credit_edges_sql` reads, scoped down
    so a rebuild over a few hundred releases costs nothing like a rebuild
    over the full working set. `release_formats` is always the same
    universally-empty relation `CreditGraph.open` falls back to when no
    format table is present -- this evaluator measures structural edge
    value, not the format-caveat tier, which is a display concern.
    """
    releases_glob = str(Path(dataset_root) / "table=releases" / "*.parquet")
    credits_glob = str(Path(dataset_root) / "table=credits" / "*.parquet")
    connection = duckdb.connect(database=":memory:")
    connection.execute(f"SET memory_limit = '{memory_limit}'")
    connection.execute(f"SET threads = {int(threads)}")
    ids_sql = ", ".join(str(int(r)) for r in sorted(release_ids)) if release_ids else "NULL"
    connection.execute(
        f"CREATE VIEW releases AS SELECT * FROM {read_parquet_sql(releases_glob)} "
        f"WHERE release_id IN ({ids_sql})"
    )
    connection.execute(
        f"CREATE VIEW credits AS SELECT * FROM {read_parquet_sql(credits_glob)} "
        f"WHERE release_id IN ({ids_sql})"
    )
    connection.execute(
        "CREATE VIEW release_formats AS "
        "SELECT NULL::BIGINT AS release_id, NULL::VARCHAR[] AS descriptions WHERE FALSE"
    )
    return connection


def edges_for_release_scope(
    dataset_root: Path,
    release_ids: frozenset[int],
    *,
    max_artists_per_release: int = 50,
    memory_limit: str = "1GB",
    threads: int = 2,
) -> frozenset[tuple[int, int]]:
    """The real, undirected co-credit edge set over exactly `release_ids`,
    computed by `credit_edges_sql` itself. Undirected: `credit_edges_sql`'s
    rows are directed `(artist_a_id, artist_b_id, release_id)`; this
    collapses each pair to a stable, order-independent tuple so `a<->b` and
    `b<->a` (both of which the real edge table can carry) count as one
    edge, matching how a route or a round treats a co-credit link.

    An empty `release_ids` returns an empty edge set without touching the
    dataset at all -- the baseline for a from-scratch evaluation.
    """
    if not release_ids:
        return frozenset()
    connection = _scoped_connection(
        dataset_root, release_ids, memory_limit=memory_limit, threads=threads
    )
    try:
        rows = connection.execute(
            credit_edges_sql(max_artists_per_release=max_artists_per_release)
        ).fetchall()
    finally:
        connection.close()
    return frozenset((a, b) if a < b else (b, a) for a, b, _release_id in rows)


def _nodes(edges: frozenset[tuple[int, int]]) -> frozenset[int]:
    return frozenset(node for pair in edges for node in pair)


def greedy_marginal_selection(
    dataset_root: Path,
    *,
    baseline_release_ids: frozenset[int],
    finalists: list[dict[str, Any]],
    count: int,
    max_artists_per_release: int = 50,
    memory_limit: str = "1GB",
    threads: int = 2,
) -> list[dict[str, Any]]:
    """Deterministic greedy selection of `count` finalists by TRUE marginal
    edge value, given everything already selected earlier in this same run.

    Each `finalists` entry must carry `master_id` and `main_release_id`;
    every other key is passed through unchanged on the entries this returns.

    At each step, for every remaining finalist, this computes the edge set
    of (current baseline release scope + that finalist's main_release_id)
    and diffs it against the current baseline's own edge set -- exact
    `credit_edges_sql` semantics, not an approximation. The finalist with
    the most NEW edges is picked; ties break by new contributor count, then
    by the finalist's own `score` field (if present, descending), then by
    `master_id` ascending -- fully deterministic, so re-running this
    function over the same inputs always produces the same selection and
    order, which is what makes an unattended selection reviewable after the
    fact rather than merely reproducible in principle.

    Cost: O(count * remaining_finalists) scoped rebuilds, each over a small
    release set (the growing baseline plus one candidate) -- tractable for a
    bounded finalist set (tens, not hundreds) and slot count (tens), because
    each rebuild is scoped to that release set, never the full corpus.
    """
    if count <= 0:
        return []

    remaining = list(finalists)
    selected: list[dict[str, Any]] = []
    current_release_ids = set(baseline_release_ids)
    current_edges = edges_for_release_scope(
        dataset_root,
        frozenset(current_release_ids),
        max_artists_per_release=max_artists_per_release,
        memory_limit=memory_limit,
        threads=threads,
    )
    current_nodes = _nodes(current_edges)

    for _ in range(min(count, len(remaining))):
        best_candidate: dict[str, Any] | None = None
        best_key: tuple[int, int, int, int] | None = None
        best_state: tuple[set[int], frozenset[tuple[int, int]], frozenset[int]] | None = None

        for candidate in remaining:
            candidate_release_ids = current_release_ids | {int(candidate["main_release_id"])}
            candidate_edges = edges_for_release_scope(
                dataset_root,
                frozenset(candidate_release_ids),
                max_artists_per_release=max_artists_per_release,
                memory_limit=memory_limit,
                threads=threads,
            )
            candidate_nodes = _nodes(candidate_edges)
            new_edge_count = len(candidate_edges - current_edges)
            new_node_count = len(candidate_nodes - current_nodes)
            key = (
                -new_edge_count,
                -new_node_count,
                -int(candidate.get("score") or 0),
                int(candidate["master_id"]),
            )
            if best_key is None or key < best_key:
                best_key = key
                best_candidate = candidate
                best_state = (candidate_release_ids, candidate_edges, candidate_nodes)

        assert best_candidate is not None and best_key is not None and best_state is not None
        new_edge_count = -best_key[0]
        new_node_count = -best_key[1]
        selected.append(
            {
                **best_candidate,
                "marginal_new_edges": new_edge_count,
                "marginal_new_contributors": new_node_count,
            }
        )
        remaining.remove(best_candidate)
        current_release_ids, current_edges, current_nodes = best_state

    return selected
