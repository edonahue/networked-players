#!/usr/bin/env python3
"""Enqueue a public-album-catalog validation check across every targeted Pi
worker (fanned out one job per worker, aggregated pass/fail), via the jobs
broker + RQ. Re-checks the already-published albums.v1.json artifact
deployed alongside the job body by deploy-catalog-check-job.yml -- no
dataset, no CreditGraph, safe to run at any time.

Fan-out is real, not sharded: every targeted worker independently
re-validates its own deployed copy of the same artifact (proving each
worker's environment produces the same result), not a split of one job
across workers. See scripts/_fleet_check.py for the shared per-worker-queue
enqueue/collect/aggregate logic every enqueue_*_check.py script uses. Pass
--limit <hostname> to target a single worker for debugging.

Prerequisites (not checked here beyond a clear failure -- each fails loudly
on its own if skipped): the jobs broker up (deploy-jobs-broker.sh), and the
check job + artifact deployed to each targeted Pi
(deploy-catalog-check-job.yml).

Not meant to be invoked directly -- use scripts/enqueue-catalog-check.sh
(or `make catalog-check-distributed`), which sources local/jobs-broker.env
and sets JOBS_BROKER_URL before calling this.

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

QUEUE_PREFIX = "catalog-check"
JOB_TIMEOUT_S = 60
JOB_FUNCTION = "catalog_check_job.check_catalog"
# Filename only: deploy-catalog-check-job.yml copies the artifact into the
# same persistent rq_jobs_dir as the job body itself, and catalog_check_job.py
# resolves relative paths against that directory (see its _resolve()).
CATALOG_FILENAME = "albums.v1.json"
USAGE_HINT = "scripts/enqueue-catalog-check.sh"


def main() -> None:
    parser = build_arg_parser(__doc__)
    args = parser.parse_args()

    redis_conn = connect_to_broker(USAGE_HINT)
    workers = resolve_target_workers(args.workers, args.limit)

    print(f"==> Checking {CATALOG_FILENAME} across {len(workers)} worker(s): {workers}.")
    per_worker = enqueue_and_collect(
        workers=workers,
        queue_prefix=QUEUE_PREFIX,
        job_function=JOB_FUNCTION,
        job_args=(CATALOG_FILENAME,),
        job_timeout=JOB_TIMEOUT_S,
        queue_factory=lambda name: Queue(name, connection=redis_conn),
    )
    output_path = write_report(
        prefix=QUEUE_PREFIX,
        extra={"catalog_artifact": CATALOG_FILENAME},
        per_worker=per_worker,
    )

    print(f"==> Wrote {output_path}.")
    if all(v["ok"] for v in per_worker.values()):
        print(f"==> PASS: public album catalog is valid on all {len(per_worker)} worker(s).")
    else:
        failing = {host: v for host, v in per_worker.items() if not v["ok"]}
        print(f"==> FAIL on {sorted(failing)}:")
        for host, v in failing.items():
            failures = v["result"].get("failures", []) if v["result"] else None
            print(f"    {host}: job_failed={v['job_failed']}, failures={failures}")
        sys.exit(1)


if __name__ == "__main__":
    main()
