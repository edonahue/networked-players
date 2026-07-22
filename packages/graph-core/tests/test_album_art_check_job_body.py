"""Checks the constrained-worker adapter for `album_art_check_job.py`.

Unlike its siblings (cohort/rounds/connection_rounds/record_routes/catalog),
the album-art registry has no separate graph-core-side generation-time
validator to cross-check against -- `album_art_failures`
(`networked_players_contracts.album_art`) is the sole validator, called
directly by both `validate-album-art-registry` and this job body. So this
test proves correct I/O wiring (the job body reads the right files, calls
the real validator, and reports the result faithfully) rather than
two-implementation agreement.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from networked_players_contracts.album_art import album_art_failures, album_art_version

JOB_BODY_PATH = (
    Path(__file__).resolve().parents[3] / "infra" / "ansible" / "files" / "album_art_check_job.py"
)

_SNAPSHOT = "20260601"
_CATALOG_VERSION = "catalog-v1-20260601-abc123abc123"


@pytest.fixture
def job_body_module():
    spec = importlib.util.spec_from_file_location("album_art_check_job", JOB_BODY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["album_art_check_job"] = module
    spec.loader.exec_module(module)
    yield module
    del sys.modules["album_art_check_job"]


def _catalog() -> dict[str, Any]:
    return {
        "catalog_version": _CATALOG_VERSION,
        "snapshot_date": _SNAPSHOT,
        "albums": [
            {"id": "master-1", "main_release_id": 11},
            {"id": "master-2", "main_release_id": 22},
        ],
    }


def _entries() -> list[dict[str, Any]]:
    return [
        {
            "album_id": "master-1",
            "main_release_id": 11,
            "uri150": "https://i.discogs.com/a/150.jpg",
            "uri": "https://i.discogs.com/a/full.jpg",
            "width": 600,
            "height": 600,
        },
    ]


def _registry() -> dict[str, Any]:
    entries = _entries()
    return {
        "schema_version": 1,
        "catalog_version": _CATALOG_VERSION,
        "art_version": album_art_version(entries, _SNAPSHOT),
        "generated_at": "2026-07-22T00:00:00+00:00",
        "source": "Discogs API /releases/{id} images",
        "license": "presentational only",
        "albums": entries,
    }


def _write(tmp_path: Path, name: str, artifact: dict[str, Any]) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(artifact))
    return path


def test_clean_pair_matches(job_body_module, tmp_path: Path) -> None:
    registry = _registry()
    catalog = _catalog()
    registry_path = _write(tmp_path, "album-art.v1.json", registry)
    catalog_path = _write(tmp_path, "albums.v1.json", catalog)

    assert album_art_failures(registry, catalog) == []
    result = job_body_module.check_album_art(str(registry_path), str(catalog_path))
    assert result == {"valid": True, "failures": []}


def test_broken_pair_matches(job_body_module, tmp_path: Path) -> None:
    registry = _registry()
    registry["albums"][0]["uri"] = "http://not-https.example/x.jpg"
    catalog = _catalog()
    registry_path = _write(tmp_path, "album-art.v1.json", registry)
    catalog_path = _write(tmp_path, "albums.v1.json", catalog)

    reference_failures = album_art_failures(copy.deepcopy(registry), copy.deepcopy(catalog))
    assert reference_failures
    result = job_body_module.check_album_art(str(registry_path), str(catalog_path))
    assert result["valid"] is False
    assert result["failures"]
