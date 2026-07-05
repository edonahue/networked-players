#!/usr/bin/env python3
"""Enqueue a single cohort-artifact validation check across the joined Pi
workers, via the jobs broker + RQ. Re-checks an already-produced
connectivity.json or playable-cohort-v1.json artifact -- no dataset, no
CreditGraph, safe to run at any time regardless of when the artifact was
produced.

Mirrors scripts/enqueue_verify_challenge.py's broker-connect,
per-worker-queue (one queue per host, never one shared queue -- so results
stay attributable), burst-worker-launch, and wait-and-collect structure; see
that file's own comments for the "why per-worker queue" rationale. This
script only ever enqueues one job (to one worker), since a single-artifact
check has no natural sharding dimension the way path-batch verification
does.

Prerequisites (not checked here beyond a clear failure -- each fails loudly
on its own if skipped): the jobs broker up (deploy-jobs-broker.sh), and the
check job deployed to each targeted Pi (deploy-cohort-check-job.yml).

Not meant to be invoked directly -- use scripts/enqueue-cohort-check.sh
(or `make check-cohort-artifact`), which sources local/jobs-broker.env and
sets JOBS_BROKER_URL before calling this.

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

QUEUE_PREFIX = "cohort-check"
JOB_TIMEOUT_S = 60
WAIT_TIMEOUT_S = 120.0
JOB_FUNCTIONS = {
    "connectivity": "cohort_artifact_check_job.check_connectivity",
    "playable-cohort": "cohort_artifact_check_job.check_playable_cohort",
}


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"ABORT: set {name} (see scripts/enqueue-cohort-check.sh).", file=sys.stderr)
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


def wait_for_job(redis_conn: Redis, job_id: str) -> Job:
    job = Job.fetch(job_id, connection=redis_conn)
    deadline = time.monotonic() + WAIT_TIMEOUT_S
    while time.monotonic() < deadline:
        job.refresh()
        if job.is_finished or job.is_failed:
            return job
        time.sleep(0.5)
    print(f"ABORT: job {job_id} did not finish within {WAIT_TIMEOUT_S}s.", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=sorted(JOB_FUNCTIONS), required=True)
    parser.add_argument(
        "--artifact",
        type=Path,
        required=True,
        help="path to connectivity.json or playable-cohort-v1.json, resolved relative to "
        "each targeted worker's own filesystem, not this machine's",
    )
    parser.add_argument("--workers", default="pi_workers", help="ansible inventory group to target")
    args = parser.parse_args()

    jobs_broker_url = require_env("JOBS_BROKER_URL")
    redis_conn = Redis.from_url(jobs_broker_url)
    try:
        redis_conn.ping()
    except Exception as exc:
        print(f"ABORT: cannot reach the jobs broker at {jobs_broker_url}: {exc}", file=sys.stderr)
        print("        Start it with ./infra/swarm/deploy-jobs-broker.sh", file=sys.stderr)
        raise SystemExit(1) from exc

    workers = load_workers(args.workers)
    worker = workers[0]
    queue = Queue(queue_name_for(QUEUE_PREFIX, worker), connection=redis_conn)
    assert_queue_empty(queue, queue.name)

    print(f"==> Checking {args.artifact} ({args.kind}) via {worker}.")
    job = queue.enqueue(
        JOB_FUNCTIONS[args.kind],
        str(args.artifact),
        job_timeout=JOB_TIMEOUT_S,
    )

    run_burst_workers(limit=args.workers)
    finished_job = wait_for_job(redis_conn, job.id)

    result = finished_job.result if finished_job.is_finished else None
    record: dict[str, Any] = {
        "observed": True,
        "measured_at_utc": datetime.now(UTC).isoformat(),
        "kind": args.kind,
        "artifact": str(args.artifact),
        "worker": worker,
        "job_failed": finished_job.is_failed,
        "result": result,
        "ok": (not finished_job.is_failed) and bool(result) and result.get("valid", False),
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_path = OUTPUT_DIR / f"cohort-check-{timestamp}.json"
    output_path.write_text(json.dumps(record, indent=2, default=str) + "\n")

    print(f"==> Wrote {output_path}.")
    if record["ok"]:
        print("==> PASS: artifact is valid.")
    else:
        failures = result.get("failures", []) if result else []
        print(f"==> FAIL: job_failed={finished_job.is_failed}, failures={failures}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
