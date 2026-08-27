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

Performance is not incidental here: every one of `credit_edges_sql`'s rules
(`same_recording`, `co_performers`, `release_scope`) is `GROUP BY release_id`
internally, and its final `directed` relation is a plain `UNION ALL` of
those three -- there is no join or aggregate anywhere in the query that
crosses release boundaries. That means the SET of (artist_a, artist_b) PAIRS
a release contributes is entirely determined by that release's own credit
rows, independent of which other releases share the connection's `credits`/
`releases` views. (Only the *evidence citation* -- which specific
`release_id` gets attached to a pair that also appears on another release --
depends on cross-release ordering, via `_evidence_collapse_sql`; this module
discards that citation, so it never depends on the property that doesn't
decompose.) `edges_by_release` exploits this to compute every finalist's own
edge contribution exactly once, up front, rather than re-deriving the whole
scope from scratch at every greedy step.

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


def _view_setup_sql(releases_glob: str, credits_glob: str) -> tuple[str, str]:
    return (
        f"CREATE VIEW all_releases AS SELECT * FROM {read_parquet_sql(releases_glob)}",
        f"CREATE VIEW all_credits AS SELECT * FROM {read_parquet_sql(credits_glob)}",
    )


def _scope_views_sql(release_ids_sql: str) -> tuple[str, str, str]:
    return (
        f"CREATE OR REPLACE VIEW releases AS SELECT * FROM all_releases "
        f"WHERE release_id IN ({release_ids_sql})",
        f"CREATE OR REPLACE VIEW credits AS SELECT * FROM all_credits "
        f"WHERE release_id IN ({release_ids_sql})",
        "CREATE OR REPLACE VIEW release_formats AS "
        "SELECT NULL::BIGINT AS release_id, NULL::VARCHAR[] AS descriptions WHERE FALSE",
    )


def _undirected(rows: list[tuple[int, int, int]]) -> frozenset[tuple[int, int]]:
    return frozenset((a, b) if a < b else (b, a) for a, b, _release_id in rows)


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
    releases_glob = str(Path(dataset_root) / "table=releases" / "*.parquet")
    credits_glob = str(Path(dataset_root) / "table=credits" / "*.parquet")
    ids_sql = ", ".join(str(int(r)) for r in sorted(release_ids))
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(f"SET memory_limit = '{memory_limit}'")
        connection.execute(f"SET threads = {int(threads)}")
        for statement in _view_setup_sql(releases_glob, credits_glob):
            connection.execute(statement)
        for statement in _scope_views_sql(ids_sql):
            connection.execute(statement)
        rows = connection.execute(
            credit_edges_sql(max_artists_per_release=max_artists_per_release)
        ).fetchall()
    finally:
        connection.close()
    return _undirected(rows)


def edges_by_release(
    dataset_root: Path,
    release_ids: frozenset[int],
    *,
    max_artists_per_release: int = 50,
    memory_limit: str = "1GB",
    threads: int = 2,
) -> dict[int, frozenset[tuple[int, int]]]:
    """Each release's OWN co-credit edge contribution, computed in
    isolation -- one release at a time, one shared connection reused across
    all of them (never a fresh `duckdb.connect()` per release, and never a
    combined multi-release scan that could conflate which release
    contributed which edge). See the module docstring for why per-release
    isolation is exactly as correct as a combined scan for PAIR EXISTENCE,
    while being reusable across an unbounded number of downstream marginal
    computations without re-scanning the dataset again.
    """
    result: dict[int, frozenset[tuple[int, int]]] = {}
    if not release_ids:
        return result
    releases_glob = str(Path(dataset_root) / "table=releases" / "*.parquet")
    credits_glob = str(Path(dataset_root) / "table=credits" / "*.parquet")
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(f"SET memory_limit = '{memory_limit}'")
        connection.execute(f"SET threads = {int(threads)}")
        for statement in _view_setup_sql(releases_glob, credits_glob):
            connection.execute(statement)
        for release_id in sorted(release_ids):
            for statement in _scope_views_sql(str(int(release_id))):
                connection.execute(statement)
            rows = connection.execute(
                credit_edges_sql(max_artists_per_release=max_artists_per_release)
            ).fetchall()
            result[int(release_id)] = _undirected(rows)
    finally:
        connection.close()
    return result


def _nodes(edges: frozenset[tuple[int, int]]) -> frozenset[int]:
    return frozenset(node for pair in edges for node in pair)


def greedy_marginal_selection(
    dataset_root: Path,
    *,
    baseline_release_ids: frozenset[int],
    baseline_artist_ids: frozenset[int],
    finalists: list[dict[str, Any]],
    count: int,
    max_artists_per_release: int = 50,
    memory_limit: str = "1GB",
    threads: int = 2,
) -> list[dict[str, Any]]:
    """Deterministic greedy selection of `count` finalists by TRUE marginal
    edge value, given everything already selected earlier in this same run.

    Each `finalists` entry must carry `master_id`, `main_release_id`, and
    `artist_id`; every other key is passed through unchanged on the entries
    this returns.

    `baseline_artist_ids` -- the artists already in the catalog and/or
    already-approved Bucket A additions -- excludes matching finalists
    UPFRONT, mirroring `assemble_album_catalog`'s own "an editorial artist's
    candidate never gets added twice" rule (ADR 0038). This bucket also
    enforces at most one selection per artist among itself: once a finalist
    is picked, every other finalist sharing its `artist_id` becomes
    ineligible for the rest of this run. Without both rules, this function
    could report `selected_count` albums that `assemble_album_catalog` would
    later silently shrink by dropping duplicates -- an honest evaluator's
    output must match what the catalog build will actually keep.

    At each step, the finalist with the most NEW edges (relative to
    everything already in scope) is picked; ties break by new contributor
    count, then by the finalist's own `score` field (if present, descending),
    then by `master_id` ascending -- fully deterministic, so re-running this
    function over the same inputs always produces the same selection and
    order, which is what makes an unattended selection reviewable after the
    fact rather than merely reproducible in principle.

    Cost: one scoped query for the baseline, one query per remaining
    finalist's own release (computed once, up front, via `edges_by_release`)
    -- O(finalists) total dataset queries, not O(count * finalists); every
    round after that is pure in-memory set arithmetic.
    """
    if count <= 0:
        return []

    remaining = [f for f in finalists if int(f["artist_id"]) not in baseline_artist_ids]
    if not remaining:
        return []

    current_edges = edges_for_release_scope(
        dataset_root,
        baseline_release_ids,
        max_artists_per_release=max_artists_per_release,
        memory_limit=memory_limit,
        threads=threads,
    )
    current_nodes = _nodes(current_edges)

    finalist_release_ids = frozenset(int(f["main_release_id"]) for f in remaining)
    finalist_edges = edges_by_release(
        dataset_root,
        finalist_release_ids,
        max_artists_per_release=max_artists_per_release,
        memory_limit=memory_limit,
        threads=threads,
    )

    selected: list[dict[str, Any]] = []
    selected_artist_ids: set[int] = set()

    while remaining and len(selected) < count:
        best_candidate: dict[str, Any] | None = None
        best_key: tuple[int, int, int, int] | None = None
        best_edges: frozenset[tuple[int, int]] | None = None

        for candidate in remaining:
            if int(candidate["artist_id"]) in selected_artist_ids:
                continue
            candidate_edges = finalist_edges[int(candidate["main_release_id"])]
            new_edge_count = len(candidate_edges - current_edges)
            new_node_count = len(_nodes(candidate_edges) - current_nodes)
            key = (
                -new_edge_count,
                -new_node_count,
                -int(candidate.get("score") or 0),
                int(candidate["master_id"]),
            )
            if best_key is None or key < best_key:
                best_key = key
                best_candidate = candidate
                best_edges = candidate_edges

        if best_candidate is None or best_key is None or best_edges is None:
            break  # every remaining finalist shares an artist already selected

        new_edge_count = -best_key[0]
        new_node_count = -best_key[1]
        selected.append(
            {
                **best_candidate,
                "marginal_new_edges": new_edge_count,
                "marginal_new_contributors": new_node_count,
            }
        )
        selected_artist_ids.add(int(best_candidate["artist_id"]))
        current_edges = current_edges | best_edges
        current_nodes = current_nodes | _nodes(best_edges)
        remaining.remove(best_candidate)

    return selected
