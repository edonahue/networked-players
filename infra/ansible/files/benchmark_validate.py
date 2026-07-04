#!/usr/bin/env python3
"""Standalone checksummed-partition-validation probe for cluster node comparison.

Deliberately NOT packages/catalog's real validate_dataset() (see
packages/catalog/src/networked_players_catalog/discogs/validation.py) --
importing that package would drag lxml/pyarrow onto a Pi worker, which
AGENTS.md scopes to the coordination host/workstation only. This probe
inlines the same DuckDB query SHAPE (row counts, distinct-count, ANTI JOIN,
manifest-style reconciliation) against an in-memory, DuckDB-SQL-generated
synthetic table -- not a real Parquet file, so it stays reproducible from
source alone and needs no per-run file copy to each Pi (see AGENTS.md's
"keep fixtures synthetic and reproducible" rule).

Sizing: 5,000 releases matches packages/catalog's real chunk_releases
default (parquet.py). Credits count scaled by the observed real ratio
~11.46 credits/release (220,015,758 credit rows / 19,192,301 releases from
the 2026-07-02 full real ingest run, docs/BUILD_PLAN.md Milestone 11) --
this ratio is OBSERVED; the absolute partition size is matched to a real
code default, not itself a measured partition characteristic.

A small, deterministic fraction of synthetic orphan rows is included on
purpose, so the anti-join queries do real matching work each run instead of
optimizing to a trivial empty-set fast path.

Usage: python3 benchmark_validate.py [iterations]
   or: BENCHMARK_ITERATIONS=200 python3 benchmark_validate.py
Prints one JSON line to stdout.
"""

from __future__ import annotations

import json
import os
import platform
import resource
import socket
import sys
import time

import duckdb

DEFAULT_ITERATIONS = 200
RELEASE_COUNT = 5000
CREDITS_PER_RELEASE_RATIO = 11.46  # observed, see module docstring


def _build_synthetic_tables(connection: duckdb.DuckDBPyConnection) -> None:
    credit_count = int(RELEASE_COUNT * CREDITS_PER_RELEASE_RATIO)
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE releases AS
        SELECT
            i AS release_id,
            'Synthetic Release ' || i AS title
        FROM range({RELEASE_COUNT}) AS t(i)
        """
    )
    # A deliberate, small, deterministic slice of credits reference a
    # release_id past the real range -- real orphan rows the anti-join must
    # actually find, not an empty set it can short-circuit on.
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE credits AS
        SELECT
            i AS credit_id,
            CASE WHEN i % 500 = 0 THEN {RELEASE_COUNT} + i ELSE i % {RELEASE_COUNT} END
                AS release_id,
            'release' AS credit_scope,
            (i % 4919) AS artist_id,
            (i % 3) = 0 AS is_linked
        FROM range({credit_count}) AS t(i)
        """
    )


def run_benchmark(iterations: int) -> dict[str, object]:
    connection = duckdb.connect(database=":memory:")
    _build_synthetic_tables(connection)

    start = time.perf_counter()
    checks_run = 0
    for _ in range(iterations):
        connection.execute("SELECT count(*) FROM releases").fetchone()
        connection.execute("SELECT count(DISTINCT release_id) FROM releases").fetchone()
        connection.execute(
            "SELECT count(*) FROM credits c ANTI JOIN releases r USING (release_id)"
        ).fetchone()
        connection.execute(
            "SELECT count(*) FROM credits WHERE is_linked AND (artist_id IS NULL OR artist_id <= 0)"
        ).fetchone()
        checks_run += 1
    elapsed = time.perf_counter() - start

    peak_rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    return {
        "hostname": socket.gethostname(),
        "architecture": platform.machine(),
        "cpu_count": os.cpu_count(),
        "iterations": iterations,
        "checks_run": checks_run,
        "elapsed_s": round(elapsed, 4),
        "checks_per_sec": (round(checks_run / elapsed, 1) if elapsed > 0 else None),
        "peak_rss_mb": round(peak_rss_kb / 1024, 2),
    }


def main() -> None:
    if len(sys.argv) > 1:
        iterations = int(sys.argv[1])
    else:
        iterations = int(os.environ.get("BENCHMARK_ITERATIONS", DEFAULT_ITERATIONS))
    result = run_benchmark(iterations)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
