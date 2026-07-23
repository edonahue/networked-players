#!/usr/bin/env python3
"""Enqueue a cohort-artifact validation check across every targeted Pi
worker (fanned out one job per worker, aggregated pass/fail), via the jobs
broker + RQ. Re-checks an already-produced connectivity.json or
playable-cohort-v1.json artifact -- no dataset, no CreditGraph, safe to run
at any time regardless of when the artifact was produced.

Fan-out is real, not sharded: every targeted worker independently
re-validates its own deployed copy of the same artifact (proving each
worker's environment produces the same result), not a split of one job
across workers -- unlike scripts/enqueue_verify_challenge.py, which
genuinely splits a batch of paths across workers and stays untouched by
this change. See scripts/_fleet_check.py for the shared per-worker-queue
enqueue/collect/aggregate logic this script now shares with the other five
enqueue_*_check.py scripts. Pass --limit <hostname> to target a single
worker for debugging.

Prerequisites (not checked here beyond a clear failure -- each fails loudly
on its own if skipped): the jobs broker up (deploy-jobs-broker.sh), and the
check job deployed to each targeted Pi (deploy-cohort-check-job.yml).

Not meant to be invoked directly -- use scripts/enqueue-cohort-check.sh,
which sources local/jobs-broker.env and sets JOBS_BROKER_URL before calling
this (no `make` target wraps it today, unlike the other enqueue_*_check.py
scripts).

Results are written to local/jobs/ only -- never to a committed doc. See
docs/decisions/0018-benchmark-results-local-only.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

from _fleet_check import (
    build_arg_parser,
    connect_to_broker,
    enqueue_and_collect,
    resolve_target_workers,
    write_report,
)
from rq import Queue

QUEUE_PREFIX = "cohort-check"
JOB_TIMEOUT_S = 60
JOB_FUNCTIONS = {
    "connectivity": "cohort_artifact_check_job.check_connectivity",
    "playable-cohort": "cohort_artifact_check_job.check_playable_cohort",
}
USAGE_HINT = "scripts/enqueue-cohort-check.sh"


def main() -> None:
    parser = build_arg_parser(__doc__)
    parser.add_argument("--kind", choices=sorted(JOB_FUNCTIONS), required=True)
    parser.add_argument(
        "--artifact",
        type=Path,
        required=True,
        help="path to connectivity.json or playable-cohort-v1.json, resolved relative to "
        "each targeted worker's own filesystem, not this machine's",
    )
    args = parser.parse_args()

    redis_conn = connect_to_broker(USAGE_HINT)
    workers = resolve_target_workers(args.workers, args.limit)

    print(f"==> Checking {args.artifact} ({args.kind}) across {len(workers)} worker(s): {workers}.")
    per_worker = enqueue_and_collect(
        workers=workers,
        queue_prefix=QUEUE_PREFIX,
        job_function=JOB_FUNCTIONS[args.kind],
        job_args=(str(args.artifact),),
        job_timeout=JOB_TIMEOUT_S,
        queue_factory=lambda name: Queue(name, connection=redis_conn),
    )
    output_path = write_report(
        prefix=QUEUE_PREFIX,
        extra={"kind": args.kind, "artifact": str(args.artifact)},
        per_worker=per_worker,
    )

    print(f"==> Wrote {output_path}.")
    if all(v["ok"] for v in per_worker.values()):
        print(f"==> PASS: artifact is valid on all {len(per_worker)} worker(s).")
    else:
        failing = {host: v for host, v in per_worker.items() if not v["ok"]}
        print(f"==> FAIL on {sorted(failing)}:")
        for host, v in failing.items():
            failures = v["result"].get("failures", []) if v["result"] else None
            print(f"    {host}: job_failed={v['job_failed']}, failures={failures}")
        sys.exit(1)


if __name__ == "__main__":
    main()
