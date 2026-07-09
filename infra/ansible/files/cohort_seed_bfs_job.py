#!/usr/bin/env python3
"""Standalone cohort seed-BFS job body, for an RQ worker (Pi or x86).

Self-contained (stdlib + duckdb only) on purpose -- a Pi's lean worker venv
(equip-workers.yml: redis/rq/duckdb, no lxml/pyarrow) can't import
networked_players_graph_core. This is a hand-maintained MIRROR of
networked_players_graph_core.cohort_connectivity._bfs_from_seed plus
CreditGraph's credit_row_counts/neighbors_batch (see ADR 0032) -- the real
reference implementation, tested normally under packages/graph-core.
If those change, mirror the change here too;
packages/graph-core/tests/test_cohort_seed_bfs_job_body.py cross-checks the
two against the same synthetic inputs to catch drift.

Deployed by infra/ansible/playbooks/deploy-cohort-seed-bfs-job.yml, placed at
rq_jobs_dir. Enqueued by scripts/enqueue_cohort_seed_bfs.py via
``Queue(...).enqueue("cohort_seed_bfs_job.run_seed_bfs_chunk", seed_artist_ids,
max_hops, max_frontier_expansion, snapshot_date)``.

Deliberately reads the dataset from CATALOG_DATA_DIR only (ADR 0025's
verified local cache) -- never CATALOG_DATA_URL. A worker doing real BFS work
should be querying its own bounded local cache, not re-reading the dataset
over the LAN for every job. Dispatch granularity is a CHUNK of seed artists,
not individual neighbor lookups (see ADR 0032 for why) -- this keeps each RQ
job a single bounded, timeout-guarded unit, never open-ended traversal, per
docs/HARDWARE.md's "never graph traversal... on Pi" constraint.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import duckdb

# Mirrors networked_players_graph_core.graph.NON_INDIVIDUAL_ARTIST_IDS.
_NON_INDIVIDUAL_ARTIST_IDS = (194,)


class SeedBfsJobError(RuntimeError):
    """Raised when the dataset needed to run this job can't be opened."""


def _dataset_root(snapshot_date: str) -> Path:
    cache_dir = os.environ.get("CATALOG_DATA_DIR")
    if not cache_dir:
        raise SeedBfsJobError("CATALOG_DATA_DIR is not set -- this job requires a local cache")
    root = Path(cache_dir) / "discogs-onehop" / f"snapshot={snapshot_date}"
    if not (root / ".verified.json").exists():
        raise SeedBfsJobError(f"{root} is not a validated cache (no .verified.json)")
    return root


def _open_connection(dataset_root: Path) -> duckdb.DuckDBPyConnection:
    """Mirrors CreditGraph.open()'s view/table setup, minus everything this
    job doesn't need (releases view, masters, max_artists_per_release
    parameterization uses the same default: 50)."""
    credits_glob = str(dataset_root / "table=credits" / "*.parquet")
    connection = duckdb.connect(database=":memory:")
    connection.execute("SET memory_limit = '512MB'")
    connection.execute("SET threads = 1")
    try:
        connection.execute(
            "CREATE VIEW credits AS SELECT * FROM "
            f"read_parquet('{credits_glob}', hive_partitioning = false)"
        )
    except duckdb.IOException as exc:
        raise SeedBfsJobError(f"could not open dataset at {dataset_root}: {exc}") from exc

    non_individual = ", ".join(str(i) for i in _NON_INDIVIDUAL_ARTIST_IDS)
    connection.execute(
        "CREATE TABLE linked_credits AS "
        "SELECT release_id, artist_id, name FROM credits "
        "WHERE playable_identity AND artist_id IS NOT NULL AND artist_id > 0 "
        f"AND artist_id NOT IN ({non_individual})"
    )
    connection.execute(
        "CREATE TABLE traversal_releases AS "
        "SELECT release_id FROM linked_credits GROUP BY release_id "
        "HAVING count(DISTINCT artist_id) BETWEEN 2 AND 50"
    )
    return connection


def _scratch_id_table(connection: duckdb.DuckDBPyConnection, artist_ids: list[int]) -> str:
    table = f"scratch_ids_{uuid.uuid4().hex}"
    connection.execute(f"CREATE TEMP TABLE {table} (artist_id BIGINT)")
    connection.executemany(f"INSERT INTO {table} VALUES (?)", [[a] for a in artist_ids])
    return table


def _credit_row_counts(
    connection: duckdb.DuckDBPyConnection, artist_ids: list[int]
) -> dict[int, int]:
    if not artist_ids:
        return {}
    table = _scratch_id_table(connection, artist_ids)
    try:
        rows = connection.execute(
            "SELECT artist_id, count(*) FROM linked_credits "
            f"WHERE artist_id IN (SELECT artist_id FROM {table}) "
            "GROUP BY artist_id"
        ).fetchall()
    finally:
        connection.execute(f"DROP TABLE {table}")
    return {int(artist_id): int(count) for artist_id, count in rows}


def _neighbors_batch(
    connection: duckdb.DuckDBPyConnection, artist_ids: list[int]
) -> dict[int, dict[int, tuple[int, ...]]]:
    if not artist_ids:
        return {}
    table = _scratch_id_table(connection, artist_ids)
    try:
        rows = connection.execute(
            "SELECT a.artist_id, b.artist_id, "
            "list(DISTINCT a.release_id ORDER BY a.release_id) "
            "FROM linked_credits a "
            "JOIN linked_credits b USING (release_id) "
            "JOIN traversal_releases USING (release_id) "
            f"JOIN {table} f ON f.artist_id = a.artist_id "
            "WHERE b.artist_id != a.artist_id "
            "GROUP BY a.artist_id, b.artist_id ORDER BY a.artist_id, b.artist_id"
        ).fetchall()
    finally:
        connection.execute(f"DROP TABLE {table}")
    result: dict[int, dict[int, tuple[int, ...]]] = {int(a): {} for a in artist_ids}
    for a_id, b_id, release_ids in rows:
        result[int(a_id)][int(b_id)] = tuple(int(r) for r in release_ids)
    return result


def _bfs_from_seed(
    connection: duckdb.DuckDBPyConnection,
    seed_artist_id: int,
    *,
    max_hops: int,
    max_frontier_expansion: int | None,
    neighbor_cache: dict[int, dict[int, tuple[int, ...]]],
    deadline: float | None,
) -> tuple[dict[int, tuple[int, int]], frozenset[int]]:
    """Mirrors networked_players_graph_core.cohort_connectivity._bfs_from_seed."""
    visited = {seed_artist_id}
    parent: dict[int, tuple[int, int]] = {}
    capped_artist_ids: set[int] = set()
    frontier = [seed_artist_id]
    for _ in range(max_hops):
        if deadline is not None and time.monotonic() > deadline:
            raise TimeoutError(f"seed {seed_artist_id} expansion exceeded its deadline")

        if max_frontier_expansion is not None:
            counts = _credit_row_counts(connection, frontier)
            safe_frontier = [a for a in frontier if counts.get(a, 0) <= max_frontier_expansion]
            capped_artist_ids.update(a for a in frontier if a not in safe_frontier)
        else:
            safe_frontier = frontier

        uncached = [a for a in safe_frontier if a not in neighbor_cache]
        if uncached:
            for artist_id, neighbors in _neighbors_batch(connection, uncached).items():
                neighbor_cache[artist_id] = neighbors

        next_frontier: list[int] = []
        for artist_id in safe_frontier:
            for neighbor_id, release_ids in neighbor_cache[artist_id].items():
                if neighbor_id in visited:
                    continue
                visited.add(neighbor_id)
                parent[neighbor_id] = (artist_id, release_ids[0])
                next_frontier.append(neighbor_id)
        frontier = next_frontier
        if not frontier:
            break
    return parent, frozenset(capped_artist_ids)


def _run_with_timeout(
    connection: duckdb.DuckDBPyConnection, fn: Any, *, timeout_seconds: float | None
) -> Any:
    """Mirrors networked_players_graph_core.cohort_connectivity._run_with_timeout."""
    if timeout_seconds is None:
        return fn()

    fired = threading.Event()

    def _fire() -> None:
        fired.set()
        connection.interrupt()

    timer = threading.Timer(timeout_seconds, _fire)
    timer.start()
    try:
        return fn()
    except duckdb.Error:
        if fired.is_set():
            raise TimeoutError(f"exceeded {timeout_seconds}s and was interrupted") from None
        raise
    finally:
        timer.cancel()


def run_seed_bfs_chunk(
    seed_artist_ids: list[int],
    max_hops: int,
    max_frontier_expansion: int | None,
    snapshot_date: str,
    *,
    pair_timeout_seconds: float | None = 30.0,
) -> dict[str, Any]:
    """Runs one bounded BFS per seed_artist_id in this chunk, sharing a
    neighbor cache across the whole chunk (a hub shared by two seeds in the
    same chunk is queried at most once) -- the exact cross-seed caching
    `score_pairs` already does locally, just for this chunk's own share of
    seeds. Returns a JSON-serializable dict keyed by str(seed_artist_id).
    """
    dataset_root = _dataset_root(snapshot_date)
    connection = _open_connection(dataset_root)
    neighbor_cache: dict[int, dict[int, tuple[int, ...]]] = {}
    results: dict[str, Any] = {}

    try:
        for seed_artist_id in seed_artist_ids:
            deadline = time.monotonic() + pair_timeout_seconds if pair_timeout_seconds else None

            def _do_bfs(
                aid: int = seed_artist_id, dl: float | None = deadline
            ) -> tuple[dict[int, tuple[int, int]], frozenset[int]]:
                return _bfs_from_seed(
                    connection,
                    aid,
                    max_hops=max_hops,
                    max_frontier_expansion=max_frontier_expansion,
                    neighbor_cache=neighbor_cache,
                    deadline=dl,
                )

            try:
                parent, capped = _run_with_timeout(
                    connection, _do_bfs, timeout_seconds=pair_timeout_seconds
                )
            except TimeoutError:
                results[str(seed_artist_id)] = {"status": "timeout"}
                continue

            results[str(seed_artist_id)] = {
                "status": "ok",
                "parent": [
                    [artist_id, parent_id, release_id]
                    for artist_id, (parent_id, release_id) in parent.items()
                ],
                "capped": sorted(capped),
            }
    finally:
        connection.close()

    return results


def main() -> None:
    if len(sys.argv) != 5:
        print(
            "Usage: cohort_seed_bfs_job.py <comma-separated-seed-ids> <max_hops> "
            "<max_frontier_expansion|none> <snapshot_date>",
            file=sys.stderr,
        )
        raise SystemExit(2)
    seed_ids = [int(s) for s in sys.argv[1].split(",")]
    max_hops = int(sys.argv[2])
    max_frontier_expansion = None if sys.argv[3].lower() == "none" else int(sys.argv[3])
    snapshot_date = sys.argv[4]
    result = run_seed_bfs_chunk(seed_ids, max_hops, max_frontier_expansion, snapshot_date)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
