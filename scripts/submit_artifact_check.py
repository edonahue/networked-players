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
job across workers. Mirrors submit_research_platform_job.py's real
stage/dispatch/fetch/verify shape, looped per worker.

Results are written to local/jobs/<validator>-<timestamp>.json only --
never a committed doc (ADR 0018).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
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
    return parser.parse_args()


def _run(*command: str, capture: bool = False) -> str:
    completed = subprocess.run(
        command, cwd=REPO_ROOT, check=True, text=True, capture_output=capture
    )
    return completed.stdout if capture else ""


def _inventory_hostvars() -> dict[str, dict[str, Any]]:
    if not INVENTORY.is_file():
        print(f"ABORT: no local inventory at {INVENTORY}.", file=sys.stderr)
        raise SystemExit(1)
    inventory = json.loads(
        _run("uv", "run", "ansible-inventory", "-i", str(INVENTORY), "--list", capture=True)
    )
    hostvars: dict[str, dict[str, Any]] = inventory.get("_meta", {}).get("hostvars", {})
    return hostvars


def _target_hosts(
    group: str, limit: str | None, *, hostvars: dict[str, dict[str, Any]]
) -> list[str]:
    inventory = json.loads(
        _run("uv", "run", "ansible-inventory", "-i", str(INVENTORY), "--list", capture=True)
    )
    hosts = sorted(inventory.get(group, {}).get("hosts", []))
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


def _ansible(host: str, module: str, arguments: str) -> None:
    _run("uv", "run", "ansible", host, "-i", str(INVENTORY), "-m", module, "-a", arguments)


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


def _fetch_and_verify(
    host: str, remote_run: str, local_run: Path, result: dict[str, Any]
) -> dict[str, Any]:
    partial = local_run / ".completed.partial"
    partial.mkdir()
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
    report: dict[str, Any] = json.loads((partial / "validation-report.json").read_text())
    os.replace(partial, local_run / "completed")
    return report


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
            return _worker_record(
                job_id=job.id,
                started_at=started_at,
                finished_at=datetime.now(UTC).isoformat(),
                job_failed=True,
                result=None,
                ok=False,
            )
        time.sleep(2)
    else:
        return _worker_record(
            job_id=job.id,
            started_at=started_at,
            finished_at=datetime.now(UTC).isoformat(),
            job_failed=True,
            result=None,
            ok=False,
            error="timed out",
        )

    finished_at = datetime.now(UTC).isoformat()
    result = job.result
    if not isinstance(result, dict) or result.get("status") != "succeeded":
        return _worker_record(
            job_id=job.id,
            started_at=started_at,
            finished_at=finished_at,
            job_failed=True,
            result=result,
            ok=False,
        )
    report = _fetch_and_verify(host, remote_run, local_run, result)
    return _worker_record(
        job_id=job.id,
        started_at=started_at,
        finished_at=finished_at,
        job_failed=False,
        result=report,
        ok=bool(report.get("valid", False)),
    )


def main() -> int:
    args = _arguments()
    if not INVENTORY.is_file():
        raise RuntimeError("private Ansible inventory is missing")
    if _run("git", "status", "--short", capture=True).strip():
        raise RuntimeError("submit an artifact check only from a clean checkout")
    commit = _run("git", "rev-parse", "HEAD", capture=True).strip()
    artifact_paths = _resolve_artifact_paths(args.validator, args.artifact)
    hostvars = _inventory_hostvars()
    hosts = _target_hosts(args.workers, args.limit, hostvars=hostvars)

    broker_url = os.environ.get("JOBS_BROKER_URL", "")
    if not broker_url:
        raise RuntimeError("JOBS_BROKER_URL is required")
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
