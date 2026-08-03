from __future__ import annotations

from copy import deepcopy
from typing import Any

from networked_players_contracts.catalog import _catalog_version
from networked_players_contracts.pathfinding_graph import (
    pathfinding_graph_failures,
    pathfinding_graph_version,
)

_SNAPSHOT = "20260601"


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


def _graph() -> dict[str, Any]:
    catalog = _catalog()
    # Node 0 = artist 100, node 1 = artist 200, node 2 = artist 300.
    # Edges (both directions, matching CSR symmetry): 100<->200 (release 1),
    # 100<->300 (release 2).
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


def test_clean_graph_has_no_failures() -> None:
    assert pathfinding_graph_failures(_graph(), _catalog()) == []


def test_wrong_top_level_type_fails() -> None:
    assert pathfinding_graph_failures("nope", _catalog()) != []
    assert pathfinding_graph_failures(_graph(), "nope") != []


def test_mismatched_catalog_version_is_caught() -> None:
    graph = deepcopy(_graph())
    graph["catalog_version"] = "catalog-v1-wrong"
    failures = pathfinding_graph_failures(graph, _catalog())
    assert any("catalog_version" in f for f in failures)


def test_stale_version_is_caught() -> None:
    graph = deepcopy(_graph())
    graph["pathfinding_graph_version"] = "pathfinding-graph-v1-20260601-" + "0" * 12
    failures = pathfinding_graph_failures(graph, _catalog())
    assert any("pathfinding_graph_version" in f for f in failures)


def test_unsorted_node_ids_is_rejected() -> None:
    graph = deepcopy(_graph())
    graph["node_ids"] = [200, 100, 300]
    failures = pathfinding_graph_failures(graph, _catalog())
    assert any("sorted" in f for f in failures)


def test_names_wrong_length_is_rejected() -> None:
    graph = deepcopy(_graph())
    graph["names"] = ["Alice", "Bob"]
    failures = pathfinding_graph_failures(graph, _catalog())
    assert any("names" in f for f in failures)


def test_offsets_wrong_length_is_rejected() -> None:
    graph = deepcopy(_graph())
    graph["offsets"] = [0, 2, 3]
    failures = pathfinding_graph_failures(graph, _catalog())
    assert any("offsets" in f for f in failures)


def test_out_of_range_neighbor_index_is_rejected() -> None:
    graph = deepcopy(_graph())
    graph["neighbors"] = [1, 99, 0, 0]
    failures = pathfinding_graph_failures(graph, _catalog())
    assert any("not a valid node index" in f for f in failures)


def test_mismatched_parallel_array_length_is_rejected() -> None:
    graph = deepcopy(_graph())
    graph["edge_role_a"] = ["Guitar"]
    failures = pathfinding_graph_failures(graph, _catalog())
    assert any("edge_role_a" in f for f in failures)
