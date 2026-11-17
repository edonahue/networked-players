"""Operator view of platform jobs, read from the existing RQ/Redis state.

`JobBackend` is the seam: `RqJobBackend` reads and mutates real RQ state through
RQ's public API only; tests drive the same logic with an in-memory backend.
Nothing here opens an SSH connection, and listing never mutates Redis.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Protocol

from .broker import QUEUE_PREFIX

QUEUED_STATES = frozenset({"queued", "scheduled", "deferred"})
TERMINAL_STATES = frozenset({"finished", "failed", "canceled", "stopped"})
# RQ's own wording for work-horse deaths; the only failure text treated as an
# infrastructure loss that a fresh attempt on another worker can reasonably fix.
RETRYABLE_FAILURE_MARKERS = ("Work-horse terminated unexpectedly", "AbandonedJobError")


@dataclass(frozen=True, slots=True)
class JobRecord:
    job_id: str
    queue: str
    worker_id: str
    state: str
    workload_id: str
    attempt: int
    retry_of: str | None
    enqueued_at: str | None
    started_at: str | None
    ended_at: str | None
    remote_run: str | None
    exc_info: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CancelOutcome:
    job_id: str
    action: str  # "canceled", "stop-requested", "not-cancelable", "not-found"
    message: str


class JobBackend(Protocol):
    def list_jobs(self, *, limit_per_state: int) -> list[JobRecord]: ...

    def get_job(self, job_id: str) -> JobRecord | None: ...

    def cancel_queued(self, job_id: str) -> None: ...

    def request_stop(self, job_id: str) -> None: ...


def is_retryable_failure(exc_info: str | None) -> bool:
    return bool(exc_info) and any(
        marker in (exc_info or "") for marker in RETRYABLE_FAILURE_MARKERS
    )


def cancel_job(
    backend: JobBackend, job_id: str, *, advertised_workers: Iterable[str] = ()
) -> CancelOutcome:
    """Cancel a queued job, or request a stop of a started one.

    Honest limits (also in docs/OPERATOR_SETUP.md): cancelling a queued job is
    purely Redis-side and always works. Stopping a started job asks the owning RQ
    worker to kill its work-horse process; it is asynchronous, is lost if that
    worker is down, and leaves the run directory (partial `.output.staging`) on
    the worker for inspection -- nothing is cleaned up remotely.
    """
    record = backend.get_job(job_id)
    if record is None:
        return CancelOutcome(job_id, "not-found", f"no such job {job_id!r} (expired or never run)")
    if record.state in QUEUED_STATES:
        backend.cancel_queued(job_id)
        return CancelOutcome(
            job_id,
            "canceled",
            "removed from the queue before it started; nothing ran and nothing is left "
            "on the worker",
        )
    if record.state == "started":
        backend.request_stop(job_id)
        note = ""
        if record.worker_id not in set(advertised_workers):
            note = (
                f" Worker {record.worker_id} is not advertising, so the stop command may never "
                "be delivered; the job will stay in the started registry until that worker returns."
            )
        return CancelOutcome(
            job_id,
            "stop-requested",
            "stop requested; the worker kills the job's work-horse process asynchronously. "
            "Re-run `jobs status` to confirm. The run directory is left in place on the "
            f"worker.{note}",
        )
    return CancelOutcome(job_id, "not-cancelable", f"job is already {record.state}")


def log_locations(record: JobRecord) -> dict[str, Any]:
    """Where this job's evidence lives on its worker, plus the recorded failure."""
    remote = record.remote_run
    return {
        "job_id": record.job_id,
        "worker_id": record.worker_id,
        "state": record.state,
        "run_directory_on_worker": remote,
        "failure_record_on_worker": f"{remote}/failed.json" if remote else None,
        "completed_output_on_worker": f"{remote}/completed" if remote else None,
        "partial_output_on_worker": f"{remote}/.output.staging" if remote else None,
        "worker_service_log_hint": (
            "journalctl --user -u networked-players-platform-worker.service "
            "(run on the worker; this command does not connect to it)"
        ),
        "recorded_failure": record.exc_info,
    }


# --- real RQ backend --------------------------------------------------------------


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class RqJobBackend:
    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def _record(self, job: Any) -> JobRecord:
        meta = job.meta or {}
        queue = job.origin or ""
        args = job.args or ()
        status = job.get_status(refresh=False)
        return JobRecord(
            job_id=job.id,
            queue=queue,
            worker_id=queue.removeprefix(QUEUE_PREFIX) or (job.worker_name or ""),
            state=status.value if status else "unknown",
            workload_id=str(meta.get("workload_id", "unknown")),
            attempt=int(meta.get("attempt", 1)),
            retry_of=meta.get("retry_of"),
            enqueued_at=_iso(job.enqueued_at),
            started_at=_iso(job.started_at),
            ended_at=_iso(job.ended_at),
            remote_run=str(args[0]) if args else None,
            exc_info=job.exc_info,
        )

    def list_jobs(self, *, limit_per_state: int) -> list[JobRecord]:
        from rq import Queue
        from rq.job import Job
        from rq.registry import (
            CanceledJobRegistry,
            FailedJobRegistry,
            FinishedJobRegistry,
            StartedJobRegistry,
        )

        end = max(limit_per_state - 1, 0)
        ids: list[str] = []
        for queue in Queue.all(connection=self._connection):
            if not queue.name.startswith(QUEUE_PREFIX):
                continue
            ids.extend(queue.get_job_ids(0, limit_per_state))
            for registry_class in (
                StartedJobRegistry,
                FinishedJobRegistry,
                FailedJobRegistry,
                CanceledJobRegistry,
            ):
                registry = registry_class(queue=queue)
                # cleanup=False keeps listing read-only (cleanup moves abandoned jobs).
                ids.extend(registry.get_job_ids(0, end, True, False))
        jobs = Job.fetch_many(list(dict.fromkeys(ids)), connection=self._connection)
        records = [self._record(job) for job in jobs if job is not None]
        return sorted(records, key=lambda r: (r.enqueued_at or "", r.job_id), reverse=True)

    def get_job(self, job_id: str) -> JobRecord | None:
        from rq.exceptions import NoSuchJobError
        from rq.job import Job

        try:
            return self._record(Job.fetch(job_id, connection=self._connection))
        except NoSuchJobError:
            return None

    def cancel_queued(self, job_id: str) -> None:
        from rq.job import Job

        Job.fetch(job_id, connection=self._connection).cancel()

    def request_stop(self, job_id: str) -> None:
        from rq.command import send_stop_job_command

        send_stop_job_command(self._connection, job_id)


# --- rendering ---------------------------------------------------------------------


def filter_records(
    records: list[JobRecord], *, worker_id: str | None = None, state: str | None = None
) -> list[JobRecord]:
    return [
        r
        for r in records
        if (worker_id is None or r.worker_id == worker_id) and (state is None or r.state == state)
    ]


def render_table(records: list[JobRecord]) -> str:
    header = "JOB\tWORKER\tSTATE\tWORKLOAD\tATTEMPT\tENQUEUED\tSTARTED\tENDED"
    rows = [
        "\t".join(
            [
                r.job_id,
                r.worker_id,
                r.state,
                r.workload_id,
                str(r.attempt),
                r.enqueued_at or "-",
                r.started_at or "-",
                r.ended_at or "-",
            ]
        )
        for r in records
    ]
    return "\n".join([header, *rows])
