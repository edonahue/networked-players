"""Real test coverage for scripts/enqueue_verify_challenge.py's dispatch
logic -- sharding, per-worker queue naming, the empty-queue precondition,
job-collection/timeout behavior, and result aggregation. Previously
untested (only its job body, infra/ansible/files/verify_challenge_job.py,
had drift-prevention tests via test_verify_job_body.py); scripts/tests/ is
empty and was dropped from pyproject.toml's testpaths during the ADR-0056
cutover, so this lives alongside the sibling job-body test instead, using
the same importlib.util.spec_from_file_location pattern.

No real Redis/RQ broker is used anywhere here -- Queue/Job are faked with
minimal stub classes exposing exactly the attributes the script reads.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "enqueue_verify_challenge.py"


@pytest.fixture
def enqueue_module():
    spec = importlib.util.spec_from_file_location("enqueue_verify_challenge", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["enqueue_verify_challenge"] = module
    spec.loader.exec_module(module)
    yield module
    del sys.modules["enqueue_verify_challenge"]


# -- shard_path_ids ----------------------------------------------------------


def test_shard_path_ids_splits_into_exact_size_chunks(enqueue_module) -> None:
    assert enqueue_module.shard_path_ids(["a", "b", "c", "d"], 2) == [["a", "b"], ["c", "d"]]


def test_shard_path_ids_keeps_a_remainder_shard(enqueue_module) -> None:
    assert enqueue_module.shard_path_ids(["a", "b", "c"], 2) == [["a", "b"], ["c"]]


def test_shard_path_ids_handles_a_shard_size_larger_than_the_input(enqueue_module) -> None:
    assert enqueue_module.shard_path_ids(["a", "b"], 10) == [["a", "b"]]


def test_shard_path_ids_on_empty_input_is_no_shards(enqueue_module) -> None:
    assert enqueue_module.shard_path_ids([], 4) == []


# -- queue_name_for ------------------------------------------------------------


def test_queue_name_for_matches_the_real_naming_convention(enqueue_module) -> None:
    assert enqueue_module.queue_name_for("verify-challenge", "pi-a") == "verify-challenge-pi-a"


# -- assert_queue_empty --------------------------------------------------------


class _FakeRegistry:
    def __init__(self, count: int) -> None:
        self.count = count


class _FakeQueue:
    def __init__(self, name: str, *, queued: int = 0, started: int = 0, failed: int = 0) -> None:
        self.name = name
        self._queued = queued
        self.started_job_registry = _FakeRegistry(started)
        self.failed_job_registry = _FakeRegistry(failed)

    def __len__(self) -> int:
        return self._queued


def test_assert_queue_empty_passes_on_a_genuinely_empty_queue(enqueue_module) -> None:
    enqueue_module.assert_queue_empty(_FakeQueue("q"), "q")  # no raise


@pytest.mark.parametrize("kwargs", [{"queued": 1}, {"started": 1}, {"failed": 1}])
def test_assert_queue_empty_aborts_on_any_dirty_queue(enqueue_module, kwargs) -> None:
    with pytest.raises(SystemExit):
        enqueue_module.assert_queue_empty(_FakeQueue("q", **kwargs), "q")


# -- wait_for_jobs --------------------------------------------------------------


class _FakeJob:
    """Starts pending; becomes finished (or failed) after `settle_after`
    calls to `refresh()`. `settle_after=0` means already settled when
    fetched, matching a job RQ already completed before the first poll."""

    def __init__(self, job_id: str, *, settle_after: int = 0, fails: bool = False) -> None:
        self.id = job_id
        self._settle_after = settle_after
        self._refreshes = 0
        self._fails = fails
        self.is_finished = False
        self.is_failed = False
        self._settle_if_ready()

    def refresh(self) -> None:
        self._refreshes += 1
        self._settle_if_ready()

    def _settle_if_ready(self) -> None:
        if self._refreshes >= self._settle_after:
            self.is_failed = self._fails
            self.is_finished = not self._fails


def test_wait_for_jobs_returns_once_every_job_is_finished(enqueue_module, monkeypatch) -> None:
    jobs = {
        "a": _FakeJob("a", settle_after=0),
        "b": _FakeJob("b", settle_after=1),
    }
    monkeypatch.setattr(enqueue_module.Job, "fetch", lambda job_id, connection: jobs[job_id])
    monkeypatch.setattr(enqueue_module.time, "sleep", lambda _s: None)

    result = enqueue_module.wait_for_jobs(object(), ["a", "b"])

    assert {job.id for job in result} == {"a", "b"}
    assert all(job.is_finished for job in result)


def test_wait_for_jobs_treats_a_failed_job_as_done_not_pending(enqueue_module, monkeypatch) -> None:
    jobs = {"a": _FakeJob("a", settle_after=0, fails=True)}
    monkeypatch.setattr(enqueue_module.Job, "fetch", lambda job_id, connection: jobs[job_id])
    monkeypatch.setattr(enqueue_module.time, "sleep", lambda _s: None)

    result = enqueue_module.wait_for_jobs(object(), ["a"])

    assert result[0].is_failed is True


def test_wait_for_jobs_aborts_when_a_job_never_finishes(enqueue_module, monkeypatch) -> None:
    stuck = _FakeJob("a", settle_after=10_000)
    monkeypatch.setattr(
        enqueue_module.Job, "fetch", lambda job_id, connection: {"a": stuck}[job_id]
    )
    monkeypatch.setattr(enqueue_module.time, "sleep", lambda _s: None)
    # Real WAIT_TIMEOUT_S is 240s; shorten it so this test doesn't hang or
    # take real wall-clock time waiting to prove the timeout path.
    monkeypatch.setattr(enqueue_module, "WAIT_TIMEOUT_S", 0.0)

    with pytest.raises(SystemExit):
        enqueue_module.wait_for_jobs(object(), ["a"])


# -- build_run_record -----------------------------------------------------------


class _ResultJob:
    def __init__(self, job_id: str, *, result: dict | None, failed: bool = False) -> None:
        self.id = job_id
        self.result = result
        self.is_finished = result is not None
        self.is_failed = failed


def test_build_run_record_is_ok_on_an_all_clean_run(enqueue_module, tmp_path: Path) -> None:
    enqueued = [("pi-a", ["p1"], _ResultJob("j1", result={"failures": []}))]
    finished = [_ResultJob("j1", result={"failures": []})]

    record = enqueue_module.build_run_record(
        artifact_path=tmp_path / "challenge.v3.json",
        workers=["pi-a"],
        enqueued=enqueued,
        finished_jobs=finished,
    )

    assert record["ok"] is True
    assert record["shard_count"] == 1
    assert record["job_failures"] == []
    assert record["evidence_failures"] == []


def test_build_run_record_surfaces_evidence_failures_from_a_shards_result(
    enqueue_module, tmp_path: Path
) -> None:
    enqueued = [("pi-a", ["p1"], _ResultJob("j1", result={"failures": ["bad evidence"]}))]
    finished = [_ResultJob("j1", result={"failures": ["bad evidence"]})]

    record = enqueue_module.build_run_record(
        artifact_path=tmp_path / "challenge.v3.json",
        workers=["pi-a"],
        enqueued=enqueued,
        finished_jobs=finished,
    )

    assert record["ok"] is False
    assert record["evidence_failures"] == ["bad evidence"]
    assert record["job_failures"] == []


def test_build_run_record_surfaces_a_failed_job_with_no_result(
    enqueue_module, tmp_path: Path
) -> None:
    enqueued = [("pi-a", ["p1"], _ResultJob("j1", result=None, failed=True))]
    finished = [_ResultJob("j1", result=None, failed=True)]

    record = enqueue_module.build_run_record(
        artifact_path=tmp_path / "challenge.v3.json",
        workers=["pi-a"],
        enqueued=enqueued,
        finished_jobs=finished,
    )

    assert record["ok"] is False
    assert record["job_failures"] == ["j1"]
    assert record["shards"][0]["result"] is None
