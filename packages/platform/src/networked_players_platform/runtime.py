"""Observed worker capability and standing RQ process entry points."""

from __future__ import annotations

import json
import os
import platform
from datetime import UTC, datetime

from rq import Queue, Worker
from rq.registry import StartedJobRegistry

from .broker import publish_advertisement, queue_name, redis_from_url
from .digest import contracts_version, installed_contracts_digest, installed_digest_report
from .models import WorkerAdvertisement
from .workloads import discover_available_workloads


class RuntimeConfigurationError(RuntimeError):
    """Raised when a worker's private environment is incomplete."""


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeConfigurationError(f"{name} is required")
    return value


def _memory_total_mb() -> int:
    try:
        for line in open("/proc/meminfo", encoding="utf-8"):
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) // 1024
    except (OSError, ValueError):
        pass
    raise RuntimeConfigurationError("could not read total memory from /proc/meminfo")


def _workloads() -> tuple[dict[str, str], dict[str, str]]:
    """(advertised workload versions, unavailable workload -> reason). One broken
    plugin or unhashable workload is reported unavailable; the others stay up."""
    available, errors = discover_available_workloads()
    digests, digest_errors = installed_digest_report()
    unavailable = {**digest_errors, **errors}
    versions = {
        name: registered.spec.version for name, registered in available.items() if name in digests
    }
    for name in available:
        if name not in digests and name not in unavailable:
            unavailable[name] = "no runtime digest"
    return versions, unavailable


def build_advertisement(*, active_jobs: int = 0) -> WorkerAdvertisement:
    tags = tuple(sorted(filter(None, _required_env("PLATFORM_TAGS").split(","))))
    datasets_json = os.environ.get("PLATFORM_DATASETS_JSON", "[]")
    datasets = json.loads(datasets_json)
    versions, unavailable = _workloads()
    payload = {
        "schema_version": 2,
        "worker_id": _required_env("PLATFORM_WORKER_ID"),
        "observed_at": datetime.now(UTC).isoformat(),
        "architecture": platform.machine().lower(),
        "tags": tags,
        "total_memory_mb": _memory_total_mb(),
        "max_job_memory_mb": int(_required_env("PLATFORM_MAX_JOB_MEMORY_MB")),
        "runtime_commit": _required_env("PLATFORM_RUNTIME_COMMIT"),
        "workloads": versions,
        "unavailable_workloads": unavailable,
        "datasets": datasets,
        "active_jobs": active_jobs,
        "runtime_digests": installed_digest_report()[0],
        "contracts_version": contracts_version(),
        "contracts_digest": installed_contracts_digest(),
    }
    return WorkerAdvertisement.from_dict(payload)


def heartbeat() -> WorkerAdvertisement:
    broker = redis_from_url(_required_env("JOBS_BROKER_URL"))
    worker_id = _required_env("PLATFORM_WORKER_ID")
    queue = Queue(queue_name(worker_id), connection=broker)
    active_jobs = StartedJobRegistry(queue=queue).count
    advertisement = build_advertisement(active_jobs=active_jobs)
    publish_advertisement(broker, advertisement)
    return advertisement


def run_worker() -> bool:
    broker = redis_from_url(_required_env("JOBS_BROKER_URL"))
    worker_id = _required_env("PLATFORM_WORKER_ID")
    queue = Queue(queue_name(worker_id), connection=broker)
    # Hash the installed code once, before the first job: RQ forks a work-horse per
    # job and the cached digests are inherited, so no job pays for hashing again.
    installed_digest_report()
    publish_advertisement(broker, build_advertisement(active_jobs=0))
    worker = Worker([queue], connection=broker, name=worker_id)
    return worker.work(with_scheduler=False)
