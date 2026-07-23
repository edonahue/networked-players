"""Shared per-worker-queue fan-out helpers for every scripts/enqueue_*_check.py
script (record_routes, daily_manifest, album_art, catalog, connection_rounds).

Each script enqueues the SAME artifact check independently onto every
targeted worker's own queue ("<prefix>-<hostname>", never one shared queue --
see infra/ansible/playbooks/run-rq-burst-worker.yml's own comment for the
real bug a shared queue caused), launches a burst worker only on the hosts
that received a job this run, waits for every job, and reports one result
per worker plus an aggregate that passes only if every worker's result does.

This is real redundant fan-out -- proving each worker's own deployed copy of
the artifact + job body independently validates -- not sharding. A
single-artifact-pair check has no natural sharding dimension, so every
targeted worker runs the exact same job (unlike scripts/enqueue_verify_challenge.py,
which genuinely splits a batch of paths across workers).

`enqueue_and_collect`'s `queue_factory`/`launch_burst_workers` are injectable
so scripts/tests/test_fleet_check.py can prove the aggregation semantics
(all-pass, any-one-fails, burst workers limited to targeted hosts) with fake
in-memory queues/jobs -- no real Redis, no real Pi fleet.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from redis import Redis

REPO_ROOT = Path(__file__).resolve().parent.parent
ANSIBLE_DIR = REPO_ROOT / "infra" / "ansible"
LOCAL_INVENTORY = ANSIBLE_DIR / "inventories" / "local" / "hosts.yml"
OUTPUT_DIR = REPO_ROOT / "local" / "jobs"

WAIT_TIMEOUT_S = 120.0
POLL_INTERVAL_S = 0.5


class JobLike(Protocol):
    id: str

    def refresh(self) -> None: ...
    @property
    def is_finished(self) -> bool: ...
    @property
    def is_failed(self) -> bool: ...
    @property
    def result(self) -> Any: ...


class QueueLike(Protocol):
    name: str

    def __len__(self) -> int: ...
    @property
    def started_job_registry(self) -> Any: ...
    @property
    def failed_job_registry(self) -> Any: ...
    def enqueue(self, job_function: str, *args: Any, job_timeout: int) -> JobLike: ...


def require_env(name: str, *, usage_hint: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"ABORT: set {name} (see {usage_hint}).", file=sys.stderr)
        raise SystemExit(1)
    return value


def connect_to_broker(usage_hint: str) -> Redis:
    jobs_broker_url = require_env("JOBS_BROKER_URL", usage_hint=usage_hint)
    redis_conn = Redis.from_url(jobs_broker_url)
    try:
        redis_conn.ping()
    except Exception as exc:
        print(f"ABORT: cannot reach the jobs broker at {jobs_broker_url}: {exc}", file=sys.stderr)
        print("        Start it with ./infra/swarm/deploy-jobs-broker.sh", file=sys.stderr)
        raise SystemExit(1) from exc
    return redis_conn


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


def build_arg_parser(description: str | None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--workers", default="pi_workers", help="ansible inventory group to target")
    parser.add_argument(
        "--limit",
        help="debug: target only this single worker hostname instead of the whole --workers group",
    )
    return parser


def resolve_target_workers(group: str, limit: str | None) -> list[str]:
    workers = load_workers(group)
    if limit is None:
        return workers
    if limit not in workers:
        print(
            f"ABORT: --limit {limit!r} is not in the {group!r} inventory group ({workers}).",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return [limit]


def queue_name_for(prefix: str, host: str) -> str:
    return f"{prefix}-{host}"


def assert_queues_empty(queues: dict[str, QueueLike]) -> None:
    for host, queue in queues.items():
        dirty = len(queue) or queue.started_job_registry.count or queue.failed_job_registry.count
        if dirty:
            print(
                f"ABORT: queue {queue.name!r} (worker {host!r}) is not empty "
                "(queued/running/failed jobs present). Drain it or restart the jobs broker first.",
                file=sys.stderr,
            )
            raise SystemExit(1)


def run_burst_workers(hosts: list[str], queue_prefix: str) -> None:
    """Launch a burst worker only on the given hosts -- never the whole
    inventory group -- so an idle host that received no job this run is left
    alone. Ansible's --limit accepts a comma-separated host list; each
    matched host drains its own "<queue_prefix>-<that-host>" queue (see
    run-rq-burst-worker.yml)."""
    cmd = [
        str(ANSIBLE_DIR / "run-rq-burst-worker-local.sh"),
        "--limit",
        ",".join(hosts),
        "-e",
        f"rq_queue_name={queue_prefix}",
    ]
    subprocess.run(cmd, check=True)


def enqueue_and_collect(
    *,
    workers: list[str],
    queue_prefix: str,
    job_function: str,
    job_args: tuple[Any, ...],
    job_timeout: int,
    queue_factory: Callable[[str], QueueLike],
    launch_burst_workers: Callable[[list[str], str], None] = run_burst_workers,
    wait_timeout_s: float = WAIT_TIMEOUT_S,
    poll_interval_s: float = POLL_INTERVAL_S,
) -> dict[str, dict[str, Any]]:
    """Enqueue `job_function(*job_args)` onto every worker's own per-worker
    queue, launch burst workers only for the targeted hosts, wait for every
    job, and return one result record per worker: job id, start/end time,
    whether the RQ job itself failed, the job's own return value, and a
    per-worker `ok`. Does not raise on a worker's check failing -- only on a
    dirty queue or a job that never finishes; callers decide what an
    aggregate failure means (see write_report)."""
    if not workers:
        print("ABORT: no workers targeted.", file=sys.stderr)
        raise SystemExit(1)

    queues = {host: queue_factory(queue_name_for(queue_prefix, host)) for host in workers}
    assert_queues_empty(queues)

    jobs: dict[str, JobLike] = {}
    started_at: dict[str, str] = {}
    for host in workers:
        print(f"==> Enqueuing on {host} (queue {queues[host].name!r}).")
        started_at[host] = datetime.now(UTC).isoformat()
        jobs[host] = queues[host].enqueue(job_function, *job_args, job_timeout=job_timeout)

    launch_burst_workers(workers, queue_prefix)

    finished_at: dict[str, str] = {}
    pending = set(workers)
    deadline = time.monotonic() + wait_timeout_s
    while pending and time.monotonic() < deadline:
        for host in list(pending):
            jobs[host].refresh()
            if jobs[host].is_finished or jobs[host].is_failed:
                finished_at[host] = datetime.now(UTC).isoformat()
                pending.discard(host)
        if pending:
            time.sleep(poll_interval_s)
    if pending:
        print(
            f"ABORT: job(s) for {sorted(pending)} did not finish within {wait_timeout_s}s.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    per_worker: dict[str, dict[str, Any]] = {}
    for host in workers:
        job = jobs[host]
        result = job.result if job.is_finished else None
        per_worker[host] = {
            "job_id": job.id,
            "started_at_utc": started_at[host],
            "finished_at_utc": finished_at[host],
            "job_failed": job.is_failed,
            "result": result,
            "ok": (not job.is_failed) and bool(result) and result.get("valid", False),
        }
    return per_worker


def write_report(
    *, prefix: str, extra: dict[str, Any], per_worker: dict[str, dict[str, Any]]
) -> Path:
    aggregate_ok = bool(per_worker) and all(v["ok"] for v in per_worker.values())
    record: dict[str, Any] = {
        "observed": True,
        "measured_at_utc": datetime.now(UTC).isoformat(),
        **extra,
        "workers": per_worker,
        "ok": aggregate_ok,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_path = OUTPUT_DIR / f"{prefix}-{timestamp}.json"
    output_path.write_text(json.dumps(record, indent=2, default=str) + "\n")
    return output_path
