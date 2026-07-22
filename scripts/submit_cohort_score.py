#!/usr/bin/env python3
"""Submit whole-cohort scoring through the capability platform."""

from __future__ import annotations

import argparse
import hashlib
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
from networked_players_platform.models import (
    ArtifactDescriptor,
    CapabilityRequirement,
    DatasetIdentity,
    RunRequest,
)
from networked_players_platform.scheduler import select_worker
from networked_players_platform.staging import describe_artifact

REPO_ROOT = Path(__file__).resolve().parents[1]
INVENTORY = REPO_ROOT / "infra/ansible/inventories/local/hosts.yml"
OUTPUTS = (
    "connectivity.json",
    "playable-pairs.json",
    "review-report.md",
    "scoring-diagnostics.json",
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--snapshot-date", required=True)
    parser.add_argument("--worker-id")
    parser.add_argument("--memory-limit", default="2GB")
    parser.add_argument("--threads", type=int, default=3)
    parser.add_argument("--pair-timeout-seconds", type=float, default=180.0)
    parser.add_argument("--max-frontier-expansion", type=int, default=300)
    parser.add_argument("--max-reach-rows", type=int, default=2_000_000)
    parser.add_argument(
        "--release-format-policy",
        type=Path,
        default=None,
        help=(
            "Path to a studio-album-v1 release-format-scoring-index.json "
            "(see build-release-format-scoring-index). Optional: without it, "
            "the run falls back to the legacy title-keyword filter, same as "
            "the local score-cohort-connectivity CLI's own default."
        ),
    )
    parser.add_argument("--replace", action="store_true")
    return parser.parse_args()


def _run(*command: str, capture: bool = False) -> str:
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=capture,
    )
    return completed.stdout if capture else ""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def _request(args: argparse.Namespace, run_id: str, commit: str) -> tuple[RunRequest, Path]:
    analysis_dir = REPO_ROOT / "local/analysis/cohorts" / args.source_id
    resolved = analysis_dir / "resolved.json"
    if not resolved.is_file():
        raise RuntimeError(f"missing resolved cohort: {resolved.relative_to(REPO_ROOT)}")
    dataset = REPO_ROOT / "local/processed/discogs-onehop" / f"snapshot={args.snapshot_date}"
    manifest = dataset / "manifest.json"
    if not manifest.is_file():
        raise RuntimeError(
            f"missing coordinator dataset manifest: {manifest.relative_to(REPO_ROOT)}"
        )
    dataset_identity = DatasetIdentity(
        name="discogs-onehop",
        snapshot=args.snapshot_date,
        manifest_sha256=_sha256(manifest),
    )

    local_run = REPO_ROOT / "local/platform/runs" / run_id
    input_dir = local_run / "input"
    input_dir.mkdir(parents=True)
    shutil.copy2(resolved, input_dir / "resolved.json")
    resolved_descriptor = describe_artifact(
        input_dir,
        "resolved.json",
        name="resolved",
        contract="album-cohort-resolved-v1",
    )
    inputs = (resolved_descriptor,)
    if args.release_format_policy is not None:
        if not args.release_format_policy.is_file():
            raise RuntimeError(f"missing release format policy: {args.release_format_policy}")
        shutil.copy2(args.release_format_policy, input_dir / "release-format-policy.json")
        policy_descriptor = describe_artifact(
            input_dir,
            "release-format-policy.json",
            name="release_format_policy",
            contract="release-format-scoring-index-v1",
        )
        inputs = (resolved_descriptor, policy_descriptor)
    request = RunRequest(
        schema_version=1,
        run_id=run_id,
        workload_id="cohort.score",
        workload_version="1",
        submitted_at=datetime.now(UTC).isoformat(),
        runtime_commit=commit,
        timeout_seconds=1800,
        max_retries=0,
        capabilities=CapabilityRequirement(
            architectures=("x86_64",),
            tags=("graph", "x86-heavy"),
            min_memory_mb=4096,
            datasets=(dataset_identity,),
        ),
        inputs=inputs,
        expected_outputs=(
            "connectivity",
            "playable-pairs",
            "review-report",
            "scoring-diagnostics",
        ),
        parameters={
            "memory_limit": args.memory_limit,
            "threads": args.threads,
            "pair_timeout_seconds": args.pair_timeout_seconds,
            "max_frontier_expansion": args.max_frontier_expansion,
            "max_reach_rows": args.max_reach_rows,
        },
    )
    (local_run / "request.json").write_text(
        json.dumps(request.to_dict(), indent=2, sort_keys=True) + "\n"
    )
    return request, local_run


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
            partial,
            descriptor.relative_path,
            name=descriptor.name,
            contract=descriptor.contract,
        )
        if actual.sha256 != descriptor.sha256 or actual.size_bytes != descriptor.size_bytes:
            raise RuntimeError(f"fetched output {descriptor.name!r} failed verification")
    completed = local_run / "completed"
    os.replace(partial, completed)
    return completed


def _promote_outputs(completed: Path, analysis_dir: Path, *, replace: bool) -> None:
    existing = [analysis_dir / name for name in OUTPUTS if (analysis_dir / name).exists()]
    if existing and not replace:
        names = ", ".join(path.name for path in existing)
        print(f"Fetched and verified run; not replacing existing analysis outputs: {names}")
        print("Re-run with --replace after reviewing the run-specific completed directory.")
        return
    analysis_dir.mkdir(parents=True, exist_ok=True)
    for name in OUTPUTS:
        temporary = analysis_dir / f".{name}.platform-tmp"
        shutil.copy2(completed / name, temporary)
        os.replace(temporary, analysis_dir / name)


def main() -> int:
    args = _arguments()
    if not INVENTORY.is_file():
        raise RuntimeError("private Ansible inventory is missing")
    if _run("git", "status", "--short", capture=True).strip():
        raise RuntimeError("submit scoring only from a clean checkout")
    commit = _run("git", "rev-parse", "HEAD", capture=True).strip()
    # Platform identifiers are lowercase by contract; keep the timestamp
    # readable without introducing uppercase `T`/`Z` characters.
    run_id = f"cohort-score-{datetime.now(UTC):%Y%m%dt%H%M%sz}-{uuid.uuid4().hex[:8]}"
    request, local_run = _request(args, run_id, commit)

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
    _promote_outputs(
        completed,
        REPO_ROOT / "local/analysis/cohorts" / args.source_id,
        replace=args.replace,
    )
    print(
        json.dumps(
            {"run_id": run_id, "worker_id": worker.worker_id, "status": "succeeded"}, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
