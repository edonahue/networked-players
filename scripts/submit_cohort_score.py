#!/usr/bin/env python3
"""Submit whole-cohort scoring through the capability platform."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from _platform_client import (
    current_commit,
    enqueue_and_wait,
    fetch_and_verify,
    inventory_hostvars,
    remove_remote_run,
    require_broker_url,
    require_clean_checkout,
    require_free_disk,
    resolve_inventory_host,
    stage_run,
)
from redis import Redis

from networked_players_platform.broker import read_advertisements
from networked_players_platform.models import CapabilityRequirement, DatasetIdentity, RunRequest
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
    parser.add_argument(
        "--max-temp-directory-size",
        default="3GB",
        help=(
            "explicit ceiling on DuckDB's spill directory, so a heavy run's "
            "worst-case disk footprint is bounded instead of implicitly "
            "tracking whatever free space exists on the worker at connect "
            "time (a shared host can otherwise be driven to 0 bytes free "
            "by a single spilling query). Pass '' to fall back to DuckDB's "
            "own default behavior."
        ),
    )
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
    parser.add_argument(
        "--min-free-disk-gb",
        type=float,
        default=2.0,
        help=(
            "refuse to dispatch if the target worker has less than this much "
            "free disk (preflight, checked read-only right before staging; "
            "see the zimaworker1 disk-full incident)"
        ),
    )
    parser.add_argument("--replace", action="store_true")
    parser.add_argument(
        "--keep-remote",
        action="store_true",
        help="do not delete the remote run directory after a successful fetch (debugging)",
    )
    return parser.parse_args()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
            "max_temp_directory_size": args.max_temp_directory_size or None,
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
    require_clean_checkout(REPO_ROOT)
    commit = current_commit(REPO_ROOT)
    # Platform identifiers are lowercase by contract; keep the timestamp
    # readable without introducing uppercase `T`/`Z` characters.
    run_id = f"cohort-score-{datetime.now(UTC):%Y%m%dt%H%M%sz}-{uuid.uuid4().hex[:8]}"
    request, local_run = _request(args, run_id, commit)

    broker_url = require_broker_url()
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
    hostvars = inventory_hostvars(INVENTORY, REPO_ROOT)
    host = resolve_inventory_host(hostvars, worker.worker_id)
    require_free_disk(
        inventory_path=INVENTORY,
        repo_root=REPO_ROOT,
        host=host,
        min_free_gb=args.min_free_disk_gb,
    )
    remote_run = f"~/.local/share/networked-players/platform/runs/{run_id}"
    stage_run(
        inventory_path=INVENTORY,
        repo_root=REPO_ROOT,
        host=host,
        remote_run=remote_run,
        local_run=local_run,
    )

    result = enqueue_and_wait(
        broker=broker,
        worker_id=worker.worker_id,
        remote_run=remote_run,
        run_id=run_id,
        timeout_seconds=request.timeout_seconds,
    )
    completed = fetch_and_verify(
        inventory_path=INVENTORY,
        repo_root=REPO_ROOT,
        host=host,
        remote_run=remote_run,
        local_run=local_run,
        result=result,
    )
    _promote_outputs(
        completed,
        REPO_ROOT / "local/analysis/cohorts" / args.source_id,
        replace=args.replace,
    )
    if not args.keep_remote:
        remove_remote_run(
            inventory_path=INVENTORY, repo_root=REPO_ROOT, host=host, remote_run=remote_run
        )
    print(
        json.dumps(
            {"run_id": run_id, "worker_id": worker.worker_id, "status": "succeeded"}, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
