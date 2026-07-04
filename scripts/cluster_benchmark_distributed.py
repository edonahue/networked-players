#!/usr/bin/env python3
"""Compare a workload's aggregate throughput fanned out across the joined
Pi workers (via the jobs broker + RQ) against the same total work run on a
single worker alone.

Supports five job "kinds" (--kind, default "parse"), one per benchmark
probe in infra/ansible/files/ -- the original synthetic XML-parse probe
(benchmark_parse.py) plus four probes modeling the canonical Pi job types
named in docs/DISCOGS_INGESTION.md's hardware table (checksummed partition
validation, role summaries, graph tests, challenge batches). Whichever
probe file(s) are needed must already be deployed to each worker's rq-jobs
directory (infra/ansible/playbooks/deploy-rq-benchmark-job.yml) and each
worker's venv must already have redis/rq installed
(infra/ansible/playbooks/equip-workers.yml).

Not meant to be invoked directly -- use scripts/cluster-benchmark-distributed.sh
(or `make cluster-benchmark-distributed`), which sources local/jobs-broker.env
and sets JOBS_BROKER_URL before calling this.

Results are written to local/benchmarks/ only -- never to a committed doc.
See docs/decisions/0018-benchmark-results-local-only.md and
docs/decisions/0019-cluster-benchmark-rq-job-broker.md.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from redis import Redis
from rq import Queue
from rq.job import Job

REPO_ROOT = Path(__file__).resolve().parent.parent
ANSIBLE_DIR = REPO_ROOT / "infra" / "ansible"
LOCAL_INVENTORY = ANSIBLE_DIR / "inventories" / "local" / "hosts.yml"
OUTPUT_DIR = REPO_ROOT / "local" / "benchmarks"

BASELINE_QUEUE = "cluster-benchmark-baseline"
DISTRIBUTED_QUEUE = "cluster-benchmark-distributed"
JOB_TIMEOUT_S = 580
WAIT_TIMEOUT_S = 600.0


@dataclass(frozen=True)
class JobKind:
    func: str
    default_total: int
    throughput_field: str
    dataset: str


JOB_KINDS: dict[str, JobKind] = {
    "parse": JobKind(
        func="benchmark_parse.run_benchmark",
        default_total=20000,
        throughput_field="releases_per_sec",
        dataset="embedded synthetic Discogs-release XML fixture (same as benchmark_parse.py)",
    ),
    "validate": JobKind(
        func="benchmark_validate.run_benchmark",
        default_total=200,
        throughput_field="checks_per_sec",
        dataset="in-memory DuckDB-generated synthetic partition (benchmark_validate.py)",
    ),
    "role-summary": JobKind(
        func="benchmark_role_summary.run_benchmark",
        default_total=200,
        throughput_field="passes_per_sec",
        dataset="in-memory DuckDB-generated synthetic credits table (benchmark_role_summary.py)",
    ),
    "graph-traversal": JobKind(
        func="benchmark_graph_challenge.run_benchmark_graph_traversal",
        default_total=500,
        throughput_field="queries_per_sec",
        dataset="in-memory synthetic artist-release adjacency graph (benchmark_graph_challenge.py)",
    ),
    "challenge-batch": JobKind(
        func="benchmark_graph_challenge.run_benchmark_challenge_batch",
        default_total=500,
        throughput_field="challenges_per_sec",
        dataset="in-memory synthetic artist-release adjacency graph (benchmark_graph_challenge.py)",
    ),
}


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"ABORT: set {name} (see scripts/cluster-benchmark-distributed.sh).", file=sys.stderr)
        raise SystemExit(1)
    return value


def load_workers() -> list[str]:
    # `pi_workers`, not the broader `workers` group (ADR 0022): every host
    # here needs the redis/rq venv equip-workers.yml builds, and that
    # playbook is deliberately scoped to `pi_workers` only -- a non-Pi
    # Swarm worker in `workers` has no such venv and would fail outright
    # when run-rq-burst-worker.yml tried to invoke a binary that was never
    # installed there.
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
    hosts = inventory.get("pi_workers", {}).get("hosts", [])
    if not hosts:
        print("ABORT: no hosts in the 'pi_workers' inventory group.", file=sys.stderr)
        raise SystemExit(1)
    return sorted(hosts)


def run_burst_workers(limit: str, queue_name: str) -> None:
    cmd = [
        str(ANSIBLE_DIR / "run-rq-burst-worker-local.sh"),
        "--limit",
        limit,
        "-e",
        f"rq_queue_name={queue_name}",
    ]
    subprocess.run(cmd, check=True)


def queue_name_for(prefix: str, host: str) -> str:
    return f"{prefix}-{host}"


def assert_queue_empty(queue: Queue, name: str) -> None:
    dirty = len(queue) or queue.started_job_registry.count or queue.failed_job_registry.count
    if dirty:
        print(
            f"ABORT: queue {name!r} is not empty (queued/running/failed jobs present). "
            "Drain it or restart the jobs broker before benchmarking.",
            file=sys.stderr,
        )
        raise SystemExit(1)


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
    failed = [job.id for job in jobs if job.is_failed]
    if failed:
        print(f"ABORT: job(s) failed: {failed}", file=sys.stderr)
        raise SystemExit(1)
    return jobs


def split_iterations(total: int, parts: int) -> list[int]:
    base, remainder = divmod(total, parts)
    chunks = [base] * parts
    chunks[0] += remainder
    return chunks


def job_span_seconds(job: Job) -> float | None:
    if job.started_at is None or job.ended_at is None:
        return None
    return (job.ended_at - job.started_at).total_seconds()


def render_markdown(record: dict[str, Any]) -> str:
    baseline = record["baseline"]
    distributed = record["distributed"]
    baseline_result = baseline["result"] or {}
    throughput_field = record["throughput_field"]
    lines = [
        f"# Cluster vs. single-node benchmark: {record['kind']} (local-only, not for publication)",
        "",
        f"Measured: {record['measured_at_utc']}",
        f"Method: {record['method']}",
        f"Dataset: {record['dataset']}",
        "",
        f"| Run | Node | Iterations | Job elapsed (s) | {throughput_field} | Peak RSS (MB) |",
        "| --- | --- | --- | --- | --- | --- |",
        (
            f"| baseline (single-node) | {baseline['worker']} | {baseline['iterations']} | "
            f"{baseline_result.get('elapsed_s', '?')} | "
            f"{baseline_result.get(throughput_field, '?')} | "
            f"{baseline_result.get('peak_rss_mb', '?')} |"
        ),
    ]
    for worker, chunk, result in zip(
        distributed["workers"], distributed["chunks"], distributed["per_job_results"], strict=True
    ):
        r = result or {}
        lines.append(
            f"| distributed | {worker} | {chunk} | {r.get('elapsed_s', '?')} | "
            f"{r.get(throughput_field, '?')} | {r.get('peak_rss_mb', '?')} |"
        )
    lines += [
        "",
        f"Baseline job span: {baseline['job_span_s']}s",
        f"Distributed aggregate job span: {distributed['aggregate_job_span_s']}s",
        f"Speedup (distributed vs. single-node baseline): {record['speedup']}x",
        "",
        "This file is local-only (see docs/decisions/0018-benchmark-results-local-only.md) "
        "-- never commit it.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--kind",
        choices=sorted(JOB_KINDS),
        default="parse",
        help="Which benchmark probe to run (default: parse, the original XML-parse probe)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=None,
        help="Defaults to the chosen --kind's own default_total if not set",
    )
    parser.add_argument(
        "--baseline-worker",
        help="Inventory hostname for the single-node baseline (default: first worker, sorted)",
    )
    args = parser.parse_args()
    job_kind = JOB_KINDS[args.kind]
    iterations = args.iterations if args.iterations is not None else job_kind.default_total

    jobs_broker_url = require_env("JOBS_BROKER_URL")
    redis_conn = Redis.from_url(jobs_broker_url)
    try:
        redis_conn.ping()
    except Exception as exc:
        print(f"ABORT: cannot reach the jobs broker at {jobs_broker_url}: {exc}", file=sys.stderr)
        print("        Start it with ./infra/swarm/deploy-jobs-broker.sh", file=sys.stderr)
        raise SystemExit(1) from exc

    workers = load_workers()
    baseline_worker = args.baseline_worker or workers[0]
    if baseline_worker not in workers:
        print(
            f"ABORT: {baseline_worker!r} is not in the workers inventory group ({workers}).",
            file=sys.stderr,
        )
        raise SystemExit(1)

    # Per-worker queues, not one shared queue: multiple burst workers pulling
    # from a single shared queue race for jobs with no guaranteed
    # one-job-per-host mapping (confirmed live: one Pi's burst worker drained
    # two of three enqueued chunks while another drained zero). Each
    # worker's queue holds exactly the chunk assigned to it, so
    # `workers[i]`/`chunks[i]`/`per_job_results[i]` are guaranteed to agree
    # by construction, not just by convention.
    baseline_queue_name = queue_name_for(BASELINE_QUEUE, baseline_worker)
    baseline_queue = Queue(baseline_queue_name, connection=redis_conn)
    assert_queue_empty(baseline_queue, baseline_queue_name)
    distributed_queues = {
        worker: Queue(queue_name_for(DISTRIBUTED_QUEUE, worker), connection=redis_conn)
        for worker in workers
    }
    for queue in distributed_queues.values():
        assert_queue_empty(queue, queue.name)

    print(f"==> Baseline: {iterations} iterations on {baseline_worker} alone.")
    baseline_enqueued = baseline_queue.enqueue(job_kind.func, iterations, job_timeout=JOB_TIMEOUT_S)
    run_burst_workers(limit=baseline_worker, queue_name=BASELINE_QUEUE)
    (baseline_job,) = wait_for_jobs(redis_conn, [baseline_enqueued.id])

    print(f"==> Distributed: {iterations} iterations split across {workers}.")
    chunks = split_iterations(iterations, len(workers))
    distributed_enqueued = [
        distributed_queues[worker].enqueue(job_kind.func, chunk, job_timeout=JOB_TIMEOUT_S)
        for worker, chunk in zip(workers, chunks, strict=True)
    ]
    run_burst_workers(limit="pi_workers", queue_name=DISTRIBUTED_QUEUE)
    distributed_jobs = wait_for_jobs(redis_conn, [job.id for job in distributed_enqueued])

    baseline_span = job_span_seconds(baseline_job)
    job_spans = [job_span_seconds(job) for job in distributed_jobs]
    started_ats = [job.started_at for job in distributed_jobs if job.started_at]
    ended_ats = [job.ended_at for job in distributed_jobs if job.ended_at]
    aggregate_span = (
        (max(ended_ats) - min(started_ats)).total_seconds() if started_ats and ended_ats else None
    )
    speedup = (
        round(baseline_span / aggregate_span, 2)
        if baseline_span and aggregate_span and aggregate_span > 0
        else None
    )

    record: dict[str, Any] = {
        "observed": True,
        "kind": args.kind,
        "measured_at_utc": datetime.now(UTC).isoformat(),
        "method": (
            f"infra/ansible/files/{job_kind.func.split('.')[0]}.py via RQ (redis/rq), "
            "fanned out with infra/ansible/playbooks/run-rq-burst-worker.yml"
        ),
        "dataset": job_kind.dataset,
        "throughput_field": job_kind.throughput_field,
        "iterations_total": iterations,
        "baseline": {
            "worker": baseline_worker,
            "iterations": iterations,
            "job_span_s": baseline_span,
            "result": baseline_job.result,
        },
        "distributed": {
            "workers": workers,
            "chunks": chunks,
            "job_spans_s": job_spans,
            "aggregate_job_span_s": aggregate_span,
            "per_job_results": [job.result for job in distributed_jobs],
        },
        "speedup": speedup,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_DIR / f"cluster-vs-single-node-{args.kind}.json"
    md_path = OUTPUT_DIR / f"cluster-vs-single-node-{args.kind}.md"
    json_path.write_text(json.dumps(record, indent=2, default=str) + "\n")
    md_path.write_text(render_markdown(record))

    print(f"==> Wrote {json_path} and {md_path}.")
    print(f"==> Speedup (distributed vs. single-node baseline): {speedup}x")


if __name__ == "__main__":
    main()
