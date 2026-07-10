"""Hashing and atomic publication for run-local outputs."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .models import ArtifactDescriptor


def describe_artifact(
    root: Path, relative_path: str, *, name: str, contract: str
) -> ArtifactDescriptor:
    path = root / relative_path
    if not path.is_file():
        raise FileNotFoundError(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return ArtifactDescriptor(
        name=name,
        contract=contract,
        relative_path=relative_path,
        sha256=digest.hexdigest(),
        size_bytes=path.stat().st_size,
    )


def publish_completed_run(
    staging_dir: Path,
    completed_dir: Path,
    *,
    result_manifest: dict[str, Any],
) -> None:
    """Publish a completed run without exposing partial output as success."""
    if completed_dir.exists():
        raise FileExistsError(completed_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = staging_dir / "result.json"
    temporary = staging_dir / ".result.json.tmp"
    temporary.write_text(json.dumps(result_manifest, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, manifest_path)
    os.replace(staging_dir, completed_dir)
