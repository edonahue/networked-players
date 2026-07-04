#!/usr/bin/env python3
"""Standalone graph-traversal and challenge-batch probes for cluster node
comparison.

Deliberately NOT packages/graph-core (which has no real implementation yet
-- see its README, "planned responsibility" only) and NOT packages/catalog's
demo_challenge.py (API-based, and importing packages/catalog would drag
lxml/pyarrow onto a Pi worker). This probe builds its own small, synthetic
artist-release bipartite adjacency structure, stdlib-only -- no networkx: no
measured need for it per AGENTS.md, and packages/graph-core/README.md only
asks for NetworkX-style fixtures as a correctness oracle, not a runtime
dependency anywhere, least of all on a 1GB Pi.

Sizing: 5,000 releases (matching packages/catalog's real chunk_releases
default) at ~11 credits/release (rounded from the observed real ~11.46
ratio, docs/BUILD_PLAN.md Milestone 11), projected into a one-hop-frontier
shaped graph per docs/DISCOGS_INGESTION.md's "One-hop construction" steps.
This is a PROJECTED size, not a measured real frontier size -- one-hop
expansion itself is not yet implemented (docs/BUILD_PLAN.md).

Two entry points, both run once per invocation (not internally repeated --
the query_count/batch_count argument already provides the "how much work"
knob, matching a real bounded-partition job's shape more closely than a
tight repeat-loop over a tiny fixture would):

  run_benchmark_graph_traversal(query_count) -- BFS/shortest-path over the
    synthetic artist-artist adjacency. Each edge carries the release_id
    that justifies it, mirroring docs/ARCHITECTURE.md's "Graph model"
    evidence contract (a path retains the release that justifies each
    connection).
  run_benchmark_challenge_batch(batch_count) -- reuses the same fixture,
    finds a path then serializes it, mirroring demo_challenge.py's real
    "find path -> curate -> emit challenge.v1-shaped JSON" shape.

Usage: python3 benchmark_graph_challenge.py traversal [query_count]
       python3 benchmark_graph_challenge.py challenge [batch_count]
Prints one JSON line to stdout.
"""

from __future__ import annotations

import json
import os
import platform
import random
import resource
import socket
import sys
import time
from collections import deque

RELEASE_COUNT = 5000
CREDITS_PER_RELEASE = 11  # rounded from the observed ~11.46 ratio, see module docstring
ARTIST_POOL_SIZE = 4000  # projected -- see module docstring
DEFAULT_QUERY_COUNT = 500
DEFAULT_BATCH_COUNT = 500
FIXTURE_SEED = 20260601  # deterministic, reproducible fixture construction


def _build_synthetic_graph() -> tuple[dict[int, dict[int, int]], dict[int, list[int]]]:
    """Returns (adjacency, release_artists).

    adjacency[artist_a][artist_b] = release_id that justifies the edge
    (evidence-preserving, per docs/ARCHITECTURE.md's graph model).
    release_artists[release_id] = linked artist_ids credited on it.
    """
    rng = random.Random(FIXTURE_SEED)
    adjacency: dict[int, dict[int, int]] = {}
    release_artists: dict[int, list[int]] = {}

    for release_id in range(RELEASE_COUNT):
        credited = [rng.randrange(ARTIST_POOL_SIZE) for _ in range(CREDITS_PER_RELEASE)]
        linked = sorted(set(credited))  # a real release rarely repeats a credited artist
        release_artists[release_id] = linked
        for i, artist_a in enumerate(linked):
            for artist_b in linked[i + 1 :]:
                adjacency.setdefault(artist_a, {})[artist_b] = release_id
                adjacency.setdefault(artist_b, {})[artist_a] = release_id

    return adjacency, release_artists


def _shortest_path(adjacency: dict[int, dict[int, int]], start: int, goal: int) -> list[int] | None:
    if start == goal:
        return [start]
    visited = {start}
    queue: deque[list[int]] = deque([[start]])
    while queue:
        path = queue.popleft()
        node = path[-1]
        for neighbor in adjacency.get(node, {}):
            if neighbor in visited:
                continue
            new_path = [*path, neighbor]
            if neighbor == goal:
                return new_path
            visited.add(neighbor)
            queue.append(new_path)
    return None


def run_benchmark_graph_traversal(query_count: int) -> dict[str, object]:
    build_start = time.perf_counter()
    adjacency, _ = _build_synthetic_graph()
    build_elapsed = time.perf_counter() - build_start

    rng = random.Random(42)
    start = time.perf_counter()
    paths_found = 0
    for _ in range(query_count):
        a, b = rng.randrange(ARTIST_POOL_SIZE), rng.randrange(ARTIST_POOL_SIZE)
        if _shortest_path(adjacency, a, b) is not None:
            paths_found += 1
    elapsed = time.perf_counter() - start

    peak_rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    return {
        "hostname": socket.gethostname(),
        "architecture": platform.machine(),
        "cpu_count": os.cpu_count(),
        "graph_build_elapsed_s": round(build_elapsed, 4),
        "query_count": query_count,
        "paths_found": paths_found,
        "elapsed_s": round(elapsed, 4),
        "queries_per_sec": round(query_count / elapsed, 1) if elapsed > 0 else None,
        "peak_rss_mb": round(peak_rss_kb / 1024, 2),
    }


def run_benchmark_challenge_batch(batch_count: int) -> dict[str, object]:
    build_start = time.perf_counter()
    adjacency, release_artists = _build_synthetic_graph()
    build_elapsed = time.perf_counter() - build_start

    rng = random.Random(99)
    start = time.perf_counter()
    challenges_emitted = 0
    total_json_bytes = 0
    for _ in range(batch_count):
        a, b = rng.randrange(ARTIST_POOL_SIZE), rng.randrange(ARTIST_POOL_SIZE)
        path = _shortest_path(adjacency, a, b)
        if path is None or len(path) < 2:
            continue
        hops = []
        for i in range(len(path) - 1):
            release_id = adjacency[path[i]][path[i + 1]]
            hops.append(
                {
                    "from_artist_id": path[i],
                    "to_artist_id": path[i + 1],
                    "release_id": release_id,
                    "evidence_artist_ids": release_artists[release_id],
                }
            )
        challenge = {
            "schema": "challenge.v1",
            "from_artist_id": a,
            "to_artist_id": b,
            "hops": hops,
        }
        total_json_bytes += len(json.dumps(challenge, sort_keys=True))
        challenges_emitted += 1
    elapsed = time.perf_counter() - start

    peak_rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    return {
        "hostname": socket.gethostname(),
        "architecture": platform.machine(),
        "cpu_count": os.cpu_count(),
        "graph_build_elapsed_s": round(build_elapsed, 4),
        "batch_count": batch_count,
        "challenges_emitted": challenges_emitted,
        "total_json_bytes": total_json_bytes,
        "elapsed_s": round(elapsed, 4),
        "challenges_per_sec": (round(challenges_emitted / elapsed, 1) if elapsed > 0 else None),
        "peak_rss_mb": round(peak_rss_kb / 1024, 2),
    }


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "traversal"
    if mode == "traversal":
        count = (
            int(sys.argv[2])
            if len(sys.argv) > 2
            else int(os.environ.get("BENCHMARK_QUERY_COUNT", DEFAULT_QUERY_COUNT))
        )
        result = run_benchmark_graph_traversal(count)
    elif mode == "challenge":
        count = (
            int(sys.argv[2])
            if len(sys.argv) > 2
            else int(os.environ.get("BENCHMARK_BATCH_COUNT", DEFAULT_BATCH_COUNT))
        )
        result = run_benchmark_challenge_batch(count)
    else:
        print(f"Usage: {sys.argv[0]} {{traversal|challenge}} [count]", file=sys.stderr)
        raise SystemExit(1)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
