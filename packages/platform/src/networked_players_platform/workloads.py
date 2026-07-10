"""Workload plugin discovery."""

from __future__ import annotations

import importlib.metadata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .models import ArtifactDescriptor, RunRequest, WorkloadSpec

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
    from .staging import describe_artifact

    return (
        describe_artifact(
            output_dir,
            "self-test.json",
            name="self-test",
            contract="platform-self-test-v1",
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
        )
    }
    for entry_point in importlib.metadata.entry_points(group="networked_players.workloads"):
        registered = entry_point.load()()
        if not isinstance(registered, RegisteredWorkload):
            raise TypeError(f"workload entry point {entry_point.name!r} returned the wrong type")
        if registered.spec.workload_id in workloads:
            raise ValueError(f"duplicate workload ID: {registered.spec.workload_id}")
        workloads[registered.spec.workload_id] = registered
    return workloads
