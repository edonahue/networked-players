#!/usr/bin/env python3
"""Submit a real artifact-validation check through the ADR 0034 capability
platform, fanned out redundantly across every targeted worker (ADR-0034
consolidation of the old scripts/enqueue_*_check.py fleet-validation
family -- see docs/decisions/0056-unify-pi-fleet-checks-onto-capability-
platform.md).

Every one of `packages/platform`'s `artifact.validate` validators does the
same shape of work: read 1 or 2 already-public JSON artifacts, call one
`networked_players_contracts` dependency-free validator, return
`{"valid": bool, "failures": [...]}`. Unlike a normal platform job (one
`select_worker()` pick), this is deliberately REDUNDANT fan-out: the same
check is dispatched independently to every targeted worker, proving each
worker's own environment produces the same result -- not a shard of one
job across workers. Shares its stage/dispatch/fetch/verify machinery with
submit_cohort_score.py/submit_research_platform_job.py via
_platform_client.py, looped per worker here.

Results are written to local/jobs/<validator>-<timestamp>.json only --
never a committed doc (ADR 0018).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from _platform_client import (
    PlatformClientError,
    current_commit,
    enqueue_and_wait,
    fetch_and_verify,
    inventory_group_hosts,
    inventory_hostvars,
    remove_remote_run,
    require_broker_url,
    require_clean_checkout,
    require_free_disk,
    stage_run,
)
from redis import Redis

from networked_players_platform.broker import read_advertisements
from networked_players_platform.models import ArtifactDescriptor, CapabilityRequirement, RunRequest
from networked_players_platform.scheduler import NoEligibleWorkerError, select_worker
from networked_players_platform.staging import describe_artifact

REPO_ROOT = Path(__file__).resolve().parents[1]
INVENTORY = REPO_ROOT / "infra/ansible/inventories/local/hosts.yml"
OUTPUT_DIR = REPO_ROOT / "local" / "jobs"

# Ad hoc, per-invocation artifacts (no fixed known-in-advance location --
# the old cohort-check's shape). Same bound as the old
# scripts/_artifact_staging.py's MAX_COHORT_ARTIFACT_BYTES, for the same
# reason: bounded, human-reviewed cohort-shaped input, not dataset scale.
MAX_AD_HOC_ARTIFACT_BYTES = 8 * 1024 * 1024

_CAPABILITIES = CapabilityRequirement(
    architectures=("aarch64", "x86_64"), tags=("validation",), min_memory_mb=128
)

# validator name -> default artifact path(s), relative to REPO_ROOT, in the
# exact order packages/platform/workloads.py::_artifact_validators expects.
# Real paths, matching the old deploy-*-check-job.yml playbooks' own
# defaults exactly. connectivity/playable-cohort have no default -- an ad
# hoc --artifact is required for those two.
_DEFAULT_ARTIFACTS: dict[str, tuple[str, ...]] = {
    "catalog": ("apps/web/public/data/catalog/albums.v1.json",),
    "album-art": (
        "apps/web/public/data/catalog/album-art.v1.json",
        "apps/web/public/data/catalog/albums.v1.json",
    ),
    "connection-rounds": (
        "apps/web/public/data/game/universe.v1.json",
        "apps/web/public/data/game/rounds.v1.json",
    ),
    "contributor-index": (
        "apps/web/public/data/contributors/index.v1.json",
        "apps/web/public/data/catalog/albums.v1.json",
    ),
    "daily-manifest": (
        "apps/web/public/data/game/daily-manifest.v1.json",
        "apps/web/public/data/game/rounds.v1.json",
    ),
    "pathfinding-graph": (
        "apps/web/public/data/pathfinding/graph.v1.json",
        "apps/web/public/data/catalog/albums.v1.json",
    ),
    "record-routes": (
        "apps/web/public/data/routes/universe.v1.json",
        "apps/web/public/data/routes/rounds.v1.json",
    ),
}
_AD_HOC_VALIDATORS = ("connectivity", "playable-cohort")
_ALL_VALIDATORS = sorted({*_DEFAULT_ARTIFACTS, *_AD_HOC_VALIDATORS})


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validator", required=True, choices=_ALL_VALIDATORS)
    parser.add_argument(
        "--artifact",
        action="append",
        default=[],
        help=(
            "artifact path, in validator order. Required (once) for "
            "connectivity/playable-cohort; optional override(s) for the "
            "other validators, which otherwise use their real committed "
            "default path(s)."
        ),
    )
    parser.add_argument("--workers", default="pi_workers", help="ansible inventory group to target")
    parser.add_argument("--limit", help="debug: target only this single inventory hostname")
    parser.add_argument(
        "--min-free-disk-gb",
        type=float,
        default=0.5,
        help=(
            "refuse to dispatch to a worker with less than this much free "
            "disk (preflight, checked read-only right before staging; see "
            "the zimaworker1 disk-full incident). Lower than the other "
            "submission scripts' default since these payloads are KB-scale."
        ),
    )
    parser.add_argument(
        "--keep-remote",
        action="store_true",
        help="do not delete a worker's remote run directory after a successful fetch (debugging)",
    )
    return parser.parse_args()


def _target_hosts(
    group: str, limit: str | None, *, hostvars: dict[str, dict[str, Any]]
) -> list[str]:
    hosts = inventory_group_hosts(INVENTORY, REPO_ROOT, group)
    if not hosts:
        print(f"ABORT: no hosts in the {group!r} inventory group.", file=sys.stderr)
        raise SystemExit(1)
    if limit is not None:
        if limit not in hosts:
            print(
                f"ABORT: --limit {limit!r} is not in the {group!r} group ({hosts}).",
                file=sys.stderr,
            )
            raise SystemExit(1)
        hosts = [limit]
    missing_worker_id = [
        host for host in hosts if not hostvars.get(host, {}).get("platform_worker_id")
    ]
    if missing_worker_id:
        print(f"ABORT: no platform_worker_id set for {missing_worker_id}.", file=sys.stderr)
        raise SystemExit(1)
    return hosts


def _resolve_artifact_paths(validator: str, artifact_args: list[str]) -> list[Path]:
    if validator in _AD_HOC_VALIDATORS:
        if len(artifact_args) != 1:
            print(f"ABORT: --artifact is required exactly once for {validator!r}.", file=sys.stderr)
            raise SystemExit(1)
        path = Path(artifact_args[0]).resolve()
        if not path.is_file():
            print(f"ABORT: artifact not found: {path}.", file=sys.stderr)
            raise SystemExit(1)
        if path.stat().st_size > MAX_AD_HOC_ARTIFACT_BYTES:
            print(
                f"ABORT: artifact {path} exceeds {MAX_AD_HOC_ARTIFACT_BYTES} bytes.",
                file=sys.stderr,
            )
            raise SystemExit(1)
        return [path]

    defaults = _DEFAULT_ARTIFACTS[validator]
    if artifact_args and len(artifact_args) != len(defaults):
        print(
            f"ABORT: {validator!r} takes exactly {len(defaults)} --artifact override(s).",
            file=sys.stderr,
        )
        raise SystemExit(1)
    chosen = artifact_args or list(defaults)
    paths = []
    for value in chosen:
        path = Path(value)
        if not path.is_absolute():
            path = REPO_ROOT / value
        if not path.is_file():
            print(f"ABORT: artifact not found: {path}.", file=sys.stderr)
            raise SystemExit(1)
        paths.append(path)
    return paths


def _stage_inputs(artifact_paths: list[Path], input_dir: Path) -> tuple[ArtifactDescriptor, ...]:
    input_dir.mkdir(parents=True)
    descriptors = []
    for index, source in enumerate(artifact_paths):
        relative_path = f"artifact-{index}.json"
        shutil.copy2(source, input_dir / relative_path)
        descriptors.append(
            describe_artifact(
                input_dir,
                relative_path,
                name=f"artifact-{index}",
                contract="artifact-check-input-v1",
            )
        )
    return tuple(descriptors)


def _worker_record(
    *,
    job_id: str | None,
    started_at: str,
    finished_at: str | None,
    job_failed: bool,
    result: dict[str, Any] | None,
    ok: bool,
    error: str | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "job_id": job_id,
        "started_at_utc": started_at,
        "finished_at_utc": finished_at,
        "job_failed": job_failed,
        "result": result,
        "ok": ok,
    }
    if error is not None:
        record["error"] = error
    return record


def _check_one_worker(
    *,
    host: str,
    worker_id: str,
    validator: str,
    artifact_paths: list[Path],
    commit: str,
    broker: Redis,
    keep_remote: bool,
    min_free_disk_gb: float,
) -> dict[str, Any]:
    run_id = f"artifact-check-{validator}-{datetime.now(UTC):%Y%m%dt%H%M%Sz}-{uuid.uuid4().hex[:8]}"
    local_run = OUTPUT_DIR / ".runs" / run_id
    started_at = datetime.now(UTC).isoformat()
    inputs = _stage_inputs(artifact_paths, local_run / "input")

    request = RunRequest(
        schema_version=1,
        run_id=run_id,
        workload_id="artifact.validate",
        workload_version="1",
        submitted_at=started_at,
        runtime_commit=commit,
        timeout_seconds=120,
        max_retries=0,
        capabilities=_CAPABILITIES,
        inputs=inputs,
        expected_outputs=("validation-report",),
        parameters={"validator": validator},
    )
    (local_run / "request.json").write_text(
        json.dumps(request.to_dict(), indent=2, sort_keys=True) + "\n"
    )

    workers = [worker for worker in read_advertisements(broker) if worker.worker_id == worker_id]
    try:
        worker = select_worker(
            workers,
            request.capabilities,
            workload_id=request.workload_id,
            workload_version=request.workload_version,
            runtime_commit=request.runtime_commit,
        )
    except NoEligibleWorkerError as exc:
        return _worker_record(
            job_id=None,
            started_at=started_at,
            finished_at=None,
            job_failed=True,
            result=None,
            ok=False,
            error=str(exc),
        )

    try:
        require_free_disk(
            inventory_path=INVENTORY,
            repo_root=REPO_ROOT,
            host=host,
            min_free_gb=min_free_disk_gb,
        )
    except PlatformClientError as exc:
        return _worker_record(
            job_id=run_id,
            started_at=started_at,
            finished_at=None,
            job_failed=True,
            result=None,
            ok=False,
            error=str(exc),
        )

    remote_run = f"~/.local/share/networked-players/platform/runs/{run_id}"
    stage_run(
        inventory_path=INVENTORY,
        repo_root=REPO_ROOT,
        host=host,
        remote_run=remote_run,
        local_run=local_run,
    )

    try:
        result = enqueue_and_wait(
            broker=broker,
            worker_id=worker.worker_id,
            remote_run=remote_run,
            run_id=run_id,
            timeout_seconds=request.timeout_seconds,
        )
    except PlatformClientError as exc:
        finished_at = datetime.now(UTC).isoformat()
        return _worker_record(
            job_id=run_id,
            started_at=started_at,
            finished_at=finished_at,
            job_failed=True,
            result=None,
            ok=False,
            error=str(exc),
        )

    finished_at = datetime.now(UTC).isoformat()
    completed = fetch_and_verify(
        inventory_path=INVENTORY,
        repo_root=REPO_ROOT,
        host=host,
        remote_run=remote_run,
        local_run=local_run,
        result=result,
        save_result_json=False,
    )
    report: dict[str, Any] = json.loads((completed / "validation-report.json").read_text())
    if not keep_remote:
        remove_remote_run(
            inventory_path=INVENTORY, repo_root=REPO_ROOT, host=host, remote_run=remote_run
        )
    return _worker_record(
        job_id=run_id,
        started_at=started_at,
        finished_at=finished_at,
        job_failed=False,
        result=report,
        ok=bool(report.get("valid", False)),
    )


def main() -> int:
    args = _arguments()
    require_clean_checkout(REPO_ROOT)
    commit = current_commit(REPO_ROOT)
    artifact_paths = _resolve_artifact_paths(args.validator, args.artifact)
    hostvars = inventory_hostvars(INVENTORY, REPO_ROOT)
    hosts = _target_hosts(args.workers, args.limit, hostvars=hostvars)

    broker_url = require_broker_url()
    broker = Redis.from_url(broker_url)

    per_worker: dict[str, dict[str, Any]] = {}
    for host in hosts:
        worker_id = hostvars[host]["platform_worker_id"]
        print(f"==> Checking {args.validator!r} on {host} (worker_id={worker_id!r}).")
        per_worker[host] = _check_one_worker(
            host=host,
            worker_id=worker_id,
            validator=args.validator,
            artifact_paths=artifact_paths,
            commit=commit,
            broker=broker,
            keep_remote=args.keep_remote,
            min_free_disk_gb=args.min_free_disk_gb,
        )

    def _display_path(path: Path) -> str:
        return str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path)

    aggregate_ok = bool(per_worker) and all(v["ok"] for v in per_worker.values())
    record = {
        "observed": True,
        "measured_at_utc": datetime.now(UTC).isoformat(),
        "validator": args.validator,
        "artifacts": [_display_path(path) for path in artifact_paths],
        "workers": per_worker,
        "ok": aggregate_ok,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_path = OUTPUT_DIR / f"{args.validator}-check-{timestamp}.json"
    output_path.write_text(json.dumps(record, indent=2, default=str) + "\n")
    print(f"==> Wrote {output_path}.")

    if aggregate_ok:
        print(f"==> PASS: {args.validator!r} is valid on all {len(per_worker)} worker(s).")
        return 0
    failing = {host: v for host, v in per_worker.items() if not v["ok"]}
    print(f"==> FAIL on {sorted(failing)}:")
    for host, v in failing.items():
        failures = v["result"].get("failures") if v["result"] else v.get("error")
        print(f"    {host}: job_failed={v['job_failed']}, failures={failures}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
