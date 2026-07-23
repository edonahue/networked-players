#!/usr/bin/env python3
"""Enqueue a cohort-artifact validation check across every targeted Pi
worker (fanned out one job per worker, aggregated pass/fail), via the jobs
broker + RQ. Re-checks an already-produced connectivity.json or
playable-cohort-v1.json artifact -- no dataset, no CreditGraph, safe to run
at any time regardless of when the artifact was produced.

Unlike the other five enqueue_*_check.py scripts, the artifact here is a
per-invocation operator path with no fixed, known-in-advance location a
deploy playbook could have bundled ahead of time -- so this script stages
it (scripts/_artifact_staging.py: sha256, copy to every targeted worker
under a content-addressed filename, verify the remote checksum) before
enqueueing, and removes it afterward by default (pass --keep-staged to
retain it for debugging). Fan-out itself is real, not sharded: every
targeted worker independently re-validates its own staged copy (proving
each worker's environment produces the same result), not a split of one
job across workers -- unlike scripts/enqueue_verify_challenge.py, which
genuinely splits a batch of paths across workers and is unrelated to this
change. See scripts/_fleet_check.py for the shared per-worker-queue
enqueue/collect/aggregate logic this script shares with the other five
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

from _artifact_staging import stage_artifact, unstage_artifact, validate_local_artifact
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
        help="path to a connectivity.json or playable-cohort-v1.json on THIS machine -- "
        "staged onto every targeted worker before the check runs, never resolved on the "
        "worker's own filesystem directly",
    )
    parser.add_argument(
        "--keep-staged",
        action="store_true",
        help="skip cleanup after the check, for debugging (default: always remove the "
        "staged copy from every targeted worker afterward)",
    )
    args = parser.parse_args()

    validate_local_artifact(args.artifact)
    redis_conn = connect_to_broker(USAGE_HINT)
    workers = resolve_target_workers(args.workers, args.limit)

    print(f"==> Staging {args.artifact} onto {len(workers)} worker(s): {workers}.")
    staged_filename = stage_artifact(args.artifact, workers)

    try:
        print(f"==> Checking {staged_filename} ({args.kind}) across {len(workers)} worker(s).")
        per_worker = enqueue_and_collect(
            workers=workers,
            queue_prefix=QUEUE_PREFIX,
            job_function=JOB_FUNCTIONS[args.kind],
            job_args=(staged_filename,),
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
    finally:
        if args.keep_staged:
            print(f"==> Kept staged {staged_filename} on {workers} (--keep-staged).")
        else:
            unstage_artifact(staged_filename, workers)


if __name__ == "__main__":
    main()
