"""Cross-checks the constrained-worker adapter (Phase 2 follow-up slice --
issue #53's fleet-canary gap) against the dependency-free contract
validators on identical inputs. Mirrors test_catalog_check_job_body.py's
pattern, adapted for public_artifact_check_job.py's two entry points
(check_contributor_index, check_pathfinding_graph), which share one job
body file since both are small "published artifact against the catalog"
checks.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from networked_players_contracts.catalog import _catalog_version
from networked_players_contracts.contributor_index import (
    contributor_index_failures,
    contributor_index_version,
)
from networked_players_contracts.pathfinding_graph import (
    pathfinding_graph_failures,
    pathfinding_graph_version,
)

JOB_BODY_PATH = (
    Path(__file__).resolve().parents[3]
    / "infra"
    / "ansible"
    / "files"
    / "public_artifact_check_job.py"
)

_SNAPSHOT = "20260601"


@pytest.fixture
def job_body_module():
    spec = importlib.util.spec_from_file_location("public_artifact_check_job", JOB_BODY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["public_artifact_check_job"] = module
    spec.loader.exec_module(module)
    yield module
    del sys.modules["public_artifact_check_job"]


def _catalog() -> dict[str, Any]:
    albums = [
        {
            "id": "master-1",
            "master_id": None,
            "main_release_id": 1,
            "title": "First Light",
            "artist_id": 100,
            "artist": "Alice",
            "year": 1995,
        },
        {
            "id": "master-2",
            "master_id": None,
            "main_release_id": 2,
            "title": "Second Wave",
            "artist_id": 200,
            "artist": "Bob",
            "year": 1998,
        },
    ]
    return {
        "catalog_version": _catalog_version(albums, _SNAPSHOT),
        "snapshot_date": _SNAPSHOT,
        "generated_by": "networked-players-catalog build-album-catalog 0.1.0",
        "albums": albums,
    }


def _contributors() -> list[dict[str, Any]]:
    return [
        {
            "artist_id": 100,
            "name": "Alice",
            "role_categories": ["strings"],
            "role_text_examples": ["Guitar"],
            "albums": ["master-1", "master-2"],
            "decade_activity": [1990],
            "connection_count": 1,
            "neighboring_contributor_ids": [200],
            "evidence": [{"release_id": 1, "role_text": "Guitar"}],
        },
        {
            "artist_id": 200,
            "name": "Bob",
            "role_categories": ["strings"],
            "role_text_examples": ["Bass"],
            "albums": ["master-1", "master-2"],
            "decade_activity": [1990],
            "connection_count": 1,
            "neighboring_contributor_ids": [100],
            "evidence": [{"release_id": 1, "role_text": "Bass"}],
        },
    ]


def _contributor_index(catalog: dict[str, Any]) -> dict[str, Any]:
    contributors = _contributors()
    return {
        "schema_version": 1,
        "catalog_version": catalog["catalog_version"],
        "contributor_index_version": contributor_index_version(contributors, _SNAPSHOT),
        "generated_at": "2026-08-03T00:00:00+00:00",
        "source": "Derived from challenge.v2.json and routes artifacts.",
        "license": "See docs/DATA_AND_RIGHTS.md.",
        "contributors": contributors,
    }


def _pathfinding_graph(catalog: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "catalog_version": catalog["catalog_version"],
        "snapshot_date": _SNAPSHOT,
        "generated_at": "2026-08-03T00:00:00+00:00",
        "source": "Discogs monthly data dump (CC0), one-hop working set.",
        "license": "See docs/DATA_AND_RIGHTS.md.",
        "node_ids": [100, 200, 300],
        "names": ["Alice", "Bob", "Carol"],
        "offsets": [0, 2, 3, 4],
        "neighbors": [1, 2, 0, 0],
        "evidence_release_ids": [1, 2, 1, 2],
        "edge_role_a": ["Guitar", "Producer", "Bass", "Vocals"],
        "edge_role_b": ["Bass", "Vocals", "Guitar", "Producer"],
    }
    payload["pathfinding_graph_version"] = pathfinding_graph_version(payload, _SNAPSHOT)
    return payload


def _write(tmp_path: Path, name: str, payload: dict[str, Any]) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload))
    return path


def test_clean_contributor_index_matches(job_body_module, tmp_path: Path) -> None:
    catalog = _catalog()
    index = _contributor_index(catalog)
    index_path = _write(tmp_path, "contributor-index.v1.json", index)
    catalog_path = _write(tmp_path, "albums.v1.json", catalog)

    assert contributor_index_failures(index, catalog) == []
    result = job_body_module.check_contributor_index(str(index_path), str(catalog_path))
    assert result == {"valid": True, "failures": []}


def test_broken_contributor_index_matches(job_body_module, tmp_path: Path) -> None:
    catalog = _catalog()
    index = deepcopy(_contributor_index(catalog))
    index["catalog_version"] = "catalog-v1-wrong"
    index_path = _write(tmp_path, "contributor-index.v1.json", index)
    catalog_path = _write(tmp_path, "albums.v1.json", catalog)

    reference_failures = contributor_index_failures(index, catalog)
    assert reference_failures
    result = job_body_module.check_contributor_index(str(index_path), str(catalog_path))
    assert result["valid"] is False
    assert result["failures"] == reference_failures


def test_clean_pathfinding_graph_matches(job_body_module, tmp_path: Path) -> None:
    catalog = _catalog()
    graph = _pathfinding_graph(catalog)
    graph_path = _write(tmp_path, "pathfinding-graph.v1.json", graph)
    catalog_path = _write(tmp_path, "albums.v1.json", catalog)

    assert pathfinding_graph_failures(graph, catalog) == []
    result = job_body_module.check_pathfinding_graph(str(graph_path), str(catalog_path))
    assert result == {"valid": True, "failures": []}


def test_broken_pathfinding_graph_matches(job_body_module, tmp_path: Path) -> None:
    catalog = _catalog()
    graph = deepcopy(_pathfinding_graph(catalog))
    graph["catalog_version"] = "catalog-v1-wrong"
    graph_path = _write(tmp_path, "pathfinding-graph.v1.json", graph)
    catalog_path = _write(tmp_path, "albums.v1.json", catalog)

    reference_failures = pathfinding_graph_failures(graph, catalog)
    assert reference_failures
    result = job_body_module.check_pathfinding_graph(str(graph_path), str(catalog_path))
    assert result["valid"] is False
    assert result["failures"] == reference_failures


def test_main_dispatches_by_artifact_type(job_body_module, tmp_path, capsys) -> None:
    catalog = _catalog()
    index = _contributor_index(catalog)
    index_path = _write(tmp_path, "contributor-index.v1.json", index)
    catalog_path = _write(tmp_path, "albums.v1.json", catalog)

    old_argv = sys.argv
    sys.argv = [
        "public_artifact_check_job.py",
        "contributor-index",
        str(index_path),
        str(catalog_path),
    ]
    try:
        job_body_module.main()
    finally:
        sys.argv = old_argv

    result = json.loads(capsys.readouterr().out)
    assert result == {"valid": True, "failures": []}
