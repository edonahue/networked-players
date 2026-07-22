"""Cross-checks the constrained-worker adapter against graph-core's public
`validate_connection_daily_manifest` on identical inputs. Mirrors
test_connection_rounds_check_job_body.py exactly, adapted for
`daily_manifest_check_job.py` and its two-argument
`check_connection_daily_manifest(manifest_path, rounds_path)` entry point.

Comparison is behavioral (does the reference function raise vs. does the
mirror report invalid), not exact failure-string equality.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from networked_players_contracts.connection_rounds import round_content_fingerprint
from networked_players_graph_core.connection_daily_manifest import (
    CONNECTION_DAILY_MANIFEST_MODE,
    CONNECTION_DAILY_MANIFEST_SCHEMA_VERSION,
    ConnectionDailyManifestError,
    validate_connection_daily_manifest,
)

JOB_BODY_PATH = (
    Path(__file__).resolve().parents[3]
    / "infra"
    / "ansible"
    / "files"
    / "daily_manifest_check_job.py"
)

_CATALOG_VERSION = "catalog-v1-20260601-abc123abc123"
_POOL_VERSION = "connection-v1-20260601-def456def456"
_ARTIFACT_VERSION = "connection-artifact-v1-20260601-aaa111aaa111"


@pytest.fixture
def job_body_module():
    spec = importlib.util.spec_from_file_location("daily_manifest_check_job", JOB_BODY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["daily_manifest_check_job"] = module
    spec.loader.exec_module(module)
    yield module
    del sys.modules["daily_manifest_check_job"]


def _round() -> dict[str, Any]:
    return {
        "id": "conn-0000000001",
        "pool": "real-records",
        "kind": "one_hop",
        "difficulty": "hard",
        "endpoints": [
            {
                "id": "album-a",
                "title": "First Light",
                "year": 1995,
                "act": "Alice",
                "label": None,
                "art": None,
            },
            {
                "id": "album-c",
                "title": "Third Wave",
                "year": 1996,
                "act": "Cara",
                "label": None,
                "art": None,
            },
        ],
        "answer_set": [{"id": 700, "name": "Xavier", "role_category": "guitar"}],
        "distractors": [],
        "clues": [],
        "evidence": [],
        "provenance_note": "Real records: derived from the Discogs monthly data dump (CC0).",
    }


def _rounds_artifact() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "provenance": {
            "catalog_version": _CATALOG_VERSION,
            "pool_version": _POOL_VERSION,
            "artifact_version": _ARTIFACT_VERSION,
        },
        "rounds": [_round()],
    }


def _manifest() -> dict[str, Any]:
    round_json = _round()
    return {
        "schema_version": CONNECTION_DAILY_MANIFEST_SCHEMA_VERSION,
        "mode": CONNECTION_DAILY_MANIFEST_MODE,
        "catalog_version": _CATALOG_VERSION,
        "pool_version": _POOL_VERSION,
        "artifact_version": _ARTIFACT_VERSION,
        "generated_at": "2026-07-22T00:00:00+00:00",
        "start_date": "2026-07-22",
        "schedule": [
            {
                "date": "2026-07-22",
                "round_id": round_json["id"],
                "round_fingerprint": round_content_fingerprint(round_json),
            }
        ],
    }


def _write(tmp_path: Path, name: str, artifact: dict[str, Any]) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(artifact))
    return path


def test_clean_pair_matches(job_body_module, tmp_path: Path) -> None:
    manifest = _manifest()
    rounds = _rounds_artifact()
    manifest_path = _write(tmp_path, "daily-manifest.v1.json", manifest)
    rounds_path = _write(tmp_path, "connection-rounds.v1.json", rounds)

    validate_connection_daily_manifest(manifest, rounds)  # does not raise
    result = job_body_module.check_connection_daily_manifest(str(manifest_path), str(rounds_path))
    assert result == {"valid": True, "failures": []}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda m, r: m.__setitem__("mode", "record_routes"),
        lambda m, r: m.__setitem__("pool_version", "connection-v1-20260601-000000000000"),
        lambda m, r: m["schedule"][0].__setitem__("round_fingerprint", "rfp-0000000000000000"),
        lambda m, r: m.update(extra_top_level_key="nope"),
    ],
)
def test_broken_pair_matches(job_body_module, tmp_path: Path, mutate) -> None:
    manifest = _manifest()
    rounds = _rounds_artifact()
    mutate(manifest, rounds)
    manifest_path = _write(tmp_path, "daily-manifest.v1.json", manifest)
    rounds_path = _write(tmp_path, "connection-rounds.v1.json", rounds)

    with pytest.raises(ConnectionDailyManifestError):
        validate_connection_daily_manifest(copy.deepcopy(manifest), copy.deepcopy(rounds))
    result = job_body_module.check_connection_daily_manifest(str(manifest_path), str(rounds_path))
    assert result["valid"] is False
    assert result["failures"]
