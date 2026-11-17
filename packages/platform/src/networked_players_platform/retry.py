"""Client-side retry orchestration (ADR 0073), free of any I/O so it is testable.

A retry is a brand-new attempt: new run id, new run directory, new RQ job id,
possibly a different worker. The executor's refusal to reuse an existing output
is never bypassed. RQ's own `Retry` is deliberately not used: it would re-enqueue
the same job id onto the same (possibly dead) worker's queue and trip the
no-reuse rule.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from .models import WorkerAdvertisement
from .scheduler import DEFAULT_HEARTBEAT_MAX_AGE, NoEligibleWorkerError

DEFAULT_LOST_GRACE = timedelta(seconds=90)


class RunLostError(RuntimeError):
    """The worker holding the job stopped advertising for longer than the grace."""


class RunFailedError(RuntimeError):
    """The attempt ended without a success manifest. `retryable` marks an
    infrastructure-class failure (killed work-horse); a workload exception is not."""

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(slots=True)
class AttemptRecord:
    attempt: int
    run_id: str
    worker_id: str
    outcome: str  # succeeded | worker-lost | retryable-failure | failed
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "run_id": self.run_id,
            "worker_id": self.worker_id,
            "outcome": self.outcome,
            "detail": self.detail,
        }


@dataclass(slots=True)
class RetryOutcome:
    result: dict[str, Any]
    worker: WorkerAdvertisement
    run_id: str
    attempt: int
    attempts: list[AttemptRecord] = field(default_factory=list)

    @property
    def orphans(self) -> list[AttemptRecord]:
        """Earlier attempts whose worker vanished: they may still hold a run
        directory (and possibly a still-running job) on that worker."""
        return [a for a in self.attempts if a.outcome == "worker-lost"]


class RetriesExhaustedError(RuntimeError):
    def __init__(self, message: str, attempts: list[AttemptRecord]) -> None:
        super().__init__(message)
        self.attempts = attempts


def attempt_run_id(base_run_id: str, attempt: int) -> str:
    return base_run_id if attempt == 1 else f"{base_run_id}-a{attempt}"


class WorkerWatch:
    """Decides a worker is lost when its advertisement has been missing or stale
    continuously for `grace`. Advertisements come from a heartbeat timer that is
    independent of the RQ worker process, so a busy worker keeps advertising;
    a lapse means the host, the service or the network is down. Redis cannot tell
    those apart, which is why a lost job is cancelled/stopped before a retry."""

    def __init__(
        self,
        worker_id: str,
        *,
        grace: timedelta = DEFAULT_LOST_GRACE,
        max_age: timedelta = DEFAULT_HEARTBEAT_MAX_AGE,
    ) -> None:
        self.worker_id = worker_id
        self.grace = grace
        self.max_age = max_age
        self._unhealthy_since: datetime | None = None

    def observe(self, workers: list[WorkerAdvertisement], now: datetime) -> bool:
        """Record one observation; True when the worker is now considered lost."""
        current = now.astimezone(UTC)
        fresh = any(
            w.worker_id == self.worker_id
            and current - datetime.fromisoformat(w.observed_at).astimezone(UTC) <= self.max_age
            for w in workers
        )
        if fresh:
            self._unhealthy_since = None
            return False
        if self._unhealthy_since is None:
            self._unhealthy_since = current
        return current - self._unhealthy_since >= self.grace


AttemptRunner = Callable[[WorkerAdvertisement, str, int, str | None], dict[str, Any]]
Selector = Callable[[frozenset[str]], WorkerAdvertisement]


def run_with_retries(
    *,
    base_run_id: str,
    max_retries: int,
    select: Selector,
    run_attempt: AttemptRunner,
) -> RetryOutcome:
    """Run up to `1 + max_retries` attempts. `select(excluded_worker_ids)` picks a
    worker (raising `NoEligibleWorkerError` when none is left); `run_attempt(worker,
    run_id, attempt, retry_of)` stages, enqueues and waits, raising `RunLostError`
    or `RunFailedError`."""
    attempts: list[AttemptRecord] = []
    tried: set[str] = set()
    previous: str | None = None
    for attempt in range(1, max_retries + 2):
        run_id = attempt_run_id(base_run_id, attempt)
        try:
            worker = select(frozenset(tried))
        except NoEligibleWorkerError as exc:
            if not attempts:
                raise
            raise RetriesExhaustedError(
                f"no worker left to retry attempt {attempt}: {exc}", attempts
            ) from exc
        tried.add(worker.worker_id)
        try:
            result = run_attempt(worker, run_id, attempt, previous)
        except RunLostError as exc:
            attempts.append(
                AttemptRecord(attempt, run_id, worker.worker_id, "worker-lost", str(exc))
            )
        except RunFailedError as exc:
            outcome = "retryable-failure" if exc.retryable else "failed"
            attempts.append(AttemptRecord(attempt, run_id, worker.worker_id, outcome, str(exc)))
            if not exc.retryable:
                raise RetriesExhaustedError(str(exc), attempts) from exc
        else:
            attempts.append(AttemptRecord(attempt, run_id, worker.worker_id, "succeeded"))
            return RetryOutcome(result, worker, run_id, attempt, attempts)
        previous = run_id
    raise RetriesExhaustedError(
        f"all {len(attempts)} attempt(s) failed: " + "; ".join(a.outcome for a in attempts),
        attempts,
    )
