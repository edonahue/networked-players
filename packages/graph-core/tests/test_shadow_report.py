"""ADR 0068 Performer Graph PR 2: `shadow_report.py`'s broad-vs-gated
comparison, over a small synthetic dataset (never the real corpus in CI)."""

from __future__ import annotations

from pathlib import Path

import duckdb

from networked_players_graph_core.graph import credit_edges_sql
from networked_players_graph_core.shadow_report import (
    _broad_credit_edges_sql_pre_adr0068,
    build_shadow_comparison_report,
    build_shadow_comparison_report_from_dataset,
)


def _dataset(tmp_path: Path) -> Path:
    """Nirvana's shape from `test_graph.py`: a billed artist connected to a
    real performer-qualifying release_credit (Backing Vocals) and TWO
    non-performer-qualifying ones (Producer/Engineer, Mixed By) -- the broad
    relation keeps all three edges, the gated one keeps only the real
    performer credit. A second, fully isolated release/artist (Solo) proves
    isolated-anchor detection."""
    from conftest import _credit, _release, write_synthetic_dataset

    releases = [_release(1, "Nevermind"), _release(2, "Solo Release")]
    credits = [
        _credit(1, artist_id=100, name="Nirvana", scope="release_artist", role_text=None),
        _credit(
            1, artist_id=100, name="Nirvana", scope="track_artist", role_text=None, track_index=0
        ),
        _credit(
            1,
            artist_id=200,
            name="Butch Vig",
            scope="release_credit",
            role_text="Producer, Engineer",
        ),
        _credit(
            1, artist_id=300, name="Andy Wallace", scope="release_credit", role_text="Mixed By"
        ),
        _credit(
            1,
            artist_id=400,
            name="Backing Singer",
            scope="release_credit",
            role_text="Backing Vocals",
        ),
        _credit(2, artist_id=500, name="Solo Artist", scope="release_artist", role_text=None),
        _credit(
            2,
            artist_id=500,
            name="Solo Artist",
            scope="track_artist",
            role_text=None,
            track_index=0,
        ),
    ]
    root = tmp_path / "snapshot=20260601"
    return write_synthetic_dataset(root, release_rows=releases, credit_rows=credits)


def test_broad_relation_keeps_non_performer_edges_gated_relation_drops(tmp_path: Path) -> None:
    root = _dataset(tmp_path)
    connection = duckdb.connect(database=":memory:")
    connection.read_parquet(str(root / "table=credits" / "*.parquet")).create_view("credits")
    connection.read_parquet(str(root / "table=releases" / "*.parquet")).create_view("releases")

    gated_sql = credit_edges_sql(max_artists_per_release=50)
    gated = set(
        connection.execute(f"SELECT artist_a_id, artist_b_id FROM ({gated_sql})").fetchall()
    )
    broad_sql = _broad_credit_edges_sql_pre_adr0068(max_artists_per_release=50)
    broad = set(
        connection.execute(f"SELECT artist_a_id, artist_b_id FROM ({broad_sql})").fetchall()
    )

    assert (100, 400) in gated, "Backing Vocals passes the performer gate"
    assert (100, 200) not in gated, "Producer, Engineer fails the performer gate"
    assert (100, 300) not in gated, "Mixed By fails the performer gate"
    assert (100, 400) in broad
    assert (100, 200) in broad, "the broad relation predates the gate"
    assert (100, 300) in broad, "the broad relation predates the gate"


def test_build_shadow_comparison_report_real_metrics(tmp_path: Path) -> None:
    root = _dataset(tmp_path)
    connection = duckdb.connect(database=":memory:")
    connection.read_parquet(str(root / "table=credits" / "*.parquet")).create_view("credits")
    connection.read_parquet(str(root / "table=releases" / "*.parquet")).create_view("releases")

    report = build_shadow_comparison_report(
        connection,
        dataset_root=str(root),
        catalog_artist_ids={100, 500},
        catalog_names={100: "Nirvana", 500: "Solo Artist"},
    )
    data = report.as_dict()

    # Broad: Nirvana connects to Butch Vig, Andy Wallace, Backing Singer (3
    # undirected edges); Solo Artist is fully isolated either way.
    assert data["broad_pre_adr0068"]["undirected_edge_count"] == 3
    assert data["broad_pre_adr0068"]["isolated_catalog_anchors"] == [500]

    # Gated: only the Backing Vocals edge survives.
    assert data["gated_adr0068"]["undirected_edge_count"] == 1
    assert data["gated_adr0068"]["isolated_catalog_anchors"] == [500]
    assert data["gated_adr0068"]["largest_component_size"] == 2

    role_texts = {row["role_text"] for row in data["excluded_edges_by_role_text"]}
    assert "Producer, Engineer" in role_texts
    assert "Mixed By" in role_texts
    assert "Backing Vocals" not in role_texts, "a real performer credit is never 'excluded'"


def test_build_shadow_comparison_report_from_dataset_thin_wrapper(tmp_path: Path) -> None:
    root = _dataset(tmp_path)
    report = build_shadow_comparison_report_from_dataset(
        root, catalog_artist_ids={100, 500}, catalog_names={100: "Nirvana", 500: "Solo Artist"}
    )
    assert report.gated["undirected_edge_count"] == 1
    assert report.broad["undirected_edge_count"] == 3
