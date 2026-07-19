from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from networked_players_catalog import platform_jobs
from networked_players_platform.models import (
    CapabilityRequirement,
    DatasetIdentity,
    RunRequest,
)

RUNTIME_COMMIT = "a" * 40


def _write_verified_dataset(catalog_data_dir: Path) -> DatasetIdentity:
    """Write a minimal .verified.json-marked dataset, mirroring ADR 0025's worker cache shape."""
    dataset = catalog_data_dir / "discogs-onehop" / "snapshot=20260601"
    dataset.mkdir(parents=True)
    manifest = {"snapshot_date": "20260601", "counts": {"releases": 0}}
    manifest_path = dataset / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    canonical_sha256 = hashlib.sha256(
        json.dumps(manifest, sort_keys=True).encode("utf-8")
    ).hexdigest()
    (dataset / ".verified.json").write_text(json.dumps({"manifest_sha256": canonical_sha256}))
    return DatasetIdentity(
        name="discogs-onehop", snapshot="20260601", manifest_sha256=manifest_sha256
    )


def _request(dataset_identity: DatasetIdentity) -> RunRequest:
    return RunRequest(
        schema_version=1,
        run_id="cohort-score-test",
        workload_id="cohort.score",
        workload_version="1",
        submitted_at="2026-07-19T00:00:00+00:00",
        runtime_commit=RUNTIME_COMMIT,
        timeout_seconds=1800,
        max_retries=0,
        capabilities=CapabilityRequirement(
            architectures=("x86_64",),
            tags=("graph", "x86-heavy"),
            min_memory_mb=4096,
            datasets=(dataset_identity,),
        ),
        inputs=(),
        expected_outputs=(
            "connectivity",
            "playable-pairs",
            "review-report",
            "scoring-diagnostics",
        ),
        parameters={},
    )


@pytest.fixture
def handler_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[RunRequest, Path, Path, list[dict[str, Any]]]:
    catalog_data_dir = tmp_path / "catalog-data"
    dataset_identity = _write_verified_dataset(catalog_data_dir)
    monkeypatch.setenv("CATALOG_DATA_DIR", str(catalog_data_dir))

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "resolved.json").write_text("{}")

    output_dir = tmp_path / "output"
    output_dir.mkdir()

    calls: list[dict[str, Any]] = []

    def fake_score_cohort_to_directory(**kwargs: Any) -> None:
        calls.append(kwargs)
        (output_dir / "connectivity.json").write_text("{}")
        (output_dir / "playable-pairs.json").write_text("{}")
        (output_dir / "review-report.md").write_text("# report\n")
        (output_dir / "scoring-diagnostics.json").write_text("{}")

    monkeypatch.setattr(platform_jobs, "score_cohort_to_directory", fake_score_cohort_to_directory)

    request = _request(dataset_identity)
    return request, input_dir, output_dir, calls


def test_cohort_score_handler_without_release_format_policy(
    handler_context: tuple[RunRequest, Path, Path, list[dict[str, Any]]],
) -> None:
    request, input_dir, output_dir, calls = handler_context

    platform_jobs._cohort_score_handler(request, input_dir, output_dir)

    assert len(calls) == 1
    assert calls[0]["release_format_policy"] is None


def test_cohort_score_handler_forwards_release_format_policy(
    handler_context: tuple[RunRequest, Path, Path, list[dict[str, Any]]],
) -> None:
    request, input_dir, output_dir, calls = handler_context
    policy_path = input_dir / "release-format-policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "policy_name": "studio-album-v1",
                "policy_version": 1,
                "snapshot_date": "20260601",
                "kind": "release-format-scoring-index",
                "allowed_release_ids": [1, 2, 3],
            }
        )
    )

    platform_jobs._cohort_score_handler(request, input_dir, output_dir)

    assert len(calls) == 1
    assert calls[0]["release_format_policy"] == policy_path
