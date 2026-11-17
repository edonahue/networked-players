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

from .broker import RQ_WORKER_TTL_SECONDS
from .models import WorkerAdvertisement
from .scheduler import NoEligibleWorkerError

# Extra continuous time the RQ worker must stay not-live (on top of RQ's own TTL).
DEFAULT_LOST_GRACE = timedelta(seconds=60)


class RunLostError(RuntimeError):
    """The worker holding the job stopped advertising for longer than the grace."""


class RunFailedError(RuntimeError):
    """The attempt ended without a success manifest. `retryable` marks an
    infrastructure-class failure (killed work-horse); a workload exception is not."""

    def __init__(self, message: str, *, retryable: bool, memory_suspect: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable
        # A killed work-horse that cannot be told apart from an out-of-memory kill:
        # retried only on a worker with a larger job-memory budget.
        self.memory_suspect = memory_suspect


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
    """Decides a worker is lost from RQ's OWN liveness, never from the advertisement.

    The advertisement comes from a separate heartbeat timer unit, so its lapse says
    nothing about whether the RQ worker process (the consumer of the queue and the
    owner of a started job) is alive, and a failing heartbeat must never get a
    healthy job killed. The rule: the RQ worker is *live* when its `rq:worker:<name>`
    record exists and its `last_heartbeat` is at most `rq_ttl` old (RQ's own worker
    TTL); it is *lost* only when it has been not-live continuously for `grace`.
    While it is live, `observe` always returns False, whatever the advertisement
    says; the advertisement only annotates the report."""

    def __init__(
        self,
        worker_id: str,
        *,
        grace: timedelta = DEFAULT_LOST_GRACE,
        rq_ttl: timedelta = timedelta(seconds=RQ_WORKER_TTL_SECONDS),
    ) -> None:
        self.worker_id = worker_id
        self.grace = grace
        self.rq_ttl = rq_ttl
        self._not_live_since: datetime | None = None
        self.advertisement_fresh = True

    def observe(
        self,
        rq_last_heartbeat: datetime | None,
        now: datetime,
        *,
        advertisement_fresh: bool = True,
    ) -> bool:
        """Record one observation; True when the RQ worker is now considered lost."""
        current = now.astimezone(UTC)
        self.advertisement_fresh = advertisement_fresh
        live = rq_last_heartbeat is not None and current - rq_last_heartbeat <= self.rq_ttl
        if live:
            self._not_live_since = None
            return False
        if self._not_live_since is None:
            self._not_live_since = current
        return current - self._not_live_since >= self.grace


AttemptRunner = Callable[[WorkerAdvertisement, str, int, str | None], dict[str, Any]]
Selector = Callable[[frozenset[str], int | None], WorkerAdvertisement]


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
    memory_floor: int | None = None
    for attempt in range(1, max_retries + 2):
        run_id = attempt_run_id(base_run_id, attempt)
        try:
            worker = select(frozenset(tried), memory_floor)
        except NoEligibleWorkerError as exc:
            if not attempts:
                raise
            why = (
                f"the work-horse was killed (possibly out of memory at {memory_floor} MB) and "
                "no eligible worker has a larger max_job_memory_mb"
                if memory_floor is not None
                else "no worker left"
            )
            raise RetriesExhaustedError(
                f"cannot retry attempt {attempt}: {why}: {exc}", attempts
            ) from exc
        tried.add(worker.worker_id)
        try:
            result = run_attempt(worker, run_id, attempt, previous)
        except RunLostError as exc:
            attempts.append(
                AttemptRecord(attempt, run_id, worker.worker_id, "worker-lost", str(exc))
            )
        except RunFailedError as exc:
            outcome = (
                "memory-suspect-kill"
                if exc.memory_suspect
                else "retryable-failure"
                if exc.retryable
                else "failed"
            )
            if exc.memory_suspect:
                memory_floor = max(memory_floor or 0, worker.max_job_memory_mb)
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
