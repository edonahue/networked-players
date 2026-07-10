from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from networked_players_platform.broker import publish_advertisement, read_advertisements
from networked_players_platform.cli import main
from networked_players_platform.executor import RunExecutionError, execute_run
from networked_players_platform.models import (
    CapabilityRequirement,
    DatasetIdentity,
    RunRequest,
    WorkerAdvertisement,
)
from networked_players_platform.scheduler import NoEligibleWorkerError, select_worker
from networked_players_platform.staging import describe_artifact, publish_completed_run
from networked_players_platform.workloads import discover_workloads

COMMIT = "a" * 40
MANIFEST_HASH = "b" * 64


class _FakeStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def setex(self, name: str, time: int, value: str) -> None:
        assert time > 0
        self.values[name] = value

    def scan_iter(self, match: str):
        prefix = match.removesuffix("*")
        return (key for key in self.values if key.startswith(prefix))

    def get(self, name: bytes | str) -> bytes | str | None:
        key = name.decode() if isinstance(name, bytes) else name
        return self.values.get(key)


def _worker(
    worker_id: str,
    *,
    observed_at: datetime,
    active_jobs: int = 0,
    architecture: str = "aarch64",
) -> WorkerAdvertisement:
    return WorkerAdvertisement(
        schema_version=1,
        worker_id=worker_id,
        observed_at=observed_at.isoformat(),
        architecture=architecture,
        tags=("validation",),
        total_memory_mb=1024,
        max_job_memory_mb=512,
        runtime_commit=COMMIT,
        workloads={"artifact.validate": "1"},
        datasets=(DatasetIdentity("discogs-onehop", "20260601", MANIFEST_HASH),),
        active_jobs=active_jobs,
    )


def test_scheduler_filters_stale_and_selects_lowest_load() -> None:
    now = datetime(2026, 7, 10, tzinfo=UTC)
    stale = _worker("worker-stale", observed_at=now - timedelta(minutes=3))
    busy = _worker("worker-busy", observed_at=now, active_jobs=1)
    idle = _worker("worker-idle", observed_at=now)
    selected = select_worker(
        [stale, busy, idle],
        CapabilityRequirement(architectures=("aarch64",), tags=("validation",), min_memory_mb=256),
        workload_id="artifact.validate",
        workload_version="1",
        runtime_commit=COMMIT,
        now=now,
    )
    assert selected.worker_id == "worker-idle"


def test_scheduler_requires_exact_dataset_and_runtime() -> None:
    now = datetime(2026, 7, 10, tzinfo=UTC)
    requirement = CapabilityRequirement(
        datasets=(DatasetIdentity("discogs-onehop", "20260601", "c" * 64),)
    )
    with pytest.raises(NoEligibleWorkerError):
        select_worker(
            [_worker("worker-1", observed_at=now)],
            requirement,
            workload_id="artifact.validate",
            workload_version="1",
            runtime_commit=COMMIT,
            now=now,
        )


def test_staging_hashes_and_atomically_publishes(tmp_path: Path) -> None:
    staging = tmp_path / ".run.staging"
    staging.mkdir()
    (staging / "output.json").write_text('{"ok": true}\n')
    descriptor = describe_artifact(staging, "output.json", name="result", contract="synthetic-v1")
    completed = tmp_path / "completed"
    publish_completed_run(staging, completed, result_manifest={"output": descriptor.sha256})
    assert not staging.exists()
    assert json.loads((completed / "result.json").read_text())["output"] == descriptor.sha256
    with pytest.raises(FileExistsError):
        publish_completed_run(tmp_path / ".second.staging", completed, result_manifest={})


def test_cluster_status_reads_local_advertisements(tmp_path: Path, capsys) -> None:
    workers = tmp_path / "workers"
    workers.mkdir()
    worker = _worker("worker-1", observed_at=datetime(2026, 7, 10, tzinfo=UTC))
    (workers / "worker-1.json").write_text(json.dumps(worker.to_dict()))
    assert main(["cluster-status", "--state-dir", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["worker_count"] == 1


def test_broker_round_trips_advertisements() -> None:
    store = _FakeStore()
    worker = _worker("worker-1", observed_at=datetime(2026, 7, 10, tzinfo=UTC))
    publish_advertisement(store, worker)
    assert read_advertisements(store) == [worker]


def test_installed_catalog_workload_is_discoverable() -> None:
    workload = discover_workloads()["cohort.score"]
    assert workload.spec.version == "1"
    assert workload.spec.capabilities.architectures == ("x86_64",)
    assert workload.spec.capabilities.min_memory_mb == 4096


def test_executor_publishes_verified_self_test(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "input").mkdir(parents=True)
    request = RunRequest(
        schema_version=1,
        run_id="self-test-001",
        workload_id="platform.self-test",
        workload_version="1",
        submitted_at="2026-07-10T00:00:00+00:00",
        runtime_commit=COMMIT,
        timeout_seconds=60,
        max_retries=0,
        capabilities=CapabilityRequirement(),
        inputs=(),
        expected_outputs=("self-test",),
        parameters={},
    )
    (run_dir / "request.json").write_text(json.dumps(request.to_dict()))
    monkeypatch.setenv("PLATFORM_RUNTIME_COMMIT", COMMIT)
    monkeypatch.setenv("PLATFORM_WORKER_ID", "worker-1")

    result = execute_run(str(run_dir))
    assert result["status"] == "succeeded"
    assert (run_dir / "completed" / "self-test.json").exists()
    assert not (run_dir / ".output.staging").exists()


def test_executor_records_runtime_mismatch_without_completed_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "input").mkdir(parents=True)
    request = RunRequest(
        schema_version=1,
        run_id="self-test-002",
        workload_id="platform.self-test",
        workload_version="1",
        submitted_at="2026-07-10T00:00:00+00:00",
        runtime_commit=COMMIT,
        timeout_seconds=60,
        max_retries=0,
        capabilities=CapabilityRequirement(),
        inputs=(),
        expected_outputs=("self-test",),
        parameters={},
    )
    (run_dir / "request.json").write_text(json.dumps(request.to_dict()))
    monkeypatch.setenv("PLATFORM_RUNTIME_COMMIT", "d" * 40)
    monkeypatch.setenv("PLATFORM_WORKER_ID", "worker-1")

    with pytest.raises(RunExecutionError, match="commit mismatch"):
        execute_run(str(run_dir))
    assert (run_dir / "failed.json").exists()
    assert not (run_dir / "completed").exists()


def test_executor_runs_dependency_free_artifact_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "validation-run"
    input_dir = run_dir / "input"
    input_dir.mkdir(parents=True)
    (input_dir / "artifact.json").write_text('{"schema_version": 99}\n')
    descriptor = describe_artifact(
        input_dir,
        "artifact.json",
        name="artifact",
        contract="synthetic-json-v1",
    )
    request = RunRequest(
        schema_version=1,
        run_id="validation-001",
        workload_id="artifact.validate",
        workload_version="1",
        submitted_at="2026-07-10T00:00:00+00:00",
        runtime_commit=COMMIT,
        timeout_seconds=120,
        max_retries=1,
        capabilities=CapabilityRequirement(),
        inputs=(descriptor,),
        expected_outputs=("validation-report",),
        parameters={"validator": "connectivity"},
    )
    (run_dir / "request.json").write_text(json.dumps(request.to_dict()))
    monkeypatch.setenv("PLATFORM_RUNTIME_COMMIT", COMMIT)
    monkeypatch.setenv("PLATFORM_WORKER_ID", "worker-1")

    result = execute_run(str(run_dir))

    assert result["status"] == "succeeded"
    report = json.loads((run_dir / "completed" / "validation-report.json").read_text())
    assert report["valid"] is False
    assert report["validator"] == "connectivity"
