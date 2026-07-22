"""Cross-checks the constrained-worker adapter against graph-core's public
`validate_album_catalog` on identical inputs. Mirrors
test_connection_rounds_check_job_body.py exactly, adapted for
`catalog_check_job.py`'s single-artifact `check_catalog(catalog_path)` entry
point.

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

from networked_players_contracts.catalog import _catalog_version
from networked_players_graph_core.analysis import (
    AlbumCatalogValidationError,
    validate_album_catalog,
)

JOB_BODY_PATH = (
    Path(__file__).resolve().parents[3] / "infra" / "ansible" / "files" / "catalog_check_job.py"
)

_SNAPSHOT_DATE = "20260601"


@pytest.fixture
def job_body_module():
    spec = importlib.util.spec_from_file_location("catalog_check_job", JOB_BODY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["catalog_check_job"] = module
    spec.loader.exec_module(module)
    yield module
    del sys.modules["catalog_check_job"]


def _album(album_id: str, *, artist_id: int, main_release_id: int) -> dict[str, Any]:
    return {
        "id": album_id,
        "master_id": None,
        "main_release_id": main_release_id,
        "title": album_id.title(),
        "artist_id": artist_id,
        "artist": "Alice",
        "year": 1995,
    }


def _catalog() -> dict[str, Any]:
    albums = [
        _album("master-1", artist_id=100, main_release_id=1),
        _album("master-2", artist_id=200, main_release_id=2),
    ]
    return {
        "catalog_version": _catalog_version(albums, _SNAPSHOT_DATE),
        "snapshot_date": _SNAPSHOT_DATE,
        "generated_by": "networked-players-catalog build-album-catalog 0.1.0",
        "albums": albums,
    }


def _write(tmp_path: Path, name: str, artifact: dict[str, Any]) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(artifact))
    return path


def test_clean_catalog_matches(job_body_module, tmp_path: Path) -> None:
    catalog = _catalog()
    catalog_path = _write(tmp_path, "albums.v1.json", catalog)

    validate_album_catalog(catalog)  # does not raise
    result = job_body_module.check_catalog(str(catalog_path))
    assert result == {"valid": True, "failures": []}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c["albums"].append(copy.deepcopy(c["albums"][0])),
        lambda c: c["albums"][0].__setitem__("main_release_id", -1),
        lambda c: c.__setitem__("catalog_version", "catalog-v1-20260601-000000000000"),
        lambda c: c["albums"][0].pop("title"),
    ],
)
def test_broken_catalog_matches(job_body_module, tmp_path: Path, mutate) -> None:
    catalog = _catalog()
    mutate(catalog)
    catalog_path = _write(tmp_path, "albums.v1.json", catalog)

    with pytest.raises(AlbumCatalogValidationError):
        validate_album_catalog(copy.deepcopy(catalog))
    result = job_body_module.check_catalog(str(catalog_path))
    assert result["valid"] is False
    assert result["failures"]
