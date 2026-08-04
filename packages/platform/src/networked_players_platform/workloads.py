"""Workload plugin discovery."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .models import ArtifactDescriptor, CapabilityRequirement, RunRequest, WorkloadSpec
from .staging import describe_artifact

WorkloadHandler = Callable[[RunRequest, Path, Path], tuple[ArtifactDescriptor, ...]]


@dataclass(frozen=True, slots=True)
class RegisteredWorkload:
    spec: WorkloadSpec
    handler: WorkloadHandler


def _self_test_handler(
    request: RunRequest, input_dir: Path, output_dir: Path
) -> tuple[ArtifactDescriptor, ...]:
    del request, input_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "self-test.json").write_text('{"ok": true}\n')
    return (
        describe_artifact(
            output_dir,
            "self-test.json",
            name="self-test",
            contract="platform-self-test-v1",
        ),
    )


def _artifact_validate_handler(
    request: RunRequest, input_dir: Path, output_dir: Path
) -> tuple[ArtifactDescriptor, ...]:
    """Validate one JSON artifact using the dependency-free public contracts."""
    from networked_players_contracts import connectivity_failures, playable_cohort_failures

    validator = request.parameters.get("validator")
    validators = {
        "connectivity": connectivity_failures,
        "playable-cohort": playable_cohort_failures,
    }
    if validator not in validators:
        raise ValueError("validator must be connectivity or playable-cohort")
    if len(request.inputs) != 1:
        raise ValueError("artifact.validate requires exactly one input")

    input_path = input_dir / request.inputs[0].relative_path
    artifact = json.loads(input_path.read_text())
    if not isinstance(artifact, dict):
        raise ValueError("validation input must be a JSON object")
    failures = validators[validator](artifact)
    output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": 1,
        "validator": validator,
        "valid": not failures,
        "failures": failures,
    }
    (output_dir / "validation-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    return (
        describe_artifact(
            output_dir,
            "validation-report.json",
            name="validation-report",
            contract="platform-validation-report-v1",
        ),
    )


def _research_corpus_check_handler(
    request: RunRequest, input_dir: Path, output_dir: Path
) -> tuple[ArtifactDescriptor, ...]:
    """Verify a topic corpus's real on-disk checksums/sizes against its own
    `manifest.json` (Phase 3 Slice E) -- a bounded schema/checksum audit,
    the same "small-partition audit" class of work every Pi job in this
    project is restricted to. Deliberately pure stdlib (`hashlib`/`json`
    only, like `artifact.validate` above) so it ships to every worker,
    Pi included, the moment the platform runtime itself is redeployed --
    no `networked-players-research`/DuckDB install needed on the Pi fleet
    for this workload specifically."""
    del request
    manifest_path = input_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    failures: list[str] = []
    for entry in manifest.get("files", []):
        relative_path = entry["path"]
        file_path = input_dir / relative_path
        if not file_path.is_file():
            failures.append(f"missing file: {relative_path}")
            continue
        digest = hashlib.sha256()
        with file_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != entry["sha256"]:
            failures.append(f"checksum mismatch: {relative_path}")
        if file_path.stat().st_size != entry["size_bytes"]:
            failures.append(f"size mismatch: {relative_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": 1,
        "valid": not failures,
        "failures": failures,
        "file_count": len(manifest.get("files", [])),
    }
    (output_dir / "corpus-check-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    return (
        describe_artifact(
            output_dir,
            "corpus-check-report.json",
            name="corpus-check-report",
            contract="platform-research-corpus-check-report-v1",
        ),
    )


def discover_workloads() -> dict[str, RegisteredWorkload]:
    workloads = {
        "platform.self-test": RegisteredWorkload(
            spec=WorkloadSpec(
                workload_id="platform.self-test",
                version="1",
                default_timeout_seconds=60,
                max_retries=1,
            ),
            handler=_self_test_handler,
        ),
        "artifact.validate": RegisteredWorkload(
            spec=WorkloadSpec(
                workload_id="artifact.validate",
                version="1",
                default_timeout_seconds=120,
                max_retries=1,
                capabilities=CapabilityRequirement(
                    architectures=("aarch64", "x86_64"),
                    tags=("validation",),
                    min_memory_mb=128,
                ),
            ),
            handler=_artifact_validate_handler,
        ),
        "research.corpus-check": RegisteredWorkload(
            spec=WorkloadSpec(
                workload_id="research.corpus-check",
                version="1",
                default_timeout_seconds=120,
                max_retries=1,
                capabilities=CapabilityRequirement(
                    architectures=("aarch64", "x86_64"),
                    tags=("validation",),
                    min_memory_mb=128,
                ),
            ),
            handler=_research_corpus_check_handler,
        ),
    }
    for entry_point in importlib.metadata.entry_points(group="networked_players.workloads"):
        registered = entry_point.load()()
        if not isinstance(registered, RegisteredWorkload):
            raise TypeError(f"workload entry point {entry_point.name!r} returned the wrong type")
        if registered.spec.workload_id in workloads:
            raise ValueError(f"duplicate workload ID: {registered.spec.workload_id}")
        workloads[registered.spec.workload_id] = registered
    return workloads
