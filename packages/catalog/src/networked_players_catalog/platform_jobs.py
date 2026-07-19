"""Networked Players domain workloads registered with the generic platform."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from networked_players_graph_core.cohort_scoring import score_cohort_to_directory
from networked_players_platform.models import (
    ArtifactDescriptor,
    CapabilityRequirement,
    RunRequest,
    WorkloadSpec,
)
from networked_players_platform.staging import describe_artifact
from networked_players_platform.workloads import RegisteredWorkload


class CatalogWorkloadError(RuntimeError):
    """Raised when a catalog workload's immutable inputs are unavailable."""


def _manifest_sha256(dataset: Path) -> str:
    return hashlib.sha256((dataset / "manifest.json").read_bytes()).hexdigest()


def _verified_manifest_sha256(dataset: Path) -> str:
    marker = json.loads((dataset / ".verified.json").read_text())
    manifest = json.loads((dataset / "manifest.json").read_text())
    expected = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode("utf-8")).hexdigest()
    if marker.get("manifest_sha256") != expected:
        raise CatalogWorkloadError("worker dataset verification marker is stale")
    return expected


def _cohort_score_handler(
    request: RunRequest, input_dir: Path, output_dir: Path
) -> tuple[ArtifactDescriptor, ...]:
    dataset_root_value = os.environ.get("CATALOG_DATA_DIR", "").strip()
    if not dataset_root_value:
        raise CatalogWorkloadError("CATALOG_DATA_DIR is not configured")
    required = next(
        (dataset for dataset in request.capabilities.datasets if dataset.name == "discogs-onehop"),
        None,
    )
    if required is None:
        raise CatalogWorkloadError("run request has no discogs-onehop dataset identity")
    dataset = Path(dataset_root_value) / required.name / f"snapshot={required.snapshot}"
    if not (dataset / ".verified.json").is_file():
        raise CatalogWorkloadError("required worker-local dataset is not verified")
    if _manifest_sha256(dataset) != required.manifest_sha256:
        raise CatalogWorkloadError("worker dataset manifest hash does not match the run request")
    _verified_manifest_sha256(dataset)

    parameters = request.parameters
    release_format_policy = input_dir / "release-format-policy.json"
    score_cohort_to_directory(
        resolved_path=input_dir / "resolved.json",
        dataset_path=dataset,
        output_dir=output_dir,
        memory_limit=str(parameters.get("memory_limit", "2GB")),
        threads=int(parameters.get("threads", 3)),
        max_artists_per_release=int(parameters.get("max_artists_per_release", 500)),
        max_hops=int(parameters.get("max_hops", 3)),
        max_pairs=int(parameters.get("max_pairs", 1000)),
        max_frontier_expansion=int(parameters.get("max_frontier_expansion", 300)),
        pair_timeout_seconds=float(parameters.get("pair_timeout_seconds", 180.0)),
        max_workers=1,
        max_reach_rows=int(parameters.get("max_reach_rows", 2_000_000)),
        release_format_policy=release_format_policy if release_format_policy.is_file() else None,
    )
    outputs = (
        ("connectivity", "album-cohort-connectivity-v1", "connectivity.json"),
        ("playable-pairs", "cohort-playable-pairs-local-v1", "playable-pairs.json"),
        ("review-report", "cohort-review-report-local-v1", "review-report.md"),
        ("scoring-diagnostics", "cohort-scoring-diagnostics-local-v1", "scoring-diagnostics.json"),
    )
    return tuple(
        describe_artifact(output_dir, path, name=name, contract=contract)
        for name, contract, path in outputs
    )


def cohort_score_workload() -> RegisteredWorkload:
    return RegisteredWorkload(
        spec=WorkloadSpec(
            workload_id="cohort.score",
            version="1",
            default_timeout_seconds=1800,
            max_retries=0,
            capabilities=CapabilityRequirement(
                architectures=("x86_64",),
                tags=("graph", "x86-heavy"),
                min_memory_mb=4096,
            ),
        ),
        handler=_cohort_score_handler,
    )
