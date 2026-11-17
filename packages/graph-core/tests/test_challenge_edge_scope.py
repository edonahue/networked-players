"""Campaign Atlas G1b: the challenge builder searches under the SAME seed-scope
rule the pathfinding graph is built under, so every published hop is a graph edge.

Synthetic fixture (seeds = album artists A=100, Z=900, M=800, Y=950):
  * A-B-C-Z: A-B R1, B-C R2 (B, C both non-seed: OUT of scope), C-Z R3. 3 hops, shortest.
  * A-N1-M-N3-Z: R4..R7, every edge touches a seed (A / M / Z). 4 hops.
  * Y-P-Q-Z: R8..R10, P-Q is out of scope, and it is Y's only route.
"""

from __future__ import annotations

import itertools
import random
from pathlib import Path
from typing import Any

import duckdb
import pytest

from conftest import SNAPSHOT_DATE, _performed, _release, write_synthetic_dataset
from networked_players_contracts import challenge_hops_missing_from_graph
from networked_players_graph_core.challenge import (
    MatchedAlbum,
    build_challenge_v2_from_matched,
    carry_forward_scope_outcomes,
    validate_challenge,
)
from networked_players_graph_core.graph import (
    GRAPH_POLICY_VERSION,
    CreditGraph,
    FrontierTooLargeError,
    catalog_seed_artist_ids,
    edge_in_seed_scope,
    seed_scope_sql,
)
from networked_players_graph_core.pathfinding_graph import build_pathfinding_graph

A, B, C, Z, N1, N3, M, Y, P, Q = 100, 200, 300, 900, 201, 301, 800, 950, 401, 402
SEEDS = frozenset({A, Z, M, Y})
EDGES = [
    (1, A, B),
    (2, B, C),
    (3, C, Z),
    (4, A, N1),
    (5, N1, M),
    (6, M, N3),
    (7, N3, Z),
    (8, Y, P),
    (9, P, Q),
    (10, Q, Z),
]
NAMES = {
    A: "Aa",
    B: "Bb",
    C: "Cc",
    Z: "Zz",
    N1: "N1",
    N3: "N3",
    M: "Mm",
    Y: "Yy",
    P: "Pp",
    Q: "Qq",
}


@pytest.fixture
def scoped_root(tmp_path: Path) -> Path:
    releases = [
        _release(rid, f"R{rid}", master_id=rid, master_is_main_release=True) for rid, *_ in EDGES
    ]
    credits = []
    for rid, a, b in EDGES:
        credits += _performed(rid, artist_id=a, name=NAMES[a])
        credits += _performed(rid, artist_id=b, name=NAMES[b])
    return write_synthetic_dataset(tmp_path / "snap", release_rows=releases, credit_rows=credits)


def _albums() -> list[MatchedAlbum]:
    spec = [(A, 1), (Z, 3), (M, 5), (Y, 8)]
    return [
        MatchedAlbum(NAMES[a], f"T{rid}", rid, rid, f"T{rid}", a, NAMES[a], 1990) for a, rid in spec
    ]


def _build(graph: CreditGraph, **kwargs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    return build_challenge_v2_from_matched(
        graph,
        _albums(),
        [],
        snapshot_date=SNAPSHOT_DATE,
        generated_by="test",
        max_paths=20,
        max_hops=4,
        max_frontier_expansion=None,
        quiet=True,
        **kwargs,
    )


def _pairs(artifact: dict[str, Any]) -> dict[tuple[int, int], list[tuple[int, int]]]:
    return {
        (p["from_artist_id"], p["to_artist_id"]): [
            (h["artist_a_id"], h["artist_b_id"]) for h in p["hops"]
        ]
        for p in artifact["paths"]
    }


def _catalog() -> dict[str, Any]:
    return {
        "catalog_version": "catalog-v1-20260601-abc123abc123",
        "snapshot_date": SNAPSHOT_DATE,
        "albums": [
            {
                "id": a.album_id,
                "title": a.title,
                "artist_id": a.artist_id,
                "main_release_id": a.main_release_id,
                "year": 1990,
            }
            for a in _albums()
        ],
    }


def _graph_payload(graph: CreditGraph) -> dict[str, Any]:
    catalog = _catalog()
    membership = {
        "schema_version": 1,
        "catalog_version": catalog["catalog_version"],
        "album_credit_membership_version": "x",
        "generated_at": "2026-08-08T00:00:00+00:00",
        "source": "test",
        "license": "test",
        "albums": [
            {
                "album_id": a.album_id,
                "main_release_id": a.main_release_id,
                "credits": [
                    {
                        "artist_id": a.artist_id,
                        "name": a.artist_name,
                        "anv": None,
                        "role_text": None,
                        "credit_scope": "release_artist",
                        "track_position": None,
                        "track_title": None,
                    }
                ],
            }
            for a in _albums()
        ],
    }
    return build_pathfinding_graph(
        graph,
        catalog,
        membership,
        snapshot_date=SNAPSHOT_DATE,
        generated_at="2026-08-03T00:00:00+00:00",
        quiet=True,
    )


def test_old_unscoped_search_publishes_a_non_seed_hop(scoped_root: Path) -> None:
    """The legacy behaviour (fail-then-pass anchor): an unscoped search finds the
    3-hop A-B-C-Z path whose middle hop joins two non-seed artists."""
    with CreditGraph.open(scoped_root) as graph:
        path = graph.find_path(A, Z, max_hops=4)
    assert path is not None
    hops = [(h.artist_a_id, h.artist_b_id) for h in path.hops]
    assert hops == [(A, B), (B, C), (C, Z)]
    assert not edge_in_seed_scope(B, C, SEEDS)


@pytest.mark.parametrize(
    ("in_memory", "max_workers"),
    [(False, 1), (True, 1), (False, 2)],
    ids=["duckdb", "memory", "threads"],
)
def test_new_search_finds_a_seed_touching_alternative_or_drops(
    scoped_root: Path, in_memory: bool, max_workers: int
) -> None:
    with CreditGraph.open(scoped_root) as graph:
        artifact, report = _build(graph, in_memory=in_memory, max_workers=max_workers)
        graph_payload = _graph_payload(graph)
    validate_challenge(artifact)
    pairs = _pairs(artifact)
    # A-Z is re-found through the seed M, never through B-C.
    a_to_z = next(h for (f, t), h in pairs.items() if {f, t} == {A, Z})
    assert (B, C) not in a_to_z and (C, B) not in a_to_z
    assert len(a_to_z) == 4
    # Y's only route crosses the out-of-scope P-Q hop: dropped, not published.
    assert not any(Y in key for key in pairs)
    # Every published hop touches a seed and is an edge of the real graph artifact.
    for hops in pairs.values():
        assert all(edge_in_seed_scope(a, b, SEEDS) for a, b in hops)
    assert challenge_hops_missing_from_graph(artifact, graph_payload) == []
    assert report["albums_in_paths"] == 3
    assert artifact["provenance"]["build_parameters"]["path_edge_scope"] == "seed_touching"
    assert artifact["provenance"]["graph_policy_version"] == GRAPH_POLICY_VERSION == 2


def test_hop_check_fails_loudly_on_an_out_of_scope_hop(scoped_root: Path) -> None:
    with CreditGraph.open(scoped_root) as graph:
        artifact, _ = _build(graph)
        graph_payload = _graph_payload(graph)
    artifact["paths"][0]["hops"] = [
        {"release_id": 1, "artist_a_id": A, "artist_b_id": B},
        {"release_id": 2, "artist_a_id": B, "artist_b_id": C},
        {"release_id": 3, "artist_a_id": C, "artist_b_id": Z},
    ]
    failures = challenge_hops_missing_from_graph(artifact, graph_payload)
    assert len(failures) == 1
    assert f"{B}-{C}" in failures[0]


def test_carry_forward_pairs_are_researched_and_counted(scoped_root: Path) -> None:
    carried = frozenset({(A, Z), (Y, Z)})
    with CreditGraph.open(scoped_root) as graph:
        artifact, report = _build(graph, carry_forward_artist_pairs=carried)
    assert report["carried_pairs_total"] == 2
    assert report["carried_pairs_republished"] == 1  # (A, Z), via the in-scope route
    assert report["carried_pairs_dropped"] == 1  # (Y, Z): only an out-of-scope route
    previous = {
        "paths": [
            {
                "from_artist_id": A,
                "to_artist_id": Z,
                "hops": [
                    {"artist_a_id": A, "artist_b_id": B},
                    {"artist_a_id": B, "artist_b_id": C},
                    {"artist_a_id": C, "artist_b_id": Z},
                ],
            },
            {
                "from_artist_id": Y,
                "to_artist_id": Z,
                "hops": [
                    {"artist_a_id": Y, "artist_b_id": P},
                    {"artist_a_id": P, "artist_b_id": Q},
                    {"artist_a_id": Q, "artist_b_id": Z},
                ],
            },
            {
                "from_artist_id": A,
                "to_artist_id": M,
                "hops": [
                    {"artist_a_id": A, "artist_b_id": N1},
                    {"artist_a_id": N1, "artist_b_id": M},
                ],
            },
        ]
    }
    assert carry_forward_scope_outcomes(previous, artifact, SEEDS) == {
        "previous_paths": 3,
        "previous_paths_with_out_of_scope_hop": 2,
        "out_of_scope_pairs_refound_in_scope": 1,
        "out_of_scope_pairs_dropped": 1,
        # A-Z went 3 -> 4 hops; A-M is not in the new artifact; Y-Z is dropped.
        "pairs_refound_at_different_length": 1,
    }


def test_scope_predicate_agrees_between_python_and_sql() -> None:
    rng = random.Random(7)
    seeds = frozenset(rng.sample(range(1, 40), 8))
    pairs = list(itertools.combinations(range(1, 40), 2))
    con = duckdb.connect()
    con.execute("CREATE TABLE e (artist_a_id BIGINT, artist_b_id BIGINT)")
    con.executemany("INSERT INTO e VALUES (?, ?)", pairs)
    in_sql = {
        (a, b)
        for a, b in con.execute(
            f"SELECT artist_a_id, artist_b_id FROM e WHERE {seed_scope_sql(seeds)}"
        ).fetchall()
    }
    assert in_sql == {p for p in pairs if edge_in_seed_scope(*p, seeds)}
    assert seed_scope_sql(frozenset()) == "FALSE"


def test_graph_builder_and_challenge_search_keep_identical_edge_sets(scoped_root: Path) -> None:
    """Both builders go through the one scope definition: the graph's real-node
    edge set equals what the scoped in-memory index (the challenge search
    substrate) holds."""
    with CreditGraph.open(scoped_root) as graph:
        payload = _graph_payload(graph)
        # The seeds the graph builder uses (catalog), and the seeds the challenge
        # builder actually computes/records: asserted equal, then used for the index.
        seeds = catalog_seed_artist_ids(_catalog())
        _artifact, report = _build(graph)
        assert report["seed_artist_source"] == "matched_albums"
        assert report["seed_artist_count"] == len(seeds)
        assert report["seed_artists_without_matched_album"] == 0
        _artifact, explicit_report = _build(graph, seed_artist_ids=seeds)
        assert explicit_report["seed_artist_source"] == "explicit"
        index = graph.load_in_memory_edge_index(seed_artist_ids=seeds)
    node_ids = payload["node_ids"]
    graph_edges = {
        (node_ids[i], node_ids[payload["neighbors"][s]])
        for i in range(len(node_ids))
        for s in range(payload["offsets"][i], payload["offsets"][i + 1])
        if node_ids[i] > 0 and node_ids[payload["neighbors"][s]] > 0
    }
    index_edges = {(a, b) for a, nbrs in index._adjacency.items() for b, _r in nbrs}
    assert graph_edges == index_edges
    assert (B, C) not in index_edges and (P, Q) not in index_edges


def test_frontier_cap_counts_full_degree_not_scoped_degree(scoped_root: Path) -> None:
    """B has 2 edges (A-B in scope, B-C out of scope). With cap 1 it must be capped
    (full degree 2) even though only 1 of its edges is scoped, on both substrates."""
    with CreditGraph.open(scoped_root) as graph:
        with pytest.raises(FrontierTooLargeError):
            graph.find_path(B, A, max_hops=1, max_frontier_expansion=1, seed_artist_ids=SEEDS)
        index = graph.load_in_memory_edge_index(seed_artist_ids=SEEDS)
        with pytest.raises(FrontierTooLargeError):
            index.find_path(B, A, max_hops=1, max_frontier_expansion=1)
        # Control: a cap of 2 admits B, and expansion follows only scoped edges.
        path = index.find_path(B, A, max_hops=1, max_frontier_expansion=2)
        assert path is not None
        assert index.find_path(B, C, max_hops=1, max_frontier_expansion=2) is None


def test_explicit_seed_set_scopes_search_beyond_matched_albums(scoped_root: Path) -> None:
    """A seed with no matched album (e.g. filtered out by a format policy) still
    scopes the search like the graph does, and is reported."""
    with CreditGraph.open(scoped_root) as graph:
        matched = [m for m in _albums() if m.artist_id != M]
        artifact, report = build_challenge_v2_from_matched(
            graph,
            matched,
            [],
            snapshot_date=SNAPSHOT_DATE,
            generated_by="test",
            max_paths=20,
            max_hops=4,
            max_frontier_expansion=None,
            quiet=True,
            seed_artist_ids=SEEDS,
        )
    assert report["seed_artists_without_matched_album"] == 1
    # With M still a seed, A-Z is found via M even though M's album was filtered out.
    a_to_z = next(h for (f, t), h in _pairs(artifact).items() if {f, t} == {A, Z})
    assert len(a_to_z) == 4
