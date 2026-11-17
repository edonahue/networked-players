"""Fake-RQ tests for the submit-side lifecycle in `scripts/_platform_client.py`.

No Redis, RQ server, Ansible or worker is touched: `Queue`, the liveness/advertisement
readers and the stop command are replaced by in-memory fakes driven by a fake clock.
"""

from __future__ import annotations

import functools
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from rq.job import JobStatus

from networked_players_platform.models import (
    CapabilityRequirement,
    RunRequest,
    WorkerAdvertisement,
)
from networked_players_platform.retry import RunFailedError, RunLostError

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import _platform_client as client  # noqa: E402

T0 = datetime.now(UTC).replace(microsecond=0)
DIGEST = "e" * 64
COMMIT = "a" * 40
HORSE = "Work-horse terminated unexpectedly; waitpid returned"


class Clock:
    def __init__(self) -> None:
        self.elapsed = 0.0

    def now(self) -> datetime:
        return T0 + timedelta(seconds=self.elapsed)

    def monotonic(self) -> float:
        return self.elapsed

    def sleep(self, seconds: float) -> None:
        self.elapsed += seconds


class FakeJob:
    """Reports `statuses` in order (the last one repeats); `flip_at` lets a status
    change with the fake clock instead."""

    def __init__(
        self,
        job_id: str,
        statuses: list[JobStatus],
        *,
        exc_info: str | None = None,
        result: dict[str, Any] | None = None,
        finish_at: float | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.id = job_id
        self.statuses = list(statuses)
        self.exc_info = exc_info
        self.result = result
        self.cancelled = False
        self.finish_at = finish_at
        self.clock = clock

    def get_status(self, refresh: bool = True) -> JobStatus:
        if self.finish_at is not None and self.clock and self.clock.elapsed >= self.finish_at:
            self.result = {"status": "succeeded", "attempt": 1}
            return JobStatus.FINISHED
        if len(self.statuses) > 1:
            return self.statuses.pop(0)
        return self.statuses[0]

    def cancel(self) -> None:
        self.cancelled = True


class Backend:
    """In-memory model of the RQ/Redis state the client reads and writes."""

    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.jobs_by_queue: dict[str, list[FakeJob]] = {}
        self.enqueued: list[FakeJob] = []
        self.rq_heartbeat: dict[str, Callable[[datetime], datetime | None]] = {}
        self.advertisements: list[WorkerAdvertisement] = []
        self.stops: list[str] = []
        self.heartbeat_error: Exception | None = None

    def queue_class(self) -> Any:
        backend = self

        class FakeQueue:
            def __init__(self, name: str, connection: Any = None) -> None:
                self.name = name

            def enqueue(self, func: str, remote_run: str, **kwargs: Any) -> FakeJob:
                job = backend.jobs_by_queue[self.name].pop(0)
                job.id = kwargs["job_id"]
                job.meta = kwargs["meta"]  # type: ignore[attr-defined]
                backend.enqueued.append(job)
                return job

        return FakeQueue

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(client, "Queue", self.queue_class())

        def heartbeat(store: Any, worker_id: str) -> datetime | None:
            if self.heartbeat_error is not None:
                raise self.heartbeat_error
            return self.rq_heartbeat[worker_id](self.clock.now())

        monkeypatch.setattr(client, "read_rq_worker_heartbeat", heartbeat)
        monkeypatch.setattr(
            client, "read_advertisements_checked", lambda store: (self.advertisements, {})
        )
        monkeypatch.setattr(
            client, "send_stop_job_command", lambda store, job_id: self.stops.append(job_id)
        )
        monkeypatch.setattr(
            client,
            "enqueue_and_wait",
            functools.partial(
                client.enqueue_and_wait,
                sleep=self.clock.sleep,
                monotonic=self.clock.monotonic,
                clock=self.clock.now,
            ),
        )


def _wait(
    backend: Backend, worker_id: str = "worker-a", timeout_seconds: int = 300, **kwargs: Any
) -> dict[str, Any]:
    return client.enqueue_and_wait(
        broker=None,  # type: ignore[arg-type]
        worker_id=worker_id,
        remote_run="~/runs/run-1",
        run_id="run-1",
        timeout_seconds=timeout_seconds,
        workload_id="artifact.validate",
        sleep=backend.clock.sleep,
        monotonic=backend.clock.monotonic,
        clock=backend.clock.now,
        **kwargs,
    )


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch) -> Backend:
    backend = Backend(Clock())
    backend.install(monkeypatch)
    backend.rq_heartbeat["worker-a"] = lambda now: now  # healthy RQ worker
    return backend


def _ad(worker_id: str, now: datetime, *, memory: int = 512) -> WorkerAdvertisement:
    return WorkerAdvertisement(
        schema_version=2,
        worker_id=worker_id,
        observed_at=now.isoformat(),
        architecture="aarch64",
        tags=("validation",),
        total_memory_mb=1024,
        max_job_memory_mb=memory,
        runtime_commit=COMMIT,
        workloads={"artifact.validate": "1"},
        runtime_digests={"artifact.validate": DIGEST},
    )


# --- status mapping ------------------------------------------------------------------


def test_finished_job_returns_the_success_manifest(backend: Backend) -> None:
    job = FakeJob("x", [JobStatus.QUEUED, JobStatus.STARTED, JobStatus.FINISHED])
    job.result = {"status": "succeeded", "attempt": 1}
    backend.jobs_by_queue["networked-players.platform.worker-a"] = [job]
    assert _wait(backend)["status"] == "succeeded"
    assert job.meta["workload_id"] == "artifact.validate" and job.meta["attempt"] == 1  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("status", "exc_info", "retryable", "memory_suspect"),
    [
        (JobStatus.FAILED, f"{HORSE} 9 (signal 9); ", True, True),  # SIGKILL: OOM-suspect
        (JobStatus.FAILED, f"{HORSE} 15 (signal 15); ", True, False),  # restart/redeploy
        (JobStatus.FAILED, "rq.exceptions.AbandonedJobError", True, True),
        (JobStatus.FAILED, "Traceback ... RunExecutionError: digest mismatch", False, False),
        (JobStatus.FAILED, "Task exceeded maximum timeout value (120 seconds)", False, False),
        (JobStatus.STOPPED, "Job stopped by user, work-horse terminated.", False, False),
        (JobStatus.CANCELED, None, False, False),
    ],
)
def test_rq_statuses_map_to_retry_decisions(
    backend: Backend,
    status: JobStatus,
    exc_info: str | None,
    retryable: bool,
    memory_suspect: bool,
) -> None:
    job = FakeJob("x", [JobStatus.STARTED, status], exc_info=exc_info)
    backend.jobs_by_queue["networked-players.platform.worker-a"] = [job]
    with pytest.raises(RunFailedError) as excinfo:
        _wait(backend)
    assert excinfo.value.retryable is retryable
    assert excinfo.value.memory_suspect is memory_suspect
    assert backend.stops == []


def test_success_status_without_a_manifest_is_a_non_retryable_failure(backend: Backend) -> None:
    job = FakeJob("x", [JobStatus.FINISHED], result=None)
    backend.jobs_by_queue["networked-players.platform.worker-a"] = [job]
    with pytest.raises(RunFailedError, match="no valid success manifest") as excinfo:
        _wait(backend)
    assert excinfo.value.retryable is False


# --- lost-worker decisions come from RQ liveness --------------------------------------


def test_dead_rq_worker_with_a_fresh_advertisement_is_lost_and_stop_is_sent(
    backend: Backend,
) -> None:
    # RQ record vanishes at t=20s while the advertisement stays fresh throughout.
    backend.rq_heartbeat["worker-a"] = lambda now: now if (now - T0).total_seconds() < 20 else None
    backend.advertisements = [_ad("worker-a", T0)]
    job = FakeJob("x", [JobStatus.STARTED])
    backend.jobs_by_queue["networked-players.platform.worker-a"] = [job]
    with pytest.raises(RunLostError, match="no live rq:worker record") as excinfo:
        _wait(backend, lost_grace=timedelta(seconds=60))
    assert "advertisement fresh" not in str(excinfo.value) or "fresh" in str(excinfo.value)
    assert backend.stops == ["run-1"]  # RQ liveness lapsed, so a stop is allowed
    assert backend.clock.elapsed >= 80


def test_failing_heartbeat_with_a_live_rq_worker_never_stops_a_healthy_job(
    backend: Backend,
) -> None:
    backend.advertisements = []  # the heartbeat unit is failing: no advertisement at all
    job = FakeJob("x", [JobStatus.STARTED], finish_at=1800.0, clock=backend.clock)
    backend.jobs_by_queue["networked-players.platform.worker-a"] = [job]
    assert _wait(backend, timeout_seconds=3600)["status"] == "succeeded"
    assert backend.stops == [] and not job.cancelled
    assert backend.clock.elapsed >= 1800


def test_queued_job_on_a_dead_rq_worker_is_cancelled_not_stopped(backend: Backend) -> None:
    backend.rq_heartbeat["worker-a"] = lambda now: None
    job = FakeJob("x", [JobStatus.QUEUED])
    backend.jobs_by_queue["networked-players.platform.worker-a"] = [job]
    with pytest.raises(RunLostError):
        _wait(backend, lost_grace=timedelta(seconds=30))
    assert job.cancelled and backend.stops == []


def test_redis_error_during_the_watch_releases_a_queued_job_then_propagates(
    backend: Backend,
) -> None:
    backend.heartbeat_error = ConnectionError("broker went away")
    job = FakeJob("x", [JobStatus.QUEUED])
    backend.jobs_by_queue["networked-players.platform.worker-a"] = [job]
    with pytest.raises(ConnectionError):
        _wait(backend)
    assert job.cancelled


def test_redis_error_never_stops_a_started_job_whose_liveness_is_unknown(
    backend: Backend, capsys: pytest.CaptureFixture[str]
) -> None:
    backend.heartbeat_error = ConnectionError("broker went away")
    job = FakeJob("x", [JobStatus.STARTED])
    backend.jobs_by_queue["networked-players.platform.worker-a"] = [job]
    with pytest.raises(ConnectionError):
        _wait(backend)
    assert backend.stops == [] and not job.cancelled
    assert "could not release orphaned job" in capsys.readouterr().err


def test_release_orphan_respects_rq_liveness(backend: Backend) -> None:
    live_job = FakeJob("live", [JobStatus.STARTED])
    client._release_orphan(None, live_job, JobStatus.STARTED, "worker-a", backend.clock.now())  # type: ignore[arg-type]
    assert backend.stops == []
    backend.rq_heartbeat["worker-a"] = lambda now: None
    client._release_orphan(None, live_job, JobStatus.STARTED, "worker-a", backend.clock.now())  # type: ignore[arg-type]
    assert backend.stops == ["live"]
    queued = FakeJob("q", [JobStatus.QUEUED])
    client._release_orphan(None, queued, JobStatus.QUEUED, "worker-a", backend.clock.now())  # type: ignore[arg-type]
    assert queued.cancelled


# --- dispatch_with_retries -------------------------------------------------------------


def _request(tmp_path: Path) -> tuple[RunRequest, Path]:
    local_run = tmp_path / "local-run"
    local_run.mkdir(exist_ok=True)
    request = RunRequest(
        schema_version=2,
        run_id="run-1",
        workload_id="artifact.validate",
        workload_version="1",
        submitted_at=T0.isoformat(),
        runtime_commit=COMMIT,
        runtime_digest=DIGEST,
        timeout_seconds=300,
        max_retries=0,
        capabilities=CapabilityRequirement(tags=("validation",)),
        inputs=(),
        expected_outputs=("validation-report",),
        parameters={},
    )
    return request, local_run


@pytest.fixture
def dispatch(monkeypatch: pytest.MonkeyPatch, backend: Backend, tmp_path: Path):
    staged: list[str] = []
    monkeypatch.setattr(client, "require_free_disk", lambda **kwargs: None)
    monkeypatch.setattr(client, "stage_run", lambda **kwargs: staged.append(kwargs["remote_run"]))
    backend.advertisements = [_ad("worker-a", T0), _ad("worker-b", T0)]
    backend.rq_heartbeat["worker-b"] = lambda now: now
    hostvars = {
        "host-a": {"platform_worker_id": "worker-a"},
        "host-b": {"platform_worker_id": "worker-b"},
    }

    def run(max_retries: int) -> Any:
        request, local_run = _request(tmp_path)
        return (
            client.dispatch_with_retries(
                broker=None,  # type: ignore[arg-type]
                request=request,
                local_run=local_run,
                inventory_path=tmp_path / "inventory.yml",
                repo_root=tmp_path,
                hostvars=hostvars,
                min_free_disk_gb=0.1,
                max_retries=max_retries,
            ),
            local_run,
        )

    return run, staged


def test_dispatch_retries_a_lost_worker_on_another_worker_with_a_fresh_directory(
    backend: Backend, dispatch: Any
) -> None:
    run, staged = dispatch
    # worker-a is chosen first (alphabetical tie-break), then its RQ record dies.
    backend.rq_heartbeat["worker-a"] = lambda now: now if (now - T0).total_seconds() < 5 else None
    backend.jobs_by_queue["networked-players.platform.worker-a"] = [
        FakeJob("a", [JobStatus.STARTED])
    ]
    backend.jobs_by_queue["networked-players.platform.worker-b"] = [
        FakeJob("b", [JobStatus.FINISHED], result={"status": "succeeded", "attempt": 2})
    ]
    (outcome, host, remote_run), local_run = run(1)
    assert (outcome.attempt, outcome.worker.worker_id, host) == (2, "worker-b", "host-b")
    assert outcome.run_id == "run-1-a2" and remote_run.endswith("/run-1-a2")
    assert staged[0].endswith("/run-1") and staged[1].endswith("/run-1-a2")  # no collision
    assert [o.worker_id for o in outcome.orphans] == ["worker-a"]
    request = json.loads((local_run / "request.json").read_text())
    assert request["attempt"] == 2 and request["retry_of"] == "run-1"
    assert request["max_retries"] == 1
    assert backend.stops == ["run-1"]


def test_dispatch_with_no_retries_fails_with_the_attempt_record(
    backend: Backend, dispatch: Any
) -> None:
    run, _ = dispatch
    backend.rq_heartbeat["worker-a"] = lambda now: now if (now - T0).total_seconds() < 5 else None
    backend.jobs_by_queue["networked-players.platform.worker-a"] = [
        FakeJob("a", [JobStatus.STARTED])
    ]
    with pytest.raises(client.PlatformClientError) as excinfo:
        run(0)
    assert [a["outcome"] for a in excinfo.value.attempts] == ["worker-lost"]
    assert len(backend.enqueued) == 1


def test_dispatch_does_not_retry_a_suspected_oom_on_identical_hardware(
    backend: Backend, dispatch: Any
) -> None:
    run, _ = dispatch
    backend.jobs_by_queue["networked-players.platform.worker-a"] = [
        FakeJob("a", [JobStatus.FAILED], exc_info=f"{HORSE} 9 (signal 9); ")
    ]
    with pytest.raises(client.PlatformClientError, match="possibly out of memory") as excinfo:
        run(2)
    assert [a["outcome"] for a in excinfo.value.attempts] == ["memory-suspect-kill"]


def test_dispatch_retries_a_suspected_oom_on_a_larger_worker(
    backend: Backend, dispatch: Any
) -> None:
    run, _ = dispatch
    backend.advertisements = [_ad("worker-a", T0), _ad("worker-b", T0, memory=900)]
    backend.jobs_by_queue["networked-players.platform.worker-a"] = [
        FakeJob("a", [JobStatus.FAILED], exc_info=f"{HORSE} 9 (signal 9); ")
    ]
    backend.jobs_by_queue["networked-players.platform.worker-b"] = [
        FakeJob("b", [JobStatus.FINISHED], result={"status": "succeeded", "attempt": 2})
    ]
    (outcome, _, _), _ = run(1)
    assert outcome.worker.worker_id == "worker-b" and outcome.attempt == 2


def test_dispatch_never_retries_a_stopped_or_deterministic_failure(
    backend: Backend, dispatch: Any
) -> None:
    run, _ = dispatch
    backend.jobs_by_queue["networked-players.platform.worker-a"] = [
        FakeJob("a", [JobStatus.STOPPED], exc_info="Job stopped by user, work-horse terminated.")
    ]
    with pytest.raises(client.PlatformClientError):
        run(3)
    assert len(backend.enqueued) == 1


def test_dispatch_does_not_route_to_a_worker_whose_rq_process_is_absent(
    backend: Backend, dispatch: Any
) -> None:
    run, _ = dispatch
    backend.rq_heartbeat["worker-a"] = lambda now: None  # fresh advertisement, no RQ worker
    backend.jobs_by_queue["networked-players.platform.worker-b"] = [
        FakeJob("b", [JobStatus.FINISHED], result={"status": "succeeded", "attempt": 1})
    ]
    (outcome, _, _), _ = run(0)
    assert outcome.worker.worker_id == "worker-b"
    backend.rq_heartbeat["worker-b"] = lambda now: None
    with pytest.raises(client.PlatformClientError, match="RQ worker process absent"):
        run(0)


# --- artifact-check records --------------------------------------------------------------


def test_artifact_check_worker_record_persists_attempts_and_orphans() -> None:
    sys.path.insert(0, str(SCRIPTS))
    import submit_artifact_check as submit

    attempts = [
        {"attempt": 1, "run_id": "r", "worker_id": "worker-a", "outcome": "worker-lost"},
        {"attempt": 2, "run_id": "r-a2", "worker_id": "worker-a", "outcome": "succeeded"},
    ]
    report = {
        "valid": True,
        "runtime_commit": COMMIT,
        "runtime_digest": DIGEST,
        "worker_id": "worker-a",
        "attempt": 2,
    }
    record = submit._worker_record(
        job_id="r-a2",
        started_at="t0",
        finished_at="t1",
        job_failed=False,
        result=report,
        ok=True,
        attempts=attempts,
    )
    assert record["attempts"] == attempts
    assert [o["attempt"] for o in record["orphans"]] == [1]
    assert record["result"]["runtime_commit"] == COMMIT  # the surviving record names the code
    failed = submit._worker_record(
        job_id=None,
        started_at="t0",
        finished_at=None,
        job_failed=True,
        result=None,
        ok=False,
        error="no eligible worker",
        attempts=attempts[:1],
    )
    assert failed["orphans"] and failed["error"] == "no eligible worker"
