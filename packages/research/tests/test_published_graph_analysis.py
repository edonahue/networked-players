"""Unit tests for graph-expansion Phase 0 slice 0-C's published-graph
measurements: `published_graph_community_detection` and
`published_graph_articulation_points` (`networked_players_research.graph_analysis`).

Builds a small synthetic `pathfinding/graph.v3.json`-shaped JSON directly --
these functions are deliberately dependency-free of the private one-hop
corpus, so the test fixture is a raw CSR file, not a `CreditGraph`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from networked_players_research.graph_analysis import (
    published_graph_articulation_points,
    published_graph_community_detection,
)


def _csr_from_undirected_edges(n: int, edges: list[tuple[int, int]]) -> tuple[list[int], list[int]]:
    adjacency: list[list[int]] = [[] for _ in range(n)]
    for a, b in edges:
        adjacency[a].append(b)
        adjacency[b].append(a)
    offsets = [0]
    neighbors: list[int] = []
    for row in adjacency:
        neighbors.extend(sorted(row))
        offsets.append(len(neighbors))
    return offsets, neighbors


def _write_published_graph(
    path: Path, *, n: int, edges: list[tuple[int, int]], anchor_album_ids: dict[str, int]
) -> None:
    offsets, neighbors = _csr_from_undirected_edges(n, edges)
    payload: dict[str, Any] = {
        "node_ids": list(range(1000, 1000 + n)),
        "names": [f"Node {i}" for i in range(n)],
        "offsets": offsets,
        "neighbors": neighbors,
        "evidence_release_ids": [1] * len(neighbors),
        "edge_role_a": ["Performer"] * len(neighbors),
        "edge_role_b": ["Performer"] * len(neighbors),
        "album_virtual_nodes": [
            {"album_id": album_id, "virtual_artist_id": index}
            for album_id, index in anchor_album_ids.items()
        ],
    }
    path.write_text(json.dumps(payload))


def test_articulation_points_finds_the_real_path_between_two_anchors(tmp_path: Path) -> None:
    """Chain 0(A1)-1-2-3-4(A2)-6-5 is a plain path graph -- every internal
    node (1, 2, 3, 4, 6) is a cut vertex, since a path has no cycles at
    all. Only 1, 2, and 3 sit strictly BETWEEN the two anchors and
    genuinely separate them into different components; node 4 IS an
    anchor itself (removing it leaves only one surviving anchor, never
    "2 components with an anchor"), and node 6 sheds only the leaf at 5
    without separating the two anchors from each other -- the exact
    "single-leaf case that sank ADR 0063" this filter exists to exclude."""
    path = tmp_path / "graph.v3.json"
    _write_published_graph(
        path,
        n=7,
        edges=[(0, 1), (1, 2), (2, 3), (3, 4), (4, 6), (6, 5)],
        anchor_album_ids={"master-1": 0, "master-2": 4},
    )
    result = published_graph_articulation_points(path)

    assert result["node_count"] == 7
    assert result["raw_cut_vertex_count"] == 5  # nodes 1, 2, 3, 4, 6
    assert result["real_bridge_count"] == 3  # nodes 1, 2, 3 -- not 4 or 6
    real_bridge_indices = {b["node_index"] for b in result["real_bridges"]}
    assert real_bridge_indices == {1, 2, 3}
    assert result["elapsed_s"] >= 0.0


def test_articulation_points_returns_no_real_bridges_when_no_cut_vertex_separates_anchors(
    tmp_path: Path,
) -> None:
    """Both anchors (0 and 2) sit on a 4-cycle 0-1-2-3-0, so no vertex on
    the cycle separates them -- removing node 3 (the cycle vertex nearest
    the pendant tail) still leaves 0-1-2 as one connected component with
    BOTH anchors together. Node 3 is nonetheless a real cut vertex (it
    also disconnects the pendant {4, 5} tail), and node 4 is a second real
    cut vertex shedding only the leaf at 5 -- neither ever separates the
    two anchors from each other."""
    path = tmp_path / "graph.v3.json"
    _write_published_graph(
        path,
        n=6,
        edges=[(0, 1), (1, 2), (2, 3), (3, 0), (3, 4), (4, 5)],
        anchor_album_ids={"master-1": 0, "master-2": 2},
    )
    result = published_graph_articulation_points(path)

    assert result["raw_cut_vertex_count"] == 2  # nodes 3 and 4
    assert result["real_bridge_count"] == 0


def test_community_detection_reports_real_modularity_and_anchor_sharing(tmp_path: Path) -> None:
    """Two dense, well-separated triangles (each with its own anchor)
    joined by one sparse bridge edge -- a textbook case where Leiden should
    find (at least) two communities and each anchor should share its
    community with the other real member of its own triangle."""
    path = tmp_path / "graph.v3.json"
    # Triangle A: 0,1,2 (anchor at 0). Triangle B: 3,4,5 (anchor at 3).
    # One bridge edge 2-3.
    _write_published_graph(
        path,
        n=6,
        edges=[(0, 1), (1, 2), (2, 0), (3, 4), (4, 5), (5, 3), (2, 3)],
        anchor_album_ids={"master-1": 0, "master-2": 3},
    )
    result = published_graph_community_detection(path)

    assert result["node_count"] == 6
    assert result["edge_count"] == 7
    assert result["community_count"] >= 2
    assert result["modularity"] is not None
    assert result["modularity"] > 0
    assert result["anchor_count"] == 2
    assert result["elapsed_s"] >= 0.0


def test_community_detection_handles_an_edgeless_graph(tmp_path: Path) -> None:
    path = tmp_path / "graph.v3.json"
    _write_published_graph(path, n=2, edges=[], anchor_album_ids={"master-1": 0})
    result = published_graph_community_detection(path)
    assert result["edge_count"] == 0
    assert result["community_count"] == 0
    assert result["modularity"] is None
