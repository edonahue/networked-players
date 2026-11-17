"""Run one verified workload in an isolated, run-specific directory."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .digest import installed_digest_report
from .models import RunRequest, RunResult
from .staging import describe_artifact, publish_completed_run
from .workloads import load_workload


class RunExecutionError(RuntimeError):
    """Raised when a run cannot safely start or publish."""


def _verify_inputs(request: RunRequest, input_dir: Path) -> None:
    for expected in request.inputs:
        actual = describe_artifact(
            input_dir,
            expected.relative_path,
            name=expected.name,
            contract=expected.contract,
        )
        if actual.sha256 != expected.sha256 or actual.size_bytes != expected.size_bytes:
            raise RunExecutionError(f"input {expected.name!r} failed size/SHA-256 verification")


def _write_failure(run_dir: Path, request: RunRequest, exc: Exception) -> None:
    payload = {
        "schema_version": 1,
        "run_id": request.run_id,
        "status": "failed",
        "failed_at": datetime.now(UTC).isoformat(),
        "error_type": type(exc).__name__,
        "error": str(exc),
        "attempt": request.attempt,
        "worker_id": os.environ.get("PLATFORM_WORKER_ID", ""),
        "workload_id": request.workload_id,
        "run_dir": str(run_dir),
    }
    temporary = run_dir / ".failed.json.tmp"
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, run_dir / "failed.json")


def execute_run(run_dir_value: str) -> dict[str, Any]:
    """RQ entry point. Only a run directory crosses the queue boundary."""
    run_dir = Path(run_dir_value).expanduser().resolve()
    request = RunRequest.from_dict(json.loads((run_dir / "request.json").read_text()))
    started_at = datetime.now(UTC).isoformat()
    try:
        runtime_commit = os.environ.get("PLATFORM_RUNTIME_COMMIT", "")
        worker_id = os.environ.get("PLATFORM_WORKER_ID", "")
        if not worker_id:
            raise RunExecutionError("PLATFORM_WORKER_ID is not configured")
        # ADR 0073: the eligibility key is the runtime digest of the code installed
        # here, not the git commit (which is recorded, not compared).
        if not request.runtime_digest:
            raise RunExecutionError(
                "request carries no runtime digest (schema 1); resubmit with a current client"
            )
        digests, digest_errors = installed_digest_report()
        worker_digest = digests.get(request.workload_id)
        if worker_digest is None:
            detail = digest_errors.get(request.workload_id, "not computed")
            raise RunExecutionError(
                f"worker has no runtime digest for {request.workload_id} ({detail}); "
                "redeploy the runtime"
            )
        if worker_digest != request.runtime_digest:
            raise RunExecutionError(
                f"request/runtime digest mismatch: worker {worker_digest} != "
                f"request {request.runtime_digest}"
            )
        _verify_inputs(request, run_dir / "input")

        # Verified digest first, then import ONLY this workload (no other plugin runs).
        workload = load_workload(request.workload_id)
        if workload is None or workload.spec.version != request.workload_version:
            raise RunExecutionError(
                f"workload {request.workload_id}@{request.workload_version} is not installed"
            )
        staging_dir = run_dir / ".output.staging"
        if staging_dir.exists() or (run_dir / "completed").exists():
            raise RunExecutionError("run output already exists; refusing reuse")
        outputs = workload.handler(request, run_dir / "input", staging_dir)
        output_names = {item.name for item in outputs}
        if output_names != set(request.expected_outputs):
            raise RunExecutionError(
                f"workload outputs {sorted(output_names)} do not match expected "
                f"{sorted(request.expected_outputs)}"
            )

        result = RunResult(
            schema_version=2,
            run_id=request.run_id,
            worker_id=worker_id,
            status="succeeded",
            started_at=started_at,
            ended_at=datetime.now(UTC).isoformat(),
            runtime_commit=runtime_commit,
            outputs=outputs,
            runtime_digest=worker_digest,
            attempt=request.attempt,
        )
        publish_completed_run(staging_dir, run_dir / "completed", result_manifest=result.to_dict())
        return result.to_dict()
    except Exception as exc:
        _write_failure(run_dir, request, exc)
        raise
