#!/usr/bin/env python3
"""Standalone role-summary aggregation probe for cluster node comparison.

Deliberately NOT a scaled-down copy of real `role_text` data -- the real
distinct-value cardinality (3,345,564 distinct values across 220,015,758
real credit rows, max length 2,655 chars -- observed via a full-dataset
profiling pass, docs/BUILD_PLAN.md Milestone 11) doesn't linearly rescale to
a small partition in any way that would be a genuine measurement rather
than a guess. Instead this probe's synthetic vocabulary is PROJECTED from
that evidence's shape, not asserted as a measured distinct-count at this
size: a small common-role vocabulary (matching the real, well-known common
case) plus a long tail of generated near-unique strings, some deliberately
built out to the real observed maximum length, so the probe exercises both
the "many small groups" and "long string comparison/hash" cost shapes.

Usage: python3 benchmark_role_summary.py [iterations]
   or: BENCHMARK_ITERATIONS=200 python3 benchmark_role_summary.py
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
CREDIT_COUNT = 57300  # ~5,000 releases * observed ~11.46 credits/release
COMMON_ROLES = [
    "Guitar",
    "Vocals",
    "Producer",
    "Written-By",
    "Composed By",
    "Bass",
    "Drums",
    "Engineer",
    "Mixed By",
    "Mastered By",
    "Piano",
    "Saxophone",
    "Arranged By",
    "Photography By",
    "Design",
]
LONG_TAIL_COUNT = 400
MAX_OBSERVED_ROLE_LEN = 2655  # observed, docs/BUILD_PLAN.md Milestone 11
VOCAB_SIZE = len(COMMON_ROLES) + LONG_TAIL_COUNT


def _build_synthetic_table(connection: duckdb.DuckDBPyConnection) -> None:
    common_sql = ", ".join(f"'{role}'" for role in COMMON_ROLES)
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE role_vocab AS
        SELECT row_number() OVER () - 1 AS vocab_id, role_text FROM (
            SELECT unnest([{common_sql}]) AS role_text
            UNION ALL
            SELECT
                'Long Tail Role ' || i
                || repeat('x', {MAX_OBSERVED_ROLE_LEN} * (i % 5 = 0)::INT) AS role_text
            FROM range({LONG_TAIL_COUNT}) AS t(i)
        )
        """
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE credits AS
        SELECT i AS credit_id, v.role_text
        FROM range({CREDIT_COUNT}) AS t(i)
        JOIN role_vocab v ON v.vocab_id = (i % {VOCAB_SIZE})
        """
    )


def run_benchmark(iterations: int) -> dict[str, object]:
    connection = duckdb.connect(database=":memory:")
    _build_synthetic_table(connection)

    start = time.perf_counter()
    passes_run = 0
    for _ in range(iterations):
        connection.execute(
            "SELECT role_text, count(*) n FROM credits GROUP BY role_text ORDER BY n DESC"
        ).fetchall()
        connection.execute("SELECT count(DISTINCT role_text) FROM credits").fetchone()
        passes_run += 1
    elapsed = time.perf_counter() - start

    peak_rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    return {
        "hostname": socket.gethostname(),
        "architecture": platform.machine(),
        "cpu_count": os.cpu_count(),
        "iterations": iterations,
        "passes_run": passes_run,
        "vocab_size": VOCAB_SIZE,
        "elapsed_s": round(elapsed, 4),
        "passes_per_sec": (round(passes_run / elapsed, 1) if elapsed > 0 else None),
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
