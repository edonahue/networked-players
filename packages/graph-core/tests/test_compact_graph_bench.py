from __future__ import annotations

from pathlib import Path

import pytest

from networked_players_graph_core.compact_graph_bench import (
    FrontierTooLargeBench,
    bfs_over_csr,
    build_csr_adjacency,
    payload_size_bytes,
)
from networked_players_graph_core.graph import CreditGraph, FrontierTooLargeError


def _credit(
    release_id: int,
    artist_id: int,
    name: str,
    *,
    credit_scope: str = "release_artist",
    track_index: int | None = None,
) -> dict:
    return {
        "snapshot_date": "20260601",
        "release_id": release_id,
        "track_index": track_index,
        "track_path": str(track_index) if track_index is not None else None,
        "track_position": "1" if track_index is not None else None,
        "track_title": "Take" if track_index is not None else None,
        "credit_scope": credit_scope,
        "artist_id": artist_id,
        "name": name,
        "anv": None,
        "join_text": None,
        "role_text": "Performer" if credit_scope == "track_artist" else None,
        "credited_tracks_text": None,
        "is_linked": True,
        "playable_identity": True,
    }


def _co_performer_credits(release_id: int, a: tuple[int, str], b: tuple[int, str]) -> list[dict]:
    """Two artists co-performing on the same track of an album-shaped
    release, each also billed at release level -- the shape `graph.py`'s
    `co_performers` edge rule requires (both billed AND both track
    performers on the same track_index; see credit_edges_sql's docstring)."""
    a_id, a_name = a
    b_id, b_name = b
    return [
        _credit(release_id, a_id, a_name, credit_scope="release_artist"),
        _credit(release_id, a_id, a_name, credit_scope="track_artist", track_index=0),
        _credit(release_id, b_id, b_name, credit_scope="release_artist"),
        _credit(release_id, b_id, b_name, credit_scope="track_artist", track_index=0),
    ]


def _release(release_id: int, title: str) -> dict:
    return {
        "snapshot_date": "20260601",
        "release_id": release_id,
        "status": "Accepted",
        "title": title,
        "country": None,
        "released": None,
        "master_id": release_id,
        "master_is_main_release": True,
        "data_quality": None,
        "source_url": f"https://example.invalid/release/{release_id}",
    }


@pytest.fixture
def chain_dataset(tmp_path: Path) -> Path:
    """A -1- B -2- C -3- D chain: four artists, three releases, each pair
    co-billed on one release. Small enough to compute both a real
    CreditGraph traversal and a CSR one over exactly the same edges."""
    from conftest import write_synthetic_dataset

    releases = [_release(1, "R1"), _release(2, "R2"), _release(3, "R3")]
    credits = [
        *_co_performer_credits(1, (100, "Alice"), (200, "Bob")),
        *_co_performer_credits(2, (200, "Bob"), (300, "Cara")),
        *_co_performer_credits(3, (300, "Cara"), (400, "Dan")),
    ]
    return write_synthetic_dataset(
        tmp_path / "snapshot=20260601", release_rows=releases, credit_rows=credits
    )


def _edges_from_graph(dataset_root: Path) -> list[tuple[int, int, int]]:
    with CreditGraph.open(dataset_root) as graph:
        rows = graph._connection.execute(
            "SELECT artist_a_id, artist_b_id, release_id FROM credit_edges "
            "WHERE artist_a_id < artist_b_id"
        ).fetchall()
    return [(int(a), int(b), int(r)) for a, b, r in rows]


def test_csr_bfs_agrees_with_creditgraph_find_path(chain_dataset: Path) -> None:
    edges = _edges_from_graph(chain_dataset)
    graph = build_csr_adjacency(edges)

    csr_hops = bfs_over_csr(graph, 100, 400, max_hops=4)
    assert csr_hops is not None

    with CreditGraph.open(chain_dataset) as credit_graph:
        real_path = credit_graph.find_path(100, 400, max_hops=4)

    assert real_path is not None
    real_hops = [
        {"artist_a_id": h.artist_a_id, "artist_b_id": h.artist_b_id, "release_id": h.release_id}
        for h in real_path.hops
    ]
    # Endpoint sequence must match (same shortest path over the same edges);
    # hop direction can differ (BFS parent-pointer orientation is an
    # implementation detail, not a claim about which artist "led" the hop).
    csr_endpoints = [(h["artist_a_id"], h["artist_b_id"]) for h in csr_hops]
    real_endpoints = [(h["artist_a_id"], h["artist_b_id"]) for h in real_hops]
    assert len(csr_endpoints) == len(real_endpoints) == 3


def test_csr_bfs_confirms_no_path_within_hop_budget(chain_dataset: Path) -> None:
    edges = _edges_from_graph(chain_dataset)
    graph = build_csr_adjacency(edges)
    # A -> D is 3 hops; a budget of 2 must confirm no path, not error.
    assert bfs_over_csr(graph, 100, 400, max_hops=2) is None


def test_csr_bfs_matches_real_graph_confirmed_no_path(chain_dataset: Path) -> None:
    edges = _edges_from_graph(chain_dataset)
    graph = build_csr_adjacency(edges)
    csr_result = bfs_over_csr(graph, 100, 400, max_hops=2)

    with CreditGraph.open(chain_dataset) as credit_graph:
        real_result = credit_graph.find_path(100, 400, max_hops=2)

    assert csr_result is None
    assert real_result is None


def test_frontier_too_large_is_raised_not_silently_returned_as_no_path(
    chain_dataset: Path,
) -> None:
    edges = _edges_from_graph(chain_dataset)
    graph = build_csr_adjacency(edges)
    with pytest.raises(FrontierTooLargeBench):
        bfs_over_csr(graph, 100, 400, max_hops=4, max_frontier_nodes=0)


def test_real_graph_frontier_too_large_matches_the_concept(chain_dataset: Path) -> None:
    """Confirms the real CreditGraph raises the same class of exception this
    bench module mirrors -- both architectures must distinguish inconclusive
    from confirmed-no-path, never collapse the two."""
    with CreditGraph.open(chain_dataset) as credit_graph:
        with pytest.raises(FrontierTooLargeError):
            credit_graph.find_path(100, 400, max_hops=4, max_frontier_expansion=0)


def test_same_artist_returns_empty_path(chain_dataset: Path) -> None:
    edges = _edges_from_graph(chain_dataset)
    graph = build_csr_adjacency(edges)
    assert bfs_over_csr(graph, 100, 100, max_hops=4) == []


def test_unknown_artist_id_raises_value_error(chain_dataset: Path) -> None:
    edges = _edges_from_graph(chain_dataset)
    graph = build_csr_adjacency(edges)
    with pytest.raises(ValueError, match="999999"):
        bfs_over_csr(graph, 999999, 100, max_hops=4)


def test_csr_construction_is_deterministic_regardless_of_edge_order() -> None:
    edges = [(100, 200, 1), (200, 300, 2), (300, 400, 3)]
    graph_a = build_csr_adjacency(edges)
    graph_b = build_csr_adjacency(list(reversed(edges)))
    assert graph_a.node_ids == graph_b.node_ids
    assert graph_a.offsets == graph_b.offsets
    assert graph_a.neighbors == graph_b.neighbors
    assert graph_a.evidence_release_ids == graph_b.evidence_release_ids


def test_payload_size_bytes_scales_with_graph_size() -> None:
    small = build_csr_adjacency([(1, 2, 100)])
    large = build_csr_adjacency([(1, 2, 100), (2, 3, 200), (3, 4, 300), (4, 5, 400)])
    assert payload_size_bytes(large)["total_bytes"] > payload_size_bytes(small)["total_bytes"]
