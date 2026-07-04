#!/usr/bin/env python3
"""Enqueue challenge-evidence verification shards across the joined Pi
workers, via the jobs broker + RQ. This is a real production job (the first
one, per docs/DISCOGS_INGESTION.md's "challenge batches" hardware profile),
not a benchmark -- it re-verifies a published challenge.v2 artifact's
evidence against each Pi's own local one-hop cache (ADR 0025).

Mirrors scripts/cluster_benchmark_distributed.py's inventory-loading,
per-worker-queue, and result-collection patterns (see that file's own
comments for the "why per-worker queue, not one shared queue" rationale).

Prerequisites (not checked here beyond a clear failure -- each fails loudly
on its own if skipped): the jobs broker up (deploy-jobs-broker.sh), the
verification job deployed to each targeted Pi (deploy-verify-job.yml), and
each targeted Pi already holding a validated one-hop cache matching the
artifact's snapshot (ADR 0025 -- replicate-dataset-pi.yml).

Not meant to be invoked directly -- use
scripts/enqueue-verify-challenge.sh (or `make verify-challenge-distributed`),
which sources local/jobs-broker.env and sets JOBS_BROKER_URL before calling
this.

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

QUEUE_PREFIX = "verify-challenge"
JOB_TIMEOUT_S = 180
WAIT_TIMEOUT_S = 240.0


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"ABORT: set {name} (see scripts/enqueue-verify-challenge.sh).", file=sys.stderr)
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


def shard_path_ids(path_ids: list[str], shard_size: int) -> list[list[str]]:
    return [path_ids[i : i + shard_size] for i in range(0, len(path_ids), shard_size)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact",
        type=Path,
        default=REPO_ROOT / "apps" / "web" / "public" / "data" / "challenge.v2.json",
    )
    parser.add_argument("--shard-size", type=int, default=4)
    parser.add_argument("--workers", default="pi_workers", help="ansible inventory group to target")
    args = parser.parse_args()

    if not args.artifact.exists():
        print(f"ABORT: no artifact at {args.artifact}.", file=sys.stderr)
        raise SystemExit(1)
    artifact = json.loads(args.artifact.read_text())
    path_ids = [p["id"] for p in artifact["paths"]]
    if not path_ids:
        print(f"ABORT: {args.artifact} has no paths to verify.", file=sys.stderr)
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

    shards = shard_path_ids(path_ids, args.shard_size)
    print(f"==> {len(path_ids)} paths in {len(shards)} shard(s), across {len(workers)} worker(s).")

    enqueued: list[tuple[str, list[str], Job]] = []
    for index, shard in enumerate(shards):
        worker = workers[index % len(workers)]
        job = queues[worker].enqueue(
            "verify_challenge_job.verify_shard",
            "challenge.v2.json",
            shard,
            job_timeout=JOB_TIMEOUT_S,
        )
        enqueued.append((worker, shard, job))

    run_burst_workers(limit=args.workers)
    job_ids = [job.id for _, _, job in enqueued]
    finished_jobs = wait_for_jobs(redis_conn, job_ids)

    results = []
    all_failures: list[str] = []
    failed_job_ids: list[str] = []
    for (worker, shard, _), job in zip(enqueued, finished_jobs, strict=True):
        if job.is_failed:
            failed_job_ids.append(job.id)
        result = job.result if job.is_finished else None
        results.append({"worker": worker, "path_ids": shard, "result": result})
        if result:
            all_failures.extend(result.get("failures", []))

    record: dict[str, Any] = {
        "observed": True,
        "measured_at_utc": datetime.now(UTC).isoformat(),
        "artifact": str(args.artifact),
        "workers": workers,
        "shard_count": len(shards),
        "shards": results,
        "job_failures": failed_job_ids,
        "evidence_failures": all_failures,
        "ok": not failed_job_ids and not all_failures,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_path = OUTPUT_DIR / f"verify-challenge-{timestamp}.json"
    output_path.write_text(json.dumps(record, indent=2, default=str) + "\n")

    print(f"==> Wrote {output_path}.")
    if record["ok"]:
        print("==> PASS: every shard's evidence checks out.")
    else:
        print(
            f"==> FAIL: {len(failed_job_ids)} job failure(s), "
            f"{len(all_failures)} evidence failure(s)."
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
