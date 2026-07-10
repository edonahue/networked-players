"""Deterministic worker eligibility and selection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .models import CapabilityRequirement, WorkerAdvertisement

DEFAULT_HEARTBEAT_MAX_AGE = timedelta(seconds=90)


class NoEligibleWorkerError(RuntimeError):
    """Raised when no fresh advertisement satisfies a workload."""


def _dataset_keys(worker: WorkerAdvertisement) -> set[tuple[str, str, str]]:
    return {(item.name, item.snapshot, item.manifest_sha256) for item in worker.datasets}


def _eligible(
    worker: WorkerAdvertisement,
    requirement: CapabilityRequirement,
    *,
    workload_id: str,
    workload_version: str,
    runtime_commit: str,
    now: datetime,
    heartbeat_max_age: timedelta,
) -> bool:
    observed = datetime.fromisoformat(worker.observed_at).astimezone(UTC)
    if now - observed > heartbeat_max_age or observed > now + timedelta(seconds=5):
        return False
    if worker.runtime_commit != runtime_commit:
        return False
    if worker.workloads.get(workload_id) != workload_version:
        return False
    if requirement.architectures and worker.architecture not in requirement.architectures:
        return False
    if not set(requirement.tags).issubset(worker.tags):
        return False
    if worker.max_job_memory_mb < requirement.min_memory_mb:
        return False
    required_datasets = {
        (item.name, item.snapshot, item.manifest_sha256) for item in requirement.datasets
    }
    return required_datasets.issubset(_dataset_keys(worker))


def select_worker(
    workers: list[WorkerAdvertisement],
    requirement: CapabilityRequirement,
    *,
    workload_id: str,
    workload_version: str,
    runtime_commit: str,
    now: datetime | None = None,
    heartbeat_max_age: timedelta = DEFAULT_HEARTBEAT_MAX_AGE,
) -> WorkerAdvertisement:
    """Select the least-loaded eligible worker with stable tie breaking."""
    current = (now or datetime.now(UTC)).astimezone(UTC)
    eligible = [
        worker
        for worker in workers
        if _eligible(
            worker,
            requirement,
            workload_id=workload_id,
            workload_version=workload_version,
            runtime_commit=runtime_commit,
            now=current,
            heartbeat_max_age=heartbeat_max_age,
        )
    ]
    if not eligible:
        raise NoEligibleWorkerError(
            f"no fresh worker provides {workload_id}@{workload_version} with the required "
            "runtime, resources, tags, and datasets"
        )
    return min(
        eligible,
        key=lambda worker: (
            worker.active_jobs,
            worker.last_assigned_at or "",
            worker.worker_id,
        ),
    )
