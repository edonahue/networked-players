from __future__ import annotations

from copy import deepcopy
from typing import Any

from networked_players_contracts.prominence import prominence_failures, prominence_version

_SNAPSHOT = "20260601"
_CATALOG_VERSION = "catalog-v1-20260601-test"
_GRAPH_VERSION = "pathfinding-graph-v4-20260601-test"


def _pathfinding_graph() -> dict[str, Any]:
    return {
        "schema_version": 4,
        "catalog_version": _CATALOG_VERSION,
        "snapshot_date": _SNAPSHOT,
        "pathfinding_graph_version": _GRAPH_VERSION,
        "node_ids": [-1, 100, 200],
    }


def _prominence(pathfinding_graph: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "catalog_version": _CATALOG_VERSION,
        "pathfinding_graph_version": _GRAPH_VERSION,
        "generated_at": "2026-09-03T00:00:00+00:00",
        "source": "test",
        "license": "test",
        "node_ids": [-1, 100, 200],
        "degree": [1, 2, 1],
        "albums_1hop": [0, 1, 1],
        "albums_2hop": [0, 0, 0],
        "evidence_releases": [0, 1, 1],
        "role_diversity": [0, 1, 1],
        "first_year": [None, 1995, 1995],
        "last_year": [None, 1995, 1995],
        "rank": [0, 60, 60],
    }
    payload["prominence_version"] = prominence_version(payload, pathfinding_graph["snapshot_date"])
    return payload


def test_clean_payload_has_no_failures() -> None:
    graph = _pathfinding_graph()
    assert prominence_failures(_prominence(graph), graph) == []


def test_rejects_non_object_inputs() -> None:
    assert prominence_failures(None, {}) == ["prominence artifact must be an object"]
    assert prominence_failures({}, None) == ["pathfinding_graph must be an object"]


def test_rejects_unexpected_top_level_keys() -> None:
    graph = _pathfinding_graph()
    broken = _prominence(graph)
    broken["extra_field"] = 1
    failures = prominence_failures(broken, graph)
    assert any("unexpected top-level keys" in f for f in failures)


def test_rejects_wrong_schema_version() -> None:
    graph = _pathfinding_graph()
    broken = _prominence(graph)
    broken["schema_version"] = 2
    failures = prominence_failures(broken, graph)
    assert any("schema_version must be 1" in f for f in failures)


def test_rejects_catalog_version_mismatch() -> None:
    graph = _pathfinding_graph()
    broken = _prominence(graph)
    broken["catalog_version"] = "catalog-v1-20260601-other"
    failures = prominence_failures(broken, graph)
    assert any("catalog_version" in f for f in failures)


def test_rejects_pathfinding_graph_version_mismatch() -> None:
    """The exact defect class this cross-check exists to catch: a
    prominence sidecar paired with a since-regenerated pathfinding graph."""
    graph = _pathfinding_graph()
    broken = _prominence(graph)
    broken["pathfinding_graph_version"] = "pathfinding-graph-v4-20260601-stale"
    failures = prominence_failures(broken, graph)
    assert any("does not match the pathfinding graph's own" in f for f in failures)


def test_rejects_node_ids_mismatch() -> None:
    graph = _pathfinding_graph()
    broken = _prominence(graph)
    broken["node_ids"] = [-1, 100, 999]
    failures = prominence_failures(broken, graph)
    assert any("node_ids must be identical" in f for f in failures)


def test_rejects_wrong_length_array() -> None:
    graph = _pathfinding_graph()
    broken = _prominence(graph)
    broken["degree"] = [1, 2]
    failures = prominence_failures(broken, graph)
    assert any("degree must be an array of length 3" in f for f in failures)


def test_rejects_negative_value() -> None:
    graph = _pathfinding_graph()
    broken = _prominence(graph)
    broken["rank"][1] = -5
    failures = prominence_failures(broken, graph)
    assert any("rank must contain only non-negative integers" in f for f in failures)


def test_rejects_first_year_greater_than_last_year() -> None:
    graph = _pathfinding_graph()
    broken = _prominence(graph)
    broken["first_year"][1] = 2000
    broken["last_year"][1] = 1995
    # A tampered payload's version no longer matches -- restore it so this
    # test isolates the first/last year check, not the version mismatch.
    broken["prominence_version"] = prominence_version(broken, _SNAPSHOT)
    failures = prominence_failures(broken, graph)
    assert any("first_year[1] must be <= last_year[1]" in f for f in failures)


def test_rejects_one_sided_null_year() -> None:
    graph = _pathfinding_graph()
    broken = _prominence(graph)
    broken["first_year"][1] = None
    broken["prominence_version"] = prominence_version(broken, _SNAPSHOT)
    failures = prominence_failures(broken, graph)
    assert any("must be both null or both set" in f for f in failures)


def test_rejects_tampered_version() -> None:
    graph = _pathfinding_graph()
    broken = _prominence(graph)
    broken["rank"] = deepcopy(broken["rank"])
    broken["rank"][1] = 999
    failures = prominence_failures(broken, graph)
    assert any("does not match the artifact's own" in f for f in failures)


def test_rejects_malformed_version_pattern() -> None:
    graph = _pathfinding_graph()
    broken = _prominence(graph)
    broken["prominence_version"] = "not-a-real-version"
    failures = prominence_failures(broken, graph)
    assert any("not a well-formed prominence-v1 version" in f for f in failures)
