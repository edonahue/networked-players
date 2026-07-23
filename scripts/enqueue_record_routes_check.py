#!/usr/bin/env python3
"""Enqueue a Record Routes artifact validation check across every targeted
Pi worker (fanned out one job per worker, aggregated pass/fail), via the
jobs broker + RQ. Re-checks the already-published
routes-universe.v1.json/routes-rounds.v1.json pair deployed alongside the
job body by deploy-record-routes-check-job.yml -- no dataset, no
CreditGraph, safe to run at any time regardless of when the pool was
generated.

Fan-out is real, not sharded: every targeted worker independently
re-validates its own deployed copy of the same artifact pair (proving each
worker's environment produces the same result), not a split of one job
across workers. See scripts/_fleet_check.py for the shared per-worker-queue
enqueue/collect/aggregate logic every enqueue_*_check.py script uses. Pass
--limit <hostname> to target a single worker for debugging.

Prerequisites (not checked here beyond a clear failure -- each fails loudly
on its own if skipped): the jobs broker up (deploy-jobs-broker.sh), and the
check job + artifacts deployed to each targeted Pi
(deploy-record-routes-check-job.yml).

Not meant to be invoked directly -- use scripts/enqueue-record-routes-check.sh
(or `make record-routes-check-distributed`), which sources
local/jobs-broker.env and sets JOBS_BROKER_URL before calling this.

Results are written to local/jobs/ only -- never to a committed doc. See
docs/decisions/0018-benchmark-results-local-only.md.
"""

from __future__ import annotations

import sys

from _fleet_check import (
    build_arg_parser,
    connect_to_broker,
    enqueue_and_collect,
    resolve_target_workers,
    write_report,
)
from rq import Queue

QUEUE_PREFIX = "record-routes-check"
JOB_TIMEOUT_S = 60
JOB_FUNCTION = "record_routes_check_job.check_record_routes"
# Filenames only: deploy-record-routes-check-job.yml copies both artifacts
# into the same persistent rq_jobs_dir as the job body itself, and
# record_routes_check_job.py resolves relative paths against that directory
# (see its _resolve()).
UNIVERSE_FILENAME = "routes-universe.v1.json"
ROUNDS_FILENAME = "routes-rounds.v1.json"
USAGE_HINT = "scripts/enqueue-record-routes-check.sh"


def main() -> None:
    parser = build_arg_parser(__doc__)
    args = parser.parse_args()

    redis_conn = connect_to_broker(USAGE_HINT)
    workers = resolve_target_workers(args.workers, args.limit)

    print(
        f"==> Checking {UNIVERSE_FILENAME}/{ROUNDS_FILENAME} across "
        f"{len(workers)} worker(s): {workers}."
    )
    per_worker = enqueue_and_collect(
        workers=workers,
        queue_prefix=QUEUE_PREFIX,
        job_function=JOB_FUNCTION,
        job_args=(UNIVERSE_FILENAME, ROUNDS_FILENAME),
        job_timeout=JOB_TIMEOUT_S,
        queue_factory=lambda name: Queue(name, connection=redis_conn),
    )
    output_path = write_report(
        prefix=QUEUE_PREFIX,
        extra={"universe_artifact": UNIVERSE_FILENAME, "rounds_artifact": ROUNDS_FILENAME},
        per_worker=per_worker,
    )

    print(f"==> Wrote {output_path}.")
    if all(v["ok"] for v in per_worker.values()):
        print(f"==> PASS: Record Routes pool is valid on all {len(per_worker)} worker(s).")
    else:
        failing = {host: v for host, v in per_worker.items() if not v["ok"]}
        print(f"==> FAIL on {sorted(failing)}:")
        for host, v in failing.items():
            failures = v["result"].get("failures", []) if v["result"] else None
            print(f"    {host}: job_failed={v['job_failed']}, failures={failures}")
        sys.exit(1)


if __name__ == "__main__":
    main()
