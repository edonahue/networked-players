"""Tests for scripts/_fleet_check.py -- the shared enqueue/collect/aggregate
fan-out logic every scripts/enqueue_*_check.py script uses. Exercises the
real fan-out semantics (every targeted worker gets its own job on its own
queue, a burst worker is launched only for the hosts actually targeted, the
aggregate passes only if every worker's result does) against fake in-memory
queues/jobs -- no real Redis, no real Pi fleet.

Loads scripts/_fleet_check.py via importlib.util.spec_from_file_location
(mirrors packages/graph-core/tests/test_record_routes_check_job_body.py's
pattern for loading a file outside any installed package), since `scripts/`
is a folder of standalone operator scripts, not a package.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

FLEET_CHECK_PATH = Path(__file__).resolve().parents[1] / "_fleet_check.py"


@pytest.fixture
def fleet_check():
    spec = importlib.util.spec_from_file_location("_fleet_check", FLEET_CHECK_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_fleet_check"] = module
    spec.loader.exec_module(module)
    yield module
    del sys.modules["_fleet_check"]


class FakeJob:
    def __init__(self, job_id: str, result: Any, *, failed: bool = False) -> None:
        self.id = job_id
        self._result = result
        self._failed = failed
        self.refresh_count = 0

    def refresh(self) -> None:
        self.refresh_count += 1

    @property
    def is_finished(self) -> bool:
        return not self._failed

    @property
    def is_failed(self) -> bool:
        return self._failed

    @property
    def result(self) -> Any:
        return self._result


class NeverDoneJob(FakeJob):
    @property
    def is_finished(self) -> bool:
        return False

    @property
    def is_failed(self) -> bool:
        return False


class FakeRegistry:
    def __init__(self) -> None:
        self.count = 0


class FakeQueue:
    def __init__(self, name: str, *, next_job: FakeJob) -> None:
        self.name = name
        self._next_job = next_job
        self.enqueue_calls: list[tuple[str, tuple[Any, ...], int]] = []
        self.started_job_registry = FakeRegistry()
        self.failed_job_registry = FakeRegistry()

    def __len__(self) -> int:
        return 0

    def enqueue(self, job_function: str, *args: Any, job_timeout: int) -> FakeJob:
        self.enqueue_calls.append((job_function, args, job_timeout))
        return self._next_job


def _make_queue_factory(
    queue_prefix: str, per_host: dict[str, tuple[Any, bool]]
) -> tuple[Any, dict[str, FakeQueue]]:
    """per_host maps hostname -> (job result, job_failed)."""
    created: dict[str, FakeQueue] = {}

    def factory(name: str) -> FakeQueue:
        host = name.removeprefix(f"{queue_prefix}-")
        result, failed = per_host[host]
        queue = FakeQueue(name, next_job=FakeJob(f"job-{host}", result, failed=failed))
        created[host] = queue
        return queue

    return factory, created


def test_every_targeted_worker_gets_its_own_job_on_its_own_queue(fleet_check) -> None:
    per_host = {
        "worker-01": ({"valid": True, "failures": []}, False),
        "worker-02": ({"valid": True, "failures": []}, False),
    }
    factory, created = _make_queue_factory("catalog-check", per_host)

    per_worker = fleet_check.enqueue_and_collect(
        workers=["worker-01", "worker-02"],
        queue_prefix="catalog-check",
        job_function="catalog_check_job.check_catalog",
        job_args=("albums.v1.json",),
        job_timeout=60,
        queue_factory=factory,
        launch_burst_workers=lambda hosts, prefix: None,
    )

    assert set(per_worker) == {"worker-01", "worker-02"}
    assert created["worker-01"].name == "catalog-check-worker-01"
    assert created["worker-02"].enqueue_calls == [
        ("catalog_check_job.check_catalog", ("albums.v1.json",), 60)
    ]


def test_all_workers_passing_is_an_aggregate_pass(fleet_check) -> None:
    per_host = {
        "worker-01": ({"valid": True, "failures": []}, False),
        "worker-02": ({"valid": True, "failures": []}, False),
    }
    factory, _created = _make_queue_factory("catalog-check", per_host)

    per_worker = fleet_check.enqueue_and_collect(
        workers=["worker-01", "worker-02"],
        queue_prefix="catalog-check",
        job_function="catalog_check_job.check_catalog",
        job_args=("albums.v1.json",),
        job_timeout=60,
        queue_factory=factory,
        launch_burst_workers=lambda hosts, prefix: None,
    )

    assert all(v["ok"] for v in per_worker.values())
    path = fleet_check.write_report(prefix="catalog-check", extra={}, per_worker=per_worker)
    assert json.loads(path.read_text())["ok"] is True


def test_any_worker_failing_its_check_fails_the_aggregate(
    fleet_check, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(fleet_check, "OUTPUT_DIR", tmp_path)
    per_host = {
        "worker-01": ({"valid": True, "failures": []}, False),
        "worker-02": ({"valid": False, "failures": ["mode mismatch"]}, False),
    }
    factory, _created = _make_queue_factory("catalog-check", per_host)

    per_worker = fleet_check.enqueue_and_collect(
        workers=["worker-01", "worker-02"],
        queue_prefix="catalog-check",
        job_function="catalog_check_job.check_catalog",
        job_args=("albums.v1.json",),
        job_timeout=60,
        queue_factory=factory,
        launch_burst_workers=lambda hosts, prefix: None,
    )

    assert per_worker["worker-01"]["ok"] is True
    assert per_worker["worker-02"]["ok"] is False
    assert per_worker["worker-02"]["result"]["failures"] == ["mode mismatch"]

    path = fleet_check.write_report(prefix="catalog-check", extra={}, per_worker=per_worker)
    assert json.loads(path.read_text())["ok"] is False


def test_a_failed_rq_job_is_not_ok_even_with_no_result(fleet_check) -> None:
    per_host = {"worker-01": (None, True)}
    factory, _created = _make_queue_factory("catalog-check", per_host)

    per_worker = fleet_check.enqueue_and_collect(
        workers=["worker-01"],
        queue_prefix="catalog-check",
        job_function="catalog_check_job.check_catalog",
        job_args=("albums.v1.json",),
        job_timeout=60,
        queue_factory=factory,
        launch_burst_workers=lambda hosts, prefix: None,
    )

    assert per_worker["worker-01"]["job_failed"] is True
    assert per_worker["worker-01"]["ok"] is False


def test_burst_workers_are_launched_only_for_the_targeted_hosts(fleet_check) -> None:
    per_host = {"worker-02": ({"valid": True, "failures": []}, False)}
    factory, _created = _make_queue_factory("catalog-check", per_host)
    launched: list[tuple[list[str], str]] = []

    fleet_check.enqueue_and_collect(
        workers=["worker-02"],
        queue_prefix="catalog-check",
        job_function="catalog_check_job.check_catalog",
        job_args=("albums.v1.json",),
        job_timeout=60,
        queue_factory=factory,
        launch_burst_workers=lambda hosts, prefix: launched.append((hosts, prefix)),
    )

    assert launched == [(["worker-02"], "catalog-check")]


def test_enqueue_and_collect_aborts_if_a_job_never_finishes(fleet_check) -> None:
    def factory(name: str) -> FakeQueue:
        return FakeQueue(name, next_job=NeverDoneJob("stuck", None))

    with pytest.raises(SystemExit):
        fleet_check.enqueue_and_collect(
            workers=["worker-01"],
            queue_prefix="catalog-check",
            job_function="catalog_check_job.check_catalog",
            job_args=("albums.v1.json",),
            job_timeout=60,
            queue_factory=factory,
            launch_burst_workers=lambda hosts, prefix: None,
            wait_timeout_s=0.05,
            poll_interval_s=0.01,
        )


def test_enqueue_and_collect_aborts_with_no_workers(fleet_check) -> None:
    with pytest.raises(SystemExit):
        fleet_check.enqueue_and_collect(
            workers=[],
            queue_prefix="catalog-check",
            job_function="catalog_check_job.check_catalog",
            job_args=("albums.v1.json",),
            job_timeout=60,
            queue_factory=lambda name: FakeQueue(name, next_job=FakeJob("x", None)),
            launch_burst_workers=lambda hosts, prefix: None,
        )


def test_assert_queues_empty_aborts_if_any_worker_queue_is_dirty(fleet_check) -> None:
    clean = FakeQueue("prefix-worker-01", next_job=FakeJob("x", None))
    dirty = FakeQueue("prefix-worker-02", next_job=FakeJob("y", None))
    dirty.started_job_registry.count = 1

    with pytest.raises(SystemExit):
        fleet_check.assert_queues_empty({"worker-01": clean, "worker-02": dirty})


def test_run_burst_workers_limits_to_the_given_hosts_only(fleet_check, monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(fleet_check.subprocess, "run", lambda cmd, check: calls.append(cmd))

    fleet_check.run_burst_workers(["worker-01", "worker-03"], "catalog-check")

    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[1:] == ["--limit", "worker-01,worker-03", "-e", "rq_queue_name=catalog-check"]


def test_resolve_target_workers_returns_the_full_group_by_default(fleet_check, monkeypatch) -> None:
    monkeypatch.setattr(fleet_check, "load_workers", lambda group: ["worker-01", "worker-02"])
    assert fleet_check.resolve_target_workers("pi_workers", None) == ["worker-01", "worker-02"]


def test_resolve_target_workers_limit_narrows_to_one_host(fleet_check, monkeypatch) -> None:
    monkeypatch.setattr(fleet_check, "load_workers", lambda group: ["worker-01", "worker-02"])
    assert fleet_check.resolve_target_workers("pi_workers", "worker-02") == ["worker-02"]


def test_resolve_target_workers_rejects_a_limit_outside_the_group(fleet_check, monkeypatch) -> None:
    monkeypatch.setattr(fleet_check, "load_workers", lambda group: ["worker-01"])
    with pytest.raises(SystemExit):
        fleet_check.resolve_target_workers("pi_workers", "not-a-real-worker")


def test_write_report_writes_every_targeted_worker_and_an_aggregate(
    fleet_check, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(fleet_check, "OUTPUT_DIR", tmp_path)
    per_worker = {
        "worker-01": {
            "job_id": "j1",
            "started_at_utc": "t0",
            "finished_at_utc": "t1",
            "job_failed": False,
            "result": {"valid": True, "failures": []},
            "ok": True,
        },
    }

    path = fleet_check.write_report(
        prefix="catalog-check",
        extra={"catalog_artifact": "albums.v1.json"},
        per_worker=per_worker,
    )

    written = json.loads(path.read_text())
    assert written["ok"] is True
    assert written["catalog_artifact"] == "albums.v1.json"
    assert written["workers"] == per_worker
