"""Collection contract (ADR 0074): synthetic fixtures only."""

from __future__ import annotations

import copy
from typing import Any

from networked_players_contracts.collection import (
    collection_failures,
    collection_version,
    collections_failures,
)
from networked_players_contracts.public_artifacts import PUBLIC_ARTIFACT_GROUPS

CATALOG_VERSION = "catalog-v1-test-aaaaaaaaaaaa"
GRAPH_VERSION = "pathfinding-graph-v4-test-bbbbbbbbbbbb"

# Albums master-1..master-5 (anchors -1..-5) and performers 10..14.
ANCHOR_PERFORMERS = {
    1: [10, 11],
    2: [11, 12],
    3: [12, 13],
    4: [10, 13],
    5: [13, 14],
}
# Undirected performer edges -> evidence release id.
PERFORMER_EDGES = {(10, 11): 1001, (11, 12): 1002, (12, 13): 1003, (13, 14): 1004}


def make_graph(edges: dict[tuple[int, int], int] | None = None) -> dict[str, Any]:
    edges = PERFORMER_EDGES if edges is None else edges
    node_ids = sorted([-n for n in ANCHOR_PERFORMERS] + [10, 11, 12, 13, 14])
    adjacency: dict[int, list[tuple[int, int]]] = {n: [] for n in node_ids}
    for album, performers in ANCHOR_PERFORMERS.items():
        for p in performers:
            adjacency[-album].append((p, 500 + album))
            adjacency[p].append((-album, 500 + album))
    for (a, b), release in edges.items():
        adjacency[a].append((b, release))
        adjacency[b].append((a, release))
    index = {n: i for i, n in enumerate(node_ids)}
    offsets = [0]
    neighbors: list[int] = []
    evidence: list[int] = []
    for n in node_ids:
        for other, release in sorted(adjacency[n], key=lambda item: index[item[0]]):
            neighbors.append(index[other])
            evidence.append(release)
        offsets.append(len(neighbors))
    return {
        "schema_version": 4,
        "pathfinding_graph_version": GRAPH_VERSION,
        "node_ids": node_ids,
        "names": [f"Anchor {-n}" if n < 0 else f"Player {n}" for n in node_ids],
        "offsets": offsets,
        "neighbors": neighbors,
        "evidence_release_ids": evidence,
        "album_virtual_nodes": [
            {"album_id": f"master-{n}", "virtual_artist_id": -n, "main_release_id": 500 + n}
            for n in ANCHOR_PERFORMERS
        ],
    }


def make_catalog() -> dict[str, Any]:
    return {
        "catalog_version": CATALOG_VERSION,
        "albums": [
            {"id": f"master-{n}", "artist_id": 100 + (n % 4), "artist": f"Artist {n % 4}"}
            for n in range(1, 6)
        ],
    }


def make_collection() -> dict[str, Any]:
    collection: dict[str, Any] = {
        "schema_version": 1,
        "collection_id": "synthetic-bridge",
        "title": "Synthetic Bridge",
        "intro": "A made-up set of records for tests.",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "records": ["master-1", "master-2", "master-3", "master-4"],
        "bridge_players": [
            {"artist_id": 10, "name": "Player 10", "records": ["master-1", "master-4"]},
            {"artist_id": 11, "name": "Player 11", "records": ["master-1", "master-2"]},
        ],
        "journey": [
            {
                "from_record": "master-1",
                "to_record": "master-3",
                "via": [11, 12],
                "via_names": ["Player 11", "Player 12"],
                "evidence_release_ids": [1002],
            }
        ],
        "provenance": {
            "inputs": {"catalog": CATALOG_VERSION, "pathfinding_graph": GRAPH_VERSION},
            "collection_version": "",
        },
    }
    return restamp(collection)


def restamp(collection: dict[str, Any]) -> dict[str, Any]:
    collection["provenance"]["collection_version"] = collection_version(collection)
    return collection


def failures(collection: Any, graph: Any = None, catalog: Any = None) -> str:
    return " | ".join(
        collection_failures(
            collection, catalog or make_catalog(), graph if graph is not None else make_graph()
        )
    )


def test_valid_collection_passes() -> None:
    assert collection_failures(make_collection(), make_catalog(), make_graph()) == []


def test_record_not_in_catalog() -> None:
    c = make_collection()
    c["records"][3] = "master-99"
    assert "record 'master-99' is not in the catalog" in failures(restamp(c))


def test_too_few_records_and_artists() -> None:
    c = make_collection()
    c["records"] = c["records"][:3]
    assert "must hold 4..24 albums" in failures(restamp(c))
    catalog = make_catalog()
    for album in catalog["albums"]:
        album["artist_id"] = 7
    assert "at least 3 distinct primary artists" in failures(make_collection(), catalog=catalog)


def test_bridge_player_not_adjacent() -> None:
    c = make_collection()
    c["bridge_players"][0]["records"] = ["master-1", "master-2"]  # 10 is not on master-2
    assert "not adjacent to record 'master-2'" in failures(restamp(c))


def test_journey_hop_without_edge() -> None:
    c = make_collection()
    c["journey"][0]["via"] = [10, 12]
    c["journey"][0]["via_names"] = ["Player 10", "Player 12"]
    assert "no edge between performers 10 and 12" in failures(restamp(c))


def test_evidence_must_equal_the_graphs() -> None:
    c = make_collection()
    c["journey"][0]["evidence_release_ids"] = [9999]
    assert "differs from the graph's evidence release 1002" in failures(restamp(c))


def test_private_fields_are_refused() -> None:
    for key in ("notes", "reviewer", "reviewed_by", "rejected", "working_title", "x_private"):
        c = make_collection()
        c[key] = "secret"
        assert f"private field '$.{key}'" in failures(c)
    c = make_collection()
    c["journey"][0]["note"] = "nested"
    assert "private field '$.journey[0].note'" in failures(c)


def test_empty_title_or_intro_refused() -> None:
    c = make_collection()
    c["intro"] = "  "
    c["title"] = ""
    text = failures(restamp(c))
    assert "intro is required" in text and "title is required" in text


def test_copy_must_not_suggest_a_private_collection_or_influence() -> None:
    c = make_collection()
    c["intro"] = "Straight from my collection."
    assert "forbidden phrase 'my collection'" in failures(restamp(c))


def test_version_mismatch() -> None:
    c = make_collection()
    c["title"] = "Changed after stamping"
    assert "does not match recomputed content" in failures(c)


def test_generated_at_does_not_change_the_version() -> None:
    c = make_collection()
    c["generated_at"] = "2027-01-01T00:00:00+00:00"
    assert collection_failures(c, make_catalog(), make_graph()) == []


def test_stale_graph_version_in_lineage() -> None:
    graph = make_graph()
    graph["pathfinding_graph_version"] = "pathfinding-graph-v4-test-cccccccccccc"
    assert "built from pathfinding_graph version" in failures(make_collection(), graph)


def test_graph_rebuild_that_removes_a_journey_edge_names_the_hop() -> None:
    edges = {k: v for k, v in PERFORMER_EDGES.items() if k != (11, 12)}
    graph = make_graph(edges)
    text = failures(make_collection(), graph)
    assert "journey hop 1 (master-1 -> master-3)" in text
    assert "no edge between performers 11 and 12" in text


def test_playable_pairs_validate_and_are_checked_against_the_graph() -> None:
    c = make_collection()
    c["playable_cohort"] = {
        "schema_version": 2,
        "route_policy": "shortest-first-found-v1",
        "pairs": [
            {
                "record_a": "master-1",
                "record_b": "master-3",
                "hop_count": 1,
                "via": [11, 12],
                "via_names": ["Player 11", "Player 12"],
                "evidence_release_ids": [1002],
            }
        ],
    }
    assert collection_failures(restamp(c), make_catalog(), make_graph()) == []
    c["playable_cohort"]["pairs"][0]["evidence_release_ids"] = [1]
    assert "playable pair 1" in failures(restamp(c))


def test_group_passes_with_no_collections_and_checks_the_index() -> None:
    assert collections_failures(None, make_catalog(), make_graph()) == []
    c = make_collection()
    index = {
        "schema_version": 1,
        "collections": [
            {
                "collection_id": "synthetic-bridge",
                "title": c["title"],
                "artifact_path": "/data/collections/synthetic-bridge.v1.json",
                "record_count": 4,
                "collection_version": c["provenance"]["collection_version"],
            }
        ],
    }
    good = {"index": index, "files": {"synthetic-bridge": c}}
    assert collections_failures(good, make_catalog(), make_graph()) == []
    unlisted = {"index": index, "files": {"synthetic-bridge": c, "other": copy.deepcopy(c)}}
    assert "not listed in the collections index" in " ".join(
        collections_failures(unlisted, make_catalog(), make_graph())
    )
    assert "no file was loaded" in " ".join(
        collections_failures({"index": index, "files": {}}, make_catalog(), make_graph())
    )


def test_collections_is_a_registered_group() -> None:
    from networked_players_contracts.artifact_lineage import ARTIFACT_CLASSES

    assert "collections" in PUBLIC_ARTIFACT_GROUPS
    assert ARTIFACT_CLASSES["collections"] == "live"
