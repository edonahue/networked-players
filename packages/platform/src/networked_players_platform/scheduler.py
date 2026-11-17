"""Deterministic worker eligibility and selection.

Eligibility is by runtime digest (ADR 0073), not by git commit. Every refusal
carries a human-readable reason so version skew is explained, not silent.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from .broker import RQ_WORKER_TTL_SECONDS
from .models import CapabilityRequirement, WorkerAdvertisement

DEFAULT_HEARTBEAT_MAX_AGE = timedelta(seconds=90)


class NoEligibleWorkerError(RuntimeError):
    """Raised when no fresh advertisement satisfies a workload.

    `reasons` maps every considered worker_id to why it was refused.
    """

    def __init__(self, message: str, reasons: dict[str, list[str]] | None = None) -> None:
        super().__init__(message)
        self.reasons = reasons or {}


def _dataset_keys(worker: WorkerAdvertisement) -> set[tuple[str, str, str]]:
    return {(item.name, item.snapshot, item.manifest_sha256) for item in worker.datasets}


def ineligibility_reasons(
    worker: WorkerAdvertisement,
    requirement: CapabilityRequirement,
    *,
    workload_id: str,
    workload_version: str,
    runtime_digest: str,
    now: datetime,
    heartbeat_max_age: timedelta = DEFAULT_HEARTBEAT_MAX_AGE,
    rq_checked: bool = False,
    rq_last_heartbeat: datetime | None = None,
) -> list[str]:
    """Every reason `worker` cannot take the job; an empty list means eligible."""
    reasons: list[str] = []
    observed = datetime.fromisoformat(worker.observed_at).astimezone(UTC)
    if now - observed > heartbeat_max_age:
        age = int((now - observed).total_seconds())
        reasons.append(
            f"stale heartbeat: observed {worker.observed_at}, {age}s old "
            f"(limit {int(heartbeat_max_age.total_seconds())}s)"
        )
    elif observed > now + timedelta(seconds=5):
        reasons.append(f"heartbeat is in the future: observed {worker.observed_at}")

    if rq_checked:
        if rq_last_heartbeat is None:
            reasons.append(
                "RQ worker process absent: no rq:worker record, so nothing consumes this "
                "worker's queue even though its advertisement is fresh"
            )
        elif now - rq_last_heartbeat > timedelta(seconds=RQ_WORKER_TTL_SECONDS):
            reasons.append(
                f"RQ worker heartbeat stale: last {rq_last_heartbeat.isoformat()} "
                f"(RQ expires a silent worker after {RQ_WORKER_TTL_SECONDS}s)"
            )

    installed_version = worker.workloads.get(workload_id)
    if installed_version != workload_version and workload_id in worker.unavailable_workloads:
        reasons.append(
            f"workload {workload_id} unavailable on worker: "
            f"{worker.unavailable_workloads[workload_id]}"
        )
    elif installed_version != workload_version:
        reasons.append(
            f"workload {workload_id}@{workload_version} not provided "
            f"(worker has {installed_version or 'none'})"
        )
    elif worker.schema_version < 2:
        reasons.append(
            f"advertisement schema {worker.schema_version} carries no runtime digests "
            f"(recorded commit {worker.runtime_commit[:12]}); redeploy the runtime"
        )
    else:
        worker_digest = worker.runtime_digests.get(workload_id)
        if worker_digest is None:
            reasons.append(f"no runtime digest advertised for {workload_id}; redeploy the runtime")
        elif worker_digest != runtime_digest:
            reasons.append(
                f"runtime digest mismatch: worker {worker_digest} "
                f"(recorded commit {worker.runtime_commit[:12]}) != request {runtime_digest}"
            )

    if requirement.architectures and worker.architecture not in requirement.architectures:
        reasons.append(
            f"architecture {worker.architecture} not in {sorted(requirement.architectures)}"
        )
    missing_tags = sorted(set(requirement.tags) - set(worker.tags))
    if missing_tags:
        reasons.append(f"missing tags {missing_tags}")
    if worker.max_job_memory_mb < requirement.min_memory_mb:
        reasons.append(
            f"max job memory {worker.max_job_memory_mb} MB below required "
            f"{requirement.min_memory_mb} MB"
        )
    required = {(item.name, item.snapshot, item.manifest_sha256) for item in requirement.datasets}
    missing_datasets = sorted(required - _dataset_keys(worker))
    if missing_datasets:
        reasons.append(
            "dataset identity not present: " + ", ".join(f"{n}@{s}" for n, s, _ in missing_datasets)
        )
    return reasons


def explain_workers(
    workers: list[WorkerAdvertisement],
    requirement: CapabilityRequirement,
    *,
    workload_id: str,
    workload_version: str,
    runtime_digest: str,
    now: datetime | None = None,
    heartbeat_max_age: timedelta = DEFAULT_HEARTBEAT_MAX_AGE,
    rq_heartbeats: Mapping[str, datetime | None] | None = None,
) -> dict[str, list[str]]:
    """worker_id -> ineligibility reasons (empty list = eligible)."""
    current = (now or datetime.now(UTC)).astimezone(UTC)
    return {
        worker.worker_id: ineligibility_reasons(
            worker,
            requirement,
            workload_id=workload_id,
            workload_version=workload_version,
            runtime_digest=runtime_digest,
            now=current,
            heartbeat_max_age=heartbeat_max_age,
            rq_checked=rq_heartbeats is not None,
            rq_last_heartbeat=(rq_heartbeats or {}).get(worker.worker_id),
        )
        for worker in workers
    }


def format_refusals(workload_id: str, workload_version: str, reasons: dict[str, list[str]]) -> str:
    header = f"no eligible worker for {workload_id}@{workload_version}"
    if not reasons:
        return header + ": no worker advertisements found (broker unreachable or no workers up)"
    lines = [header + ":"]
    for worker_id in sorted(reasons):
        lines.append(f"  {worker_id}: " + "; ".join(reasons[worker_id]))
    return "\n".join(lines)


def select_worker(
    workers: list[WorkerAdvertisement],
    requirement: CapabilityRequirement,
    *,
    workload_id: str,
    workload_version: str,
    runtime_digest: str,
    now: datetime | None = None,
    heartbeat_max_age: timedelta = DEFAULT_HEARTBEAT_MAX_AGE,
    exclude: frozenset[str] = frozenset(),
    rq_heartbeats: Mapping[str, datetime | None] | None = None,
    problems: Mapping[str, str] | None = None,
    memory_above_mb: int | None = None,
) -> WorkerAdvertisement:
    """Select the least-loaded eligible worker with stable tie breaking.

    `exclude` removes workers already tried (a lost worker must not be re-picked
    by a retry). `rq_heartbeats` (worker_id -> RQ `last_heartbeat`, None = absent)
    additionally excludes a worker whose RQ process is not running even though its
    advertisement is fresh; leave it None to skip that check. `problems` are
    unreadable advertisements, reported per worker. `memory_above_mb` restricts to
    workers with a strictly larger job-memory budget (retry after a suspected OOM).
    Raises `NoEligibleWorkerError` carrying per-worker reasons.
    """
    reasons = explain_workers(
        workers,
        requirement,
        workload_id=workload_id,
        workload_version=workload_version,
        runtime_digest=runtime_digest,
        now=now,
        heartbeat_max_age=heartbeat_max_age,
        rq_heartbeats=rq_heartbeats,
    )
    for worker in workers:
        if memory_above_mb is not None and worker.max_job_memory_mb <= memory_above_mb:
            reasons[worker.worker_id].append(
                f"max job memory {worker.max_job_memory_mb} MB is not above the "
                f"{memory_above_mb} MB budget of the worker whose job was killed"
            )
    for worker_id, problem in (problems or {}).items():
        reasons.setdefault(worker_id, []).append(problem)
    for worker_id in exclude:
        if worker_id in reasons:
            reasons[worker_id] = [*reasons[worker_id], "already attempted (lost or failed)"]
    eligible = [worker for worker in workers if not reasons[worker.worker_id]]
    if not eligible:
        message = format_refusals(workload_id, workload_version, reasons)
        raise NoEligibleWorkerError(message, reasons)
    return min(
        eligible,
        key=lambda worker: (
            worker.active_jobs,
            worker.last_assigned_at or "",
            worker.worker_id,
        ),
    )
