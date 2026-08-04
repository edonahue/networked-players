"""Correctness parity fixtures for the graph-library benchmark: a small,
hand-computable synthetic graph, same expected component/edge answer from
every candidate library. Requires the optional 'graph' extra
(uv sync --package networked-players-research --extra graph); skipped
entirely if it isn't installed, since it's not part of the base install."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from networked_players_catalog.discogs.parquet import SCHEMAS

pytest.importorskip("networkx")
pytest.importorskip("igraph")
pytest.importorskip("rustworkx")

from networked_players_research.graph_bench import (
    _undirected_dedup,
    benchmark_igraph,
    benchmark_networkx,
    benchmark_rustworkx,
    load_edges,
)


# Two triangles (100-200-300 and 400-500-600), disconnected from each other:
# a real, hand-computable case -- 6 nodes, 6 edges, 2 components, each of
# size 3.
def _two_triangles() -> set[tuple[int, int]]:
    return {(100, 200), (200, 300), (100, 300), (400, 500), (500, 600), (400, 600)}


def test_networkx_finds_the_real_component_structure() -> None:
    result = benchmark_networkx(_two_triangles())
    assert result.node_count == 6
    assert result.edge_count == 6
    assert result.component_count == 2
    assert result.largest_component_size == 3


def test_igraph_finds_the_real_component_structure() -> None:
    result = benchmark_igraph(_two_triangles())
    assert result.node_count == 6
    assert result.edge_count == 6
    assert result.component_count == 2
    assert result.largest_component_size == 3


def test_rustworkx_finds_the_real_component_structure() -> None:
    result = benchmark_rustworkx(_two_triangles())
    assert result.node_count == 6
    assert result.edge_count == 6
    assert result.component_count == 2
    assert result.largest_component_size == 3
    # rustworkx has no built-in community detection in this pass -- reported
    # as unavailable, never silently substituted.
    assert result.community_count is None


def test_all_three_libraries_agree_on_component_structure() -> None:
    pairs = _two_triangles()
    results = [
        benchmark_networkx(pairs),
        benchmark_igraph(pairs),
        benchmark_rustworkx(pairs),
    ]
    assert {r.node_count for r in results} == {6}
    assert {r.edge_count for r in results} == {6}
    assert {r.component_count for r in results} == {2}
    assert {r.largest_component_size for r in results} == {3}


def test_undirected_dedup_collapses_both_directions() -> None:
    # credit_edges_sql returns both (a,b) and (b,a) rows, plus a release_id
    # per edge -- dedup must collapse direction, not release.
    edges = [(100, 200, 1), (200, 100, 1), (100, 300, 2)]
    assert _undirected_dedup(edges) == {(100, 200), (100, 300)}


def test_load_edges_uses_the_real_credit_edges_sql_semantics(tmp_path: Path) -> None:
    """A DJ-compilation-shaped fixture (many track-scope credits on one
    release) must not become a giant clique -- the exact hub bug
    credit_edges_sql's own docstring names. Proves load_edges reuses the
    real production semantics, not a naive "shared release_id" join."""
    root = tmp_path / "snapshot=20260601"
    (root / "table=releases").mkdir(parents=True)
    (root / "table=credits").mkdir(parents=True)
    (root / "table=tracks").mkdir(parents=True)

    release_row = {
        "snapshot_date": "20260601",
        "release_id": 1,
        "status": "Accepted",
        "title": "Various Compilation",
        "country": None,
        "released": "1999",
        "master_id": None,
        "master_is_main_release": None,
        "data_quality": None,
        "source_url": "https://example.invalid/release/1",
    }
    credit_rows = []
    for track_index, artist_id in enumerate([100, 200, 300]):
        credit_rows.append(
            {
                "snapshot_date": "20260601",
                "release_id": 1,
                "track_index": track_index,
                "track_path": str(track_index),
                "track_position": str(track_index + 1),
                "track_title": f"Track {track_index + 1}",
                "credit_scope": "track_artist",
                "artist_id": artist_id,
                "name": f"Artist {artist_id}",
                "anv": None,
                "join_text": None,
                "role_text": None,
                "credited_tracks_text": None,
                "is_linked": True,
                "playable_identity": True,
            }
        )

    pq.write_table(
        pa.Table.from_pylist([release_row], schema=SCHEMAS["releases"]),
        root / "table=releases" / "part-00000.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist(credit_rows, schema=SCHEMAS["credits"]),
        root / "table=credits" / "part-00000.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist([], schema=SCHEMAS["tracks"]),
        root / "table=tracks" / "part-00000.parquet",
    )

    edges = load_edges(root)
    # Each artist is the sole performer of their own track (no shared
    # track_index) -- real credit_edges_sql semantics produce NO edges
    # here, unlike a naive "everyone who shares a release_id" join, which
    # would wrongly connect all three into a clique.
    assert edges == []
