#!/usr/bin/env python3
"""Submit a real, bounded research workload against a built topic corpus,
through the ADR 0034 capability platform (Phase 3 Slice E).

Mirrors submit_cohort_score.py's real dispatch shape (stage inputs via
Ansible, enqueue via RQ, wait, fetch and verify outputs) but simplified:
a topic corpus is small and bounded (a few MB, see corpus.py), so it is
staged directly as run inputs rather than requiring a pre-replicated
worker-local dataset cache (ADR 0023) the way cohort.score's full
canonical dataset does.

`research.corpus-check` is validation-class (tags=("validation",),
min_memory_mb=128) -- eligible on the Pi fleet as well as x86, matching
this project's "Pi jobs are bounded validation only" rule.
`research.graph-metrics` is x86-only/heavy -- a bounded co-credit degree
distribution, never full graph analytics (those stay local, see
graph_analysis.py).

Results are fetched to local/research/<topic>/platform-runs/<run-id>/ only
-- never promoted anywhere automatically (ADR 0054's research/publication
boundary).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from redis import Redis
from rq import Queue
from rq.job import JobStatus

from networked_players_platform.broker import queue_name, read_advertisements
from networked_players_platform.models import ArtifactDescriptor, CapabilityRequirement, RunRequest
from networked_players_platform.scheduler import select_worker
from networked_players_platform.staging import describe_artifact

REPO_ROOT = Path(__file__).resolve().parents[1]
INVENTORY = REPO_ROOT / "infra/ansible/inventories/local/hosts.yml"

_WORKLOADS: dict[str, dict[str, Any]] = {
    "corpus-check": {
        "workload_id": "research.corpus-check",
        "workload_version": "1",
        "capabilities": CapabilityRequirement(
            architectures=("aarch64", "x86_64"), tags=("validation",), min_memory_mb=128
        ),
        "expected_outputs": ("corpus-check-report",),
        "timeout_seconds": 120,
    },
    "graph-metrics": {
        "workload_id": "research.graph-metrics",
        "workload_version": "1",
        "capabilities": CapabilityRequirement(
            architectures=("x86_64",), tags=("graph", "x86-heavy"), min_memory_mb=1024
        ),
        "expected_outputs": ("degree-distribution",),
        "timeout_seconds": 600,
    },
}


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workload", required=True, choices=sorted(_WORKLOADS))
    parser.add_argument("--topic", required=True, help="topic slug, e.g. jamiroquai")
    parser.add_argument("--worker-id", help="restrict dispatch to one advertised worker_id")
    return parser.parse_args()


def _run(*command: str, capture: bool = False) -> str:
    completed = subprocess.run(
        command, cwd=REPO_ROOT, check=True, text=True, capture_output=capture
    )
    return completed.stdout if capture else ""


def _inventory_host(worker_id: str) -> str:
    inventory = json.loads(
        _run("uv", "run", "ansible-inventory", "-i", str(INVENTORY), "--list", capture=True)
    )
    hostvars = inventory.get("_meta", {}).get("hostvars", {})
    matches = [
        host for host, values in hostvars.items() if values.get("platform_worker_id") == worker_id
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"worker_id {worker_id!r} does not map to exactly one private inventory host"
        )
    return str(matches[0])


def _ansible(host: str, module: str, arguments: str) -> None:
    _run("uv", "run", "ansible", host, "-i", str(INVENTORY), "-m", module, "-a", arguments)


def _corpus_snapshot_dir(topic_slug: str) -> Path:
    corpus_root = REPO_ROOT / "local/research" / topic_slug / "corpus"
    snapshots = sorted(corpus_root.glob("snapshot=*"))
    if not snapshots:
        raise RuntimeError(f"no built corpus for topic {topic_slug!r} under {corpus_root}")
    return snapshots[-1]


def _input_relative_paths(workload: str, snapshot_dir: Path) -> list[str]:
    if workload == "corpus-check":
        return [
            "manifest.json",
            *sorted(
                f"{path.parent.name}/{path.name}" for path in snapshot_dir.glob("table=*/*.parquet")
            ),
        ]
    return ["table=releases/part-00000.parquet", "table=credits/part-00000.parquet"]


def _stage_inputs(
    workload: str, snapshot_dir: Path, input_dir: Path
) -> tuple[ArtifactDescriptor, ...]:
    input_dir.mkdir(parents=True)
    descriptors = []
    for relative_path in _input_relative_paths(workload, snapshot_dir):
        destination = input_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(snapshot_dir / relative_path, destination)
        safe_name = relative_path.replace("/", "-").replace("=", "-")
        descriptors.append(
            describe_artifact(
                input_dir, relative_path, name=safe_name, contract="research-platform-input-v1"
            )
        )
    return tuple(descriptors)


def _fetch_and_verify(host: str, remote_run: str, local_run: Path, result: dict[str, Any]) -> Path:
    partial = local_run / ".completed.partial"
    partial.mkdir()
    _ansible(
        host,
        "fetch",
        f"src={remote_run}/completed/result.json dest={partial / 'result.json'} flat=yes",
    )
    for output in result["outputs"]:
        descriptor = ArtifactDescriptor(**output)
        destination = partial / descriptor.relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        _ansible(
            host,
            "fetch",
            f"src={remote_run}/completed/{descriptor.relative_path} dest={destination} flat=yes",
        )
        actual = describe_artifact(
            partial, descriptor.relative_path, name=descriptor.name, contract=descriptor.contract
        )
        if actual.sha256 != descriptor.sha256 or actual.size_bytes != descriptor.size_bytes:
            raise RuntimeError(f"fetched output {descriptor.name!r} failed verification")
    completed = local_run / "completed"
    os.replace(partial, completed)
    return completed


def main() -> int:
    args = _arguments()
    if not INVENTORY.is_file():
        raise RuntimeError("private Ansible inventory is missing")
    if _run("git", "status", "--short", capture=True).strip():
        raise RuntimeError("submit a research platform job only from a clean checkout")
    commit = _run("git", "rev-parse", "HEAD", capture=True).strip()
    spec = _WORKLOADS[args.workload]
    snapshot_dir = _corpus_snapshot_dir(args.topic)

    run_id = f"research-{args.workload}-{datetime.now(UTC):%Y%m%dt%H%M%sz}-{uuid.uuid4().hex[:8]}"
    local_run = REPO_ROOT / "local/research" / args.topic / "platform-runs" / run_id
    inputs = _stage_inputs(args.workload, snapshot_dir, local_run / "input")

    request = RunRequest(
        schema_version=1,
        run_id=run_id,
        workload_id=spec["workload_id"],
        workload_version=spec["workload_version"],
        submitted_at=datetime.now(UTC).isoformat(),
        runtime_commit=commit,
        timeout_seconds=spec["timeout_seconds"],
        max_retries=0,
        capabilities=spec["capabilities"],
        inputs=inputs,
        expected_outputs=spec["expected_outputs"],
        parameters={},
    )
    (local_run / "request.json").write_text(
        json.dumps(request.to_dict(), indent=2, sort_keys=True) + "\n"
    )

    broker_url = os.environ.get("JOBS_BROKER_URL", "")
    if not broker_url:
        raise RuntimeError("JOBS_BROKER_URL is required")
    broker = Redis.from_url(broker_url)
    workers = read_advertisements(broker)
    if args.worker_id:
        workers = [worker for worker in workers if worker.worker_id == args.worker_id]
    worker = select_worker(
        workers,
        request.capabilities,
        workload_id=request.workload_id,
        workload_version=request.workload_version,
        runtime_commit=request.runtime_commit,
    )
    host = _inventory_host(worker.worker_id)
    remote_run = f"~/.local/share/networked-players/platform/runs/{run_id}"
    _ansible(host, "file", f"path={remote_run}/input state=directory mode=0755")
    _ansible(
        host, "copy", f"src={local_run / 'request.json'} dest={remote_run}/request.json mode=0644"
    )
    _ansible(host, "copy", f"src={local_run / 'input'}/ dest={remote_run}/input/ mode=0644")

    queue = Queue(queue_name(worker.worker_id), connection=broker)
    job = queue.enqueue(
        "networked_players_platform.executor.execute_run",
        remote_run,
        job_id=run_id,
        job_timeout=request.timeout_seconds,
        result_ttl=604800,
        failure_ttl=2592000,
        retry=None,
    )
    deadline = time.monotonic() + request.timeout_seconds + 60
    while time.monotonic() < deadline:
        status = job.get_status(refresh=True)
        if status == JobStatus.FINISHED:
            break
        if status in {JobStatus.FAILED, JobStatus.CANCELED, JobStatus.STOPPED}:
            raise RuntimeError(f"remote run ended with status {status.value}: {job.exc_info}")
        time.sleep(2)
    else:
        raise RuntimeError("timed out waiting for remote run completion")

    result = job.result
    if not isinstance(result, dict) or result.get("status") != "succeeded":
        raise RuntimeError("remote run returned no valid success manifest")
    completed = _fetch_and_verify(host, remote_run, local_run, result)
    print(
        json.dumps(
            {
                "run_id": run_id,
                "worker_id": worker.worker_id,
                "status": "succeeded",
                "completed_dir": str(completed.relative_to(REPO_ROOT)),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
