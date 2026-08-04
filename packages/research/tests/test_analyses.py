"""Fixture tests for Slice D's five new analysis primitives:
`role_distribution` and `temporal_comparison` (DuckDB aggregations, this
file) and the three igraph-based analyses in `graph_analysis.py`
(`contributor_network`, `community_detection`, `bridge_analysis` --
requires the optional 'graph' extra, skipped otherwise).

Uses the shared `dataset_root` fixture from conftest.py: Jane (100) and
Bob (200) co-credited on release 1 (1990), Jane (100) and Cara (300)
co-credited on release 2 (1993), Bob (200) alone on release 3 (1995).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from networked_players_research.analyses import role_distribution, temporal_comparison


def test_role_distribution_classifies_unlabeled_credits_as_unknown(dataset_root: Path) -> None:
    result = role_distribution(dataset_root)
    assert result["kind"] == "role_distribution"
    # Every fixture credit has role_text=None -> classify_role(None) is
    # UNKNOWN -- a real, honest signal, not a test artifact to hide.
    assert result["overall"] == {"unknown": 10}
    assert result["by_year"]["1990"] == {"unknown": 4}
    assert result["by_year"]["1993"] == {"unknown": 4}
    assert result["by_year"]["1995"] == {"unknown": 2}


def test_temporal_comparison_flags_measured_turnover_not_guessed_dates(
    dataset_root: Path,
) -> None:
    result = temporal_comparison(dataset_root)
    assert result["kind"] == "temporal_comparison"
    # 1990->1993 keeps Jane (jaccard 1/3, above the 0.2 threshold); 1993->1995
    # shares no contributor at all (jaccard 0) -- a real measured discontinuity.
    assert result["turnover_years"] == ["1995"]
    assert result["eras"] == [
        {"start_year": "1990", "end_year_exclusive": "1995"},
        {"start_year": "1995", "end_year_exclusive": None},
    ]


def test_role_distribution_on_a_dataset_with_no_credits_is_empty(tmp_path: Path) -> None:
    from .conftest import write_synthetic_dataset

    root = write_synthetic_dataset(tmp_path / "snapshot=20260601", release_rows=[], credit_rows=[])
    result = role_distribution(root)
    assert result["overall"] == {}
    assert result["by_year"] == {}


igraph = pytest.importorskip("igraph")


def test_contributor_network_reflects_real_co_credit_edges(dataset_root: Path) -> None:
    from networked_players_research.graph_analysis import contributor_network

    result = contributor_network(dataset_root)
    assert result["kind"] == "contributor_network"
    node_ids = {node["artist_id"] for node in result["nodes"]}
    assert node_ids == {100, 200, 300}
    edge_pairs = {frozenset((edge["artist_a_id"], edge["artist_b_id"])) for edge in result["edges"]}
    assert edge_pairs == {frozenset((100, 200)), frozenset((100, 300))}


def test_community_detection_labels_communities_by_algorithm_never_a_scene_name(
    dataset_root: Path,
) -> None:
    from networked_players_research.graph_analysis import community_detection

    result = community_detection(dataset_root)
    assert result["kind"] == "community_detection"
    assert result["algorithm"] == "leiden"
    assert result["community_count"] >= 1
    for assignment in result["assignments"]:
        assert assignment["community"].startswith("community ")
        assert "algorithm leiden" in assignment["community"]


def test_bridge_analysis_ranks_by_betweenness_not_a_relationship_claim(
    dataset_root: Path,
) -> None:
    from networked_players_research.graph_analysis import bridge_analysis

    result = bridge_analysis(dataset_root)
    assert result["kind"] == "bridge_analysis"
    assert result["signal"] == "betweenness_centrality"
    # Jane (100) is the only node bridging the {100,200} and {100,300} edges
    # -- a real, measured structural fact, not an asserted relationship.
    ranked_ids = [entry["artist_id"] for entry in result["ranked_contributors"]]
    assert 100 in ranked_ids
