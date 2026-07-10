from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from networked_players_platform.cli import main
from networked_players_platform.models import (
    CapabilityRequirement,
    DatasetIdentity,
    WorkerAdvertisement,
)
from networked_players_platform.scheduler import NoEligibleWorkerError, select_worker
from networked_players_platform.staging import describe_artifact, publish_completed_run

COMMIT = "a" * 40
MANIFEST_HASH = "b" * 64


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
