"""Deterministic shard fan-out and gather on top of the ADR 0034 platform (ADR 0073 addendum).

A big job is split into shards by a stable hash of each item's key, every non-empty
shard is submitted as its own job (own run id, own retries, any eligible worker), and
the results are gathered in a deterministic order after verifying that every shard
arrived exactly once. Nothing here performs I/O against Redis or a worker: the
caller supplies the worker listing and the per-shard runner, so the whole contract is
testable with in-memory fakes and the same code drives the real submit scripts.

Bounds (Pi workers are constrained 1 GB nodes): a shard's input is capped at
`MAX_SHARD_INPUT_BYTES`; the cure for an oversized shard is more shards, never a
larger memory limit; in-flight shards never exceed the eligible worker count.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import WorkerAdvertisement
from .retry import RetriesExhaustedError, RetryOutcome, Selector
from .scheduler import NoEligibleWorkerError

MAX_SHARD_INPUT_BYTES = 256 * 1024 * 1024
MAX_SHARDS = 256
MAX_SHARD_CONCURRENCY = 8
_JOB_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,100}$")

ShardKey = int | str


class ShardPlanError(ValueError):
    """The requested split is invalid or violates a bound."""


class GatherError(RuntimeError):
    """Shard results are incomplete, duplicated or do not match the plan."""

    def __init__(
        self,
        message: str,
        *,
        missing: Sequence[int] = (),
        duplicates: Sequence[int] = (),
        unexpected: Sequence[int] = (),
    ) -> None:
        super().__init__(message)
        self.missing = tuple(missing)
        self.duplicates = tuple(duplicates)
        self.unexpected = tuple(unexpected)


class ShardedRunError(RuntimeError):
    """One or more shards could not be completed within their retry budget.
    Shards that did complete are kept in `completed` (their outputs are valid)."""

    def __init__(
        self,
        message: str,
        failures: dict[int, str],
        completed: dict[int, Any],
        attempts: dict[int, list[Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.failures = failures
        self.completed = completed
        # shard index -> AttemptRecords of the shard's failed retry sequence
        self.attempts = attempts or {}


def shard_for_key(key: ShardKey, shard_count: int) -> int:
    """Stable shard index of `key`: SHA-256 of its canonical text, never Python's
    per-process `hash()`. An int and its decimal string hash alike on purpose."""
    if shard_count < 1:
        raise ShardPlanError("shard_count must be at least 1")
    digest = hashlib.sha256(str(key).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % shard_count


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(value: Any) -> str:
    """Content hash of a JSON-compatible value, independent of key order and layout."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def write_atomic(path: Path, data: bytes) -> None:
    """Write `data` so readers see the old file or the complete new one, never a
    partial file: temp file in the same directory, fsync, then `os.replace`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial-{os.getpid()}")
    try:
        with temporary.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


@dataclass(frozen=True, slots=True)
class ShardSpec:
    index: int
    shard_count: int
    run_id: str
    keys: tuple[ShardKey, ...]
    input_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "shard_count": self.shard_count,
            "run_id": self.run_id,
            "key_count": len(self.keys),
            "keys_sha256": canonical_hash(list(self.keys)),
            "input_bytes": self.input_bytes,
        }


@dataclass(frozen=True, slots=True)
class ShardPlan:
    job_id: str
    shard_count: int
    key_order: tuple[ShardKey, ...]
    shards: tuple[ShardSpec, ...]  # every shard, including empty ones, by index

    @property
    def active(self) -> tuple[ShardSpec, ...]:
        """Shards that hold at least one key; only these are submitted and gathered."""
        return tuple(shard for shard in self.shards if shard.keys)

    def shard(self, index: int) -> ShardSpec:
        return self.shards[index]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "job_id": self.job_id,
            "shard_count": self.shard_count,
            "key_count": len(self.key_order),
            "keys_sha256": canonical_hash(list(self.key_order)),
            "active_shards": [shard.index for shard in self.active],
            "shards": [shard.to_dict() for shard in self.shards],
        }


def shard_run_id(job_id: str, index: int, shard_count: int) -> str:
    return f"{job_id}-s{index:03d}of{shard_count:03d}"


def plan_shards(
    job_id: str,
    keys: Iterable[ShardKey],
    shard_count: int,
    *,
    key_bytes: Callable[[ShardKey], int] | None = None,
    max_shard_input_bytes: int = MAX_SHARD_INPUT_BYTES,
) -> ShardPlan:
    """Split `keys` into `shard_count` shards by stable hash. Duplicate keys are
    rejected (a duplicate would be processed twice by one run and once by another,
    breaking equivalence with a single-node run). A shard whose estimated input
    exceeds `max_shard_input_bytes` is refused: raise `shard_count` instead."""
    if not _JOB_ID_RE.fullmatch(job_id):
        raise ShardPlanError(f"job_id must match {_JOB_ID_RE.pattern!r}")
    if not 1 <= shard_count <= MAX_SHARDS:
        raise ShardPlanError(f"shard_count must be between 1 and {MAX_SHARDS}")
    ordered = tuple(keys)
    duplicates = sorted(
        {k for k, count in Counter(str(key) for key in ordered).items() if count > 1}
    )
    if duplicates:
        raise ShardPlanError(f"duplicate shard keys: {duplicates[:5]}")
    buckets: list[list[ShardKey]] = [[] for _ in range(shard_count)]
    sizes = [0] * shard_count
    for key in ordered:
        index = shard_for_key(key, shard_count)
        buckets[index].append(key)
        sizes[index] += key_bytes(key) if key_bytes is not None else 0
    for index, size in enumerate(sizes):
        if size > max_shard_input_bytes:
            raise ShardPlanError(
                f"shard {index} input is {size} bytes, over the {max_shard_input_bytes}-byte "
                f"bound; use more shards (never a larger memory limit)"
            )
    shards = tuple(
        ShardSpec(
            index=index,
            shard_count=shard_count,
            run_id=shard_run_id(job_id, index, shard_count),
            keys=tuple(buckets[index]),
            input_bytes=sizes[index],
        )
        for index in range(shard_count)
    )
    return ShardPlan(job_id=job_id, shard_count=shard_count, key_order=ordered, shards=shards)


def assign_preview(
    plan: ShardPlan, workers: Sequence[WorkerAdvertisement]
) -> dict[int, str | None]:
    """The dry-run placement: active shard index -> worker id, round robin over the
    eligible workers given (None when there are none). Informational only; the real
    run re-selects per attempt from live advertisements."""
    return {
        shard.index: (workers[position % len(workers)].worker_id if workers else None)
        for position, shard in enumerate(plan.active)
    }


def verify_complete(plan: ShardPlan, received: Iterable[tuple[int, Any]]) -> list[Any]:
    """Payloads of every active shard in ascending shard-index order, or `GatherError`.

    Exactly once: each active shard must appear one time; a missing shard, a duplicate
    and an index the plan never submitted are each reported (all of them, not the first).
    """
    seen: Counter[int] = Counter()
    payloads: dict[int, Any] = {}
    for index, payload in received:
        seen[index] += 1
        payloads.setdefault(index, payload)
    expected = {shard.index for shard in plan.active}
    missing = sorted(expected - set(seen))
    duplicates = sorted(i for i, count in seen.items() if count > 1)
    unexpected = sorted(set(seen) - expected)
    if missing or duplicates or unexpected:
        raise GatherError(
            f"shard gather for {plan.job_id} is not exactly-once: missing {missing}, "
            f"duplicated {duplicates}, unexpected {unexpected}",
            missing=missing,
            duplicates=duplicates,
            unexpected=unexpected,
        )
    return [payloads[index] for index in sorted(expected)]


def verify_shard_keys(plan: ShardPlan, index: int, returned_keys: Sequence[ShardKey]) -> None:
    """The shard returned exactly the keys it was given, no more, no fewer."""
    expected = Counter(str(k) for k in plan.shard(index).keys)
    actual = Counter(str(k) for k in returned_keys)
    if expected != actual:
        extra = sorted((actual - expected).elements())[:5]
        absent = sorted((expected - actual).elements())[:5]
        raise GatherError(
            f"shard {index} of {plan.job_id} returned the wrong keys: "
            f"unexpected {extra}, missing {absent}"
        )


ListEligible = Callable[[frozenset[str], int | None], list[WorkerAdvertisement]]


class ShardBalancer:
    """Gives each in-flight shard its own eligible worker, never doubling up.

    `list_eligible(excluded, memory_floor)` returns the eligible workers (the caller
    wires it to `select_workers`, raising `NoEligibleWorkerError` when there are
    none). A shard is only ever assigned a worker that holds none of OUR other
    in-flight shards; when every eligible worker is occupied it waits for one to free
    up (re-listing eligibility each pass, so a worker that dies meanwhile drops out).
    Stacking a second shard on a busy worker would leave it queued behind the first,
    where its client-side deadline runs without it executing. Among free workers the
    choice rotates by shard position so placement is reproducible. A retry after a lost
    worker passes that worker in `excluded`, so the shard moves to another one.
    """

    def __init__(
        self,
        list_eligible: ListEligible,
        *,
        poll_seconds: float = 1.0,
        max_wait_seconds: float = 3600.0,  # callers derive it from the workload timeout
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._list_eligible = list_eligible
        self._cond = threading.Condition()
        self._in_flight: Counter[str] = Counter()
        self._holding: dict[int, str] = {}
        self._poll = poll_seconds
        self._max_wait = max_wait_seconds
        self._monotonic = monotonic

    def selector(self, position: int, shard_index: int) -> Selector:
        def select(excluded: frozenset[str], memory_floor: int | None) -> WorkerAdvertisement:
            started = self._monotonic()
            while True:
                with self._cond:
                    self._release_locked(shard_index)
                eligible = self._list_eligible(excluded, memory_floor)
                with self._cond:
                    size = len(eligible)
                    free = [i for i in range(size) if self._in_flight[eligible[i].worker_id] == 0]
                    if free:
                        chosen = min(free, key=lambda i: (i - position) % size)
                        worker = eligible[chosen]
                        self._in_flight[worker.worker_id] += 1
                        self._holding[shard_index] = worker.worker_id
                        return worker
                    if self._monotonic() - started >= self._max_wait:
                        # NoEligibleWorkerError, so run_with_retries keeps the attempt
                        # history and reports RetriesExhaustedError.
                        raise NoEligibleWorkerError(
                            f"shard {shard_index}: no unoccupied eligible worker after "
                            f"{int(self._max_wait)}s (all eligible workers hold other shards)"
                        )
                    self._cond.wait(timeout=self._poll)

        return select

    def release(self, shard_index: int) -> None:
        with self._cond:
            self._release_locked(shard_index)

    def _release_locked(self, shard_index: int) -> None:
        previous = self._holding.pop(shard_index, None)
        if previous is not None:
            self._in_flight[previous] -= 1
            self._cond.notify_all()


RunOne = Callable[[ShardSpec, Selector], RetryOutcome]


@dataclass(slots=True)
class ShardedRun:
    plan: ShardPlan
    outcomes: dict[int, RetryOutcome] = field(default_factory=dict)

    def ordered_results(self) -> list[tuple[int, dict[str, Any]]]:
        return [(index, self.outcomes[index].result) for index in sorted(self.outcomes)]

    def report(self) -> dict[str, Any]:
        return {
            "job_id": self.plan.job_id,
            "shards": [
                {
                    "index": index,
                    "run_id": outcome.run_id,
                    "worker_id": outcome.worker.worker_id,
                    "attempt": outcome.attempt,
                    "attempts": [a.to_dict() for a in outcome.attempts],
                }
                for index, outcome in sorted(self.outcomes.items())
            ],
        }


def run_sharded(
    plan: ShardPlan,
    *,
    run_one: RunOne,
    list_eligible: ListEligible,
    concurrency: int | None = None,
    balancer: ShardBalancer | None = None,
) -> ShardedRun:
    """Run every active shard to completion, each with its own retries.

    `run_one(shard, select)` runs one shard (normally `run_with_retries`/
    `dispatch_with_retries` using the given selector, so a shard whose worker is lost
    is re-queued to another eligible worker within its retry budget). In-flight
    shards are bounded by the eligible worker count (a Pi takes one job at a time),
    `MAX_SHARD_CONCURRENCY` and `concurrency`. All shards are attempted even if one
    fails; failures raise `ShardedRunError` afterwards, carrying the shards that did
    complete. Raises `NoEligibleWorkerError` up front when no worker is eligible.
    """
    active = plan.active
    run = ShardedRun(plan)
    if not active:
        return run
    initial = list_eligible(frozenset(), None)
    limit = min(len(initial), MAX_SHARD_CONCURRENCY, len(active))
    if concurrency is not None:
        limit = min(limit, max(1, concurrency))
    balancer = balancer or ShardBalancer(list_eligible)

    def work(position: int, shard: ShardSpec) -> RetryOutcome:
        try:
            return run_one(shard, balancer.selector(position, shard.index))
        finally:
            balancer.release(shard.index)

    failures: dict[int, str] = {}
    failed_attempts: dict[int, list[Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, limit)) as pool:
        futures = {
            shard.index: pool.submit(work, position, shard) for position, shard in enumerate(active)
        }
        for index, future in futures.items():
            try:
                run.outcomes[index] = future.result()
            except Exception as exc:
                failures[index] = f"{type(exc).__name__}: {exc}"
                if isinstance(exc, RetriesExhaustedError):
                    failed_attempts[index] = list(exc.attempts)
    if failures:
        raise ShardedRunError(
            f"{len(failures)} of {len(active)} shard(s) of {plan.job_id} failed: "
            + "; ".join(f"shard {i}: {why}" for i, why in sorted(failures.items())),
            failures,
            dict(run.outcomes),
            failed_attempts,
        )
    return run
