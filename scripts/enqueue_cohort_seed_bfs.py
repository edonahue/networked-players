#!/usr/bin/env python3
"""Enqueue cohort seed-BFS chunks across joined workers, via the jobs broker
+ RQ. See ADR 0032 for why the dispatch unit is a chunk of unique seed
artists (not individual neighbor lookups) and why this mirrors
scripts/enqueue_verify_challenge.py's shape almost exactly.

Mirrors scripts/cluster_benchmark_distributed.py's inventory-loading,
per-worker-queue, and result-collection patterns (see that file's own
comments for the "why per-worker queue, not one shared queue" rationale).

Prerequisites (not checked here beyond a clear failure -- each fails loudly
on its own if skipped): the jobs broker up (deploy-jobs-broker.sh), the
cohort seed-BFS job deployed to each targeted worker
(deploy-cohort-seed-bfs-job.yml), and each targeted worker already holding a
validated one-hop cache matching --snapshot-date (ADR 0025 --
replicate-dataset-pi.yml / make replicate-x86).

Not meant to be invoked directly against a real fleet without reading ADR
0032's "Consequences" section first -- real fleet execution and throughput
have not been measured or verified from a coding session; this script makes
that explicit rather than assuming success.

Results are written to local/jobs/ only -- never to a committed doc. See
docs/decisions/0018-benchmark-results-local-only.md.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from redis import Redis
from rq import Queue
from rq.job import Job

REPO_ROOT = Path(__file__).resolve().parent.parent
ANSIBLE_DIR = REPO_ROOT / "infra" / "ansible"
LOCAL_INVENTORY = ANSIBLE_DIR / "inventories" / "local" / "hosts.yml"
OUTPUT_DIR = REPO_ROOT / "local" / "jobs"

QUEUE_PREFIX = "cohort-seed-bfs"
JOB_TIMEOUT_S = 180
WAIT_TIMEOUT_S = 240.0


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"ABORT: set {name} (see scripts/enqueue-cohort-seed-bfs.sh).", file=sys.stderr)
        raise SystemExit(1)
    return value


def load_workers(group: str) -> list[str]:
    if not LOCAL_INVENTORY.exists():
        print(f"ABORT: no local inventory at {LOCAL_INVENTORY}.", file=sys.stderr)
        print(
            "        cp -r infra/ansible/inventories/example infra/ansible/inventories/local",
            file=sys.stderr,
        )
        raise SystemExit(1)
    result = subprocess.run(
        ["ansible-inventory", "-i", str(LOCAL_INVENTORY), "--list"],
        capture_output=True,
        text=True,
        check=True,
    )
    inventory = json.loads(result.stdout)
    hosts = inventory.get(group, {}).get("hosts", [])
    if not hosts:
        print(f"ABORT: no hosts in the {group!r} inventory group.", file=sys.stderr)
        raise SystemExit(1)
    return sorted(hosts)


def queue_name_for(prefix: str, host: str) -> str:
    return f"{prefix}-{host}"


def assert_queue_empty(queue: Queue, name: str) -> None:
    dirty = len(queue) or queue.started_job_registry.count or queue.failed_job_registry.count
    if dirty:
        print(
            f"ABORT: queue {name!r} is not empty (queued/running/failed jobs present). "
            "Drain it or restart the jobs broker first.",
            file=sys.stderr,
        )
        raise SystemExit(1)


def run_burst_workers(limit: str) -> None:
    cmd = [
        str(ANSIBLE_DIR / "run-rq-burst-worker-local.sh"),
        "--limit",
        limit,
        "-e",
        f"rq_queue_name={QUEUE_PREFIX}",
    ]
    subprocess.run(cmd, check=True)


def wait_for_jobs(redis_conn: Redis, job_ids: list[str]) -> list[Job]:
    jobs = [Job.fetch(job_id, connection=redis_conn) for job_id in job_ids]
    deadline = time.monotonic() + WAIT_TIMEOUT_S
    pending = {job.id for job in jobs}
    while pending and time.monotonic() < deadline:
        for job in jobs:
            if job.id in pending:
                job.refresh()
                if job.is_finished or job.is_failed:
                    pending.discard(job.id)
        if pending:
            time.sleep(0.5)
    if pending:
        print(f"ABORT: job(s) did not finish within {WAIT_TIMEOUT_S}s: {pending}", file=sys.stderr)
        raise SystemExit(1)
    return jobs


def shard_artist_ids(artist_ids: list[int], shard_size: int) -> list[list[int]]:
    return [artist_ids[i : i + shard_size] for i in range(0, len(artist_ids), shard_size)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--resolved",
        type=Path,
        required=True,
        help="album-cohort-resolved-v1.json -- its resolved[].artist_id values are the "
        "unique seed artists to dispatch",
    )
    parser.add_argument("--snapshot-date", required=True)
    parser.add_argument("--max-hops", type=int, default=3)
    parser.add_argument("--max-frontier-expansion", type=int, default=300)
    parser.add_argument("--shard-size", type=int, default=4)
    parser.add_argument("--workers", default="workers", help="ansible inventory group to target")
    args = parser.parse_args()

    if not args.resolved.exists():
        print(f"ABORT: no resolved-cohort artifact at {args.resolved}.", file=sys.stderr)
        raise SystemExit(1)
    resolved = json.loads(args.resolved.read_text())
    artist_ids = sorted({album["artist_id"] for album in resolved.get("resolved", [])})
    if not artist_ids:
        print(f"ABORT: {args.resolved} has no resolved albums to dispatch.", file=sys.stderr)
        raise SystemExit(1)

    jobs_broker_url = require_env("JOBS_BROKER_URL")
    redis_conn = Redis.from_url(jobs_broker_url)
    try:
        redis_conn.ping()
    except Exception as exc:
        print(f"ABORT: cannot reach the jobs broker at {jobs_broker_url}: {exc}", file=sys.stderr)
        print("        Start it with ./infra/swarm/deploy-jobs-broker.sh", file=sys.stderr)
        raise SystemExit(1) from exc

    workers = load_workers(args.workers)
    queues = {
        worker: Queue(queue_name_for(QUEUE_PREFIX, worker), connection=redis_conn)
        for worker in workers
    }
    for queue in queues.values():
        assert_queue_empty(queue, queue.name)

    shards = shard_artist_ids(artist_ids, args.shard_size)
    print(
        f"==> {len(artist_ids)} seed artists in {len(shards)} shard(s), "
        f"across {len(workers)} worker(s)."
    )

    enqueued: list[tuple[str, list[int], Job]] = []
    for index, shard in enumerate(shards):
        worker = workers[index % len(workers)]
        job = queues[worker].enqueue(
            "cohort_seed_bfs_job.run_seed_bfs_chunk",
            shard,
            args.max_hops,
            args.max_frontier_expansion,
            args.snapshot_date,
            job_timeout=JOB_TIMEOUT_S,
        )
        enqueued.append((worker, shard, job))

    run_burst_workers(limit=args.workers)
    job_ids = [job.id for _, _, job in enqueued]
    finished_jobs = wait_for_jobs(redis_conn, job_ids)

    per_seed_results: dict[str, Any] = {}
    failed_job_ids: list[str] = []
    shard_summaries = []
    for (worker, shard, _), job in zip(enqueued, finished_jobs, strict=True):
        if job.is_failed:
            failed_job_ids.append(job.id)
        result = job.result if job.is_finished else None
        shard_summaries.append({"worker": worker, "seed_artist_ids": shard, "result": result})
        if result:
            per_seed_results.update(result)

    timeout_seeds = [seed for seed, r in per_seed_results.items() if r.get("status") == "timeout"]

    record: dict[str, Any] = {
        "observed": True,
        "measured_at_utc": datetime.now(UTC).isoformat(),
        "resolved_artifact": str(args.resolved),
        "snapshot_date": args.snapshot_date,
        "workers": workers,
        "shard_count": len(shards),
        "shards": shard_summaries,
        "job_failures": failed_job_ids,
        "timeout_seeds": timeout_seeds,
        "per_seed_results": per_seed_results,
        "ok": not failed_job_ids and len(per_seed_results) == len(artist_ids),
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_path = OUTPUT_DIR / f"cohort-seed-bfs-{timestamp}.json"
    output_path.write_text(json.dumps(record, indent=2, default=str) + "\n")

    print(f"==> Wrote {output_path}.")
    if record["ok"]:
        print(f"==> PASS: all {len(artist_ids)} seed artists resolved.")
    else:
        print(
            f"==> FAIL: {len(failed_job_ids)} job failure(s), "
            f"{len(per_seed_results)}/{len(artist_ids)} seeds returned."
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
