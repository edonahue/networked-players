#!/usr/bin/env python3
"""Submit a real, bounded research workload against a built topic corpus,
through the ADR 0034 capability platform (Phase 3 Slice E).

Mirrors submit_cohort_score.py's real dispatch shape (stage inputs via
Ansible, enqueue via RQ, wait, fetch and verify outputs) -- shared with
that script and submit_artifact_check.py via _platform_client.py -- but
simplified: a topic corpus is small and bounded (a few MB, see
corpus.py), so it is staged directly as run inputs rather than requiring
a pre-replicated worker-local dataset cache (ADR 0023) the way
cohort.score's full canonical dataset does.

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
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
    parser.add_argument(
        "--keep-remote",
        action="store_true",
        help="do not delete the remote run directory after a successful fetch (debugging)",
    )
    return parser.parse_args()


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


def main() -> int:
    args = _arguments()
    require_clean_checkout(REPO_ROOT)
    commit = current_commit(REPO_ROOT)
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
    if not args.keep_remote:
        remove_remote_run(
            inventory_path=INVENTORY, repo_root=REPO_ROOT, host=host, remote_run=remote_run
        )
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
