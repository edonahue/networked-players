"""Tests for the album-projection clustering study (Campaign Atlas S1/E1).
Synthetic fixtures only, in the published-graph shape (see
`test_published_graph_analysis.py`). Requires the optional 'graph' extra."""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("igraph")

from networked_players_research import album_projection as ap
from networked_players_research.cli import main
from networked_players_research.route_quality import load_published_graph

FAST: dict[str, Any] = {"seeds": (0, 1, 2), "null_count": 8, "perturbation_repeats": 3}


def _write_fixture(
    tmp_path: Path,
    album_performers: dict[str, list[int]],
    *,
    artists: dict[str, int] | None = None,
    missing_anchor: set[str] | None = None,
) -> tuple[Path, Path]:
    """Performer ids are small positive ints; album anchors are negative
    virtual ids, exactly like the real artifact."""
    missing_anchor = missing_anchor or set()
    performer_ids = sorted({p for ps in album_performers.values() for p in ps})
    album_ids = sorted(album_performers)
    anchor_id = {a: -(i + 1) for i, a in enumerate(album_ids)}
    node_ids = performer_ids + [anchor_id[a] for a in album_ids if a not in missing_anchor]
    index = {n: i for i, n in enumerate(node_ids)}
    adjacency: list[list[int]] = [[] for _ in node_ids]
    for album, performers in album_performers.items():
        if album in missing_anchor:
            continue
        for p in performers:
            adjacency[index[anchor_id[album]]].append(index[p])
            adjacency[index[p]].append(index[anchor_id[album]])
    offsets = [0]
    neighbors: list[int] = []
    for row in adjacency:
        neighbors.extend(sorted(row))
        offsets.append(len(neighbors))
    graph = {
        "node_ids": node_ids,
        "names": [f"Player {n}" if n > 0 else f"anchor {n}" for n in node_ids],
        "offsets": offsets,
        "neighbors": neighbors,
        "evidence_release_ids": [1] * len(neighbors),
        "edge_role_a": ["Performer"] * len(neighbors),
        "edge_role_b": ["Performer"] * len(neighbors),
        "album_virtual_nodes": [
            {"album_id": a, "virtual_artist_id": anchor_id[a]}
            for a in album_ids
            if a not in missing_anchor
        ],
    }
    graph_path = tmp_path / "graph.v4.json"
    graph_path.write_text(json.dumps(graph))
    catalog = {
        "albums": [
            {
                "id": a,
                "artist_id": (artists or {}).get(a, 1000 + i),
                "artist": f"Artist {(artists or {}).get(a, 1000 + i)}",
                "title": f"Title {a}",
                "year": 1970 + i,
            }
            for i, a in enumerate(album_ids)
        ]
    }
    catalog_path = tmp_path / "albums.v1.json"
    catalog_path.write_text(json.dumps(catalog))
    return graph_path, catalog_path


def _projection(
    tmp_path: Path,
    spec: dict[str, list[int]],
    *,
    artists: dict[str, int] | None = None,
    min_shared: int = 2,
    include_same_artist: bool = False,
) -> dict[tuple[str, str], dict[str, Any]]:
    graph_path, catalog_path = _write_fixture(tmp_path, spec, artists=artists)
    published = load_published_graph(graph_path)
    albums = ap._load_catalog_albums(catalog_path)
    performers = ap.album_performer_sets(published, [a["id"] for a in albums])
    projection = ap.build_projection(
        albums, performers, min_shared=min_shared, include_same_artist=include_same_artist
    )
    return {(e["a"], e["b"]): e for e in projection["edges"]}


def test_projection_shared_counts_hub_weights_and_threshold(tmp_path: Path) -> None:
    # performer 1 on a,b,c ; performer 2 on a,b ; performer 3 on c only
    spec = {"a": [1, 2], "b": [1, 2], "c": [1, 3]}
    edges = _projection(tmp_path, spec, min_shared=1)
    assert set(edges) == {("a", "b"), ("a", "c"), ("b", "c")}
    assert edges[("a", "b")]["shared"] == 2
    assert edges[("a", "c")]["shared"] == 1
    w1, w2 = 1 / math.log(1 + 3), 1 / math.log(1 + 2)
    assert edges[("a", "b")]["weight"] == pytest.approx(w1 + w2)
    assert edges[("a", "c")]["weight"] == pytest.approx(w1)

    assert set(_projection(tmp_path, spec, min_shared=2)) == {("a", "b")}


def test_projection_same_artist_exclusion_on_and_off(tmp_path: Path) -> None:
    spec = {"a": [1, 2], "b": [1, 2], "c": [1, 2]}
    artists = {"a": 7, "b": 7, "c": 8}
    off = _projection(tmp_path, spec, artists=artists)
    assert set(off) == {("a", "c"), ("b", "c")}
    on = _projection(tmp_path, spec, artists=artists, include_same_artist=True)
    assert set(on) == {("a", "b"), ("a", "c"), ("b", "c")}


def _planted(groups: int = 5, per_group: int = 6) -> dict[str, list[int]]:
    spec: dict[str, list[int]] = {}
    for g in range(groups):
        pool = [100 * (g + 1) + k for k in range(5)]
        for i in range(per_group):
            spec[f"g{g}-a{i}"] = [p for k, p in enumerate(pool) if k != i % 5]
    # sparse cross links: one shared performer between neighbouring groups
    for g in range(groups - 1):
        spec[f"g{g}-a0"] = [*spec[f"g{g}-a0"], 900 + g]
        spec[f"g{g + 1}-a1"] = [*spec[f"g{g + 1}-a1"], 900 + g]
    return spec


def test_planted_partition_is_recovered_and_gate_block_is_data(tmp_path: Path) -> None:
    graph_path, catalog_path = _write_fixture(tmp_path, _planted())
    result = ap.run_study(graph_path, catalog_path, resolution=1.0, **FAST)

    assert result["clustering"]["size_distribution"] == [6, 6, 6, 6, 6]
    assert result["clustering"]["coverage"] == 1.0
    assert result["clustering"]["largest_cluster_share"] == pytest.approx(0.2)
    assert len(result["qualifying_clusters"]) == 5
    for cluster in result["qualifying_clusters"]:
        assert len({a["id"].split("-")[0] for a in cluster["albums"]}) == 1
        years = [a["year"] for a in cluster["albums"]]
        assert years == sorted(years)
        assert cluster["bridge_players"][0]["album_count"] >= 2
        assert len(cluster["bridge_players"]) <= ap.TOP_BRIDGE_PLAYERS

    gate = result["gate"]
    assert gate["owner_legibility_review"] == "pending"
    by_name = {c["name"]: c for c in gate["criteria"]}
    assert set(by_name) == {
        "largest_cluster_share",
        "coverage",
        "modularity_above_null_z",
        "modularity_above_bipartite_null_z",
    }
    assert by_name["largest_cluster_share"]["pass"] is True
    assert by_name["coverage"]["pass"] is True
    z = by_name["modularity_above_null_z"]
    assert z["threshold"] == 3.0
    assert z["pass"] is (z["measured"] is not None and z["measured"] >= 3.0)
    assert result["stability"]["seed_ari_min"] == pytest.approx(1.0)


def test_unstructured_sharing_does_not_pass_the_null_criterion(tmp_path: Path) -> None:
    rng = random.Random(7)
    spec = {f"r{i:02d}": rng.sample(range(1, 25), 7) for i in range(40)}
    graph_path, catalog_path = _write_fixture(tmp_path, spec)
    result = ap.run_study(graph_path, catalog_path, resolution=1.0, **FAST)
    by_name = {c["name"]: c for c in result["gate"]["criteria"]}
    # The stricter bipartite null (re-projected random incidence) must not be
    # passed by structureless sharing. The projection-rewiring null, as
    # specified, is reported too but is known to be biased towards passing
    # here (it destroys every projection's inherent clique structure), which
    # is exactly why the bipartite criterion exists.
    assert by_name["modularity_above_bipartite_null_z"]["pass"] is False
    assert result["bipartite_null_model"]["null_count"] == FAST["null_count"]


def test_output_is_deterministic(tmp_path: Path) -> None:
    graph_path, catalog_path = _write_fixture(tmp_path, _planted(4, 5))
    first = ap.dumps(ap.run_study(graph_path, catalog_path, **FAST))
    second = ap.dumps(ap.run_study(graph_path, catalog_path, **FAST))
    assert first == second
    assert "elapsed" not in first and "memory" not in first


def test_empty_graph_and_albums_without_anchor_neighbours(tmp_path: Path) -> None:
    graph_path, catalog_path = _write_fixture(tmp_path, {"a": [], "b": [], "c": [1]})
    result = ap.run_study(graph_path, catalog_path, **FAST)
    assert result["projection"]["edge_count"] == 0
    assert result["projection"]["albums_without_performers"] == 2
    assert result["clustering"]["coverage"] == 0.0
    assert all(not c["pass"] for c in result["gate"]["criteria"][1:])

    empty = ap.measure_projection([], {}, **FAST)
    assert empty["projection"]["album_count"] == 0
    assert empty["clustering"]["coverage"] is None
    assert empty["clustering"]["largest_cluster_share"] is None
    assert all(c["pass"] is False for c in empty["gate"]["criteria"])
    assert empty["gate"]["owner_legibility_review"] == "pending"


def test_album_missing_from_the_graph_is_a_singleton(tmp_path: Path) -> None:
    spec = {"a": [1, 2], "b": [1, 2], "c": [1, 2]}
    graph_path, catalog_path = _write_fixture(tmp_path, spec, missing_anchor={"c"})
    result = ap.run_study(graph_path, catalog_path, **FAST)
    assert result["projection"]["albums_without_performers"] == 1
    assert result["projection"]["edge_count"] == 1


def test_single_giant_clique_fails_the_largest_cluster_criterion(tmp_path: Path) -> None:
    spec = {f"k{i}": [1, 2, 3, 4] for i in range(8)}
    graph_path, catalog_path = _write_fixture(tmp_path, spec)
    result = ap.run_study(graph_path, catalog_path, resolution=1.0, **FAST)
    assert result["clustering"]["cluster_count"] == 1
    assert result["clustering"]["largest_cluster_share"] == 1.0
    by_name = {c["name"]: c for c in result["gate"]["criteria"]}
    assert by_name["largest_cluster_share"]["pass"] is False
    assert by_name["modularity_above_null_z"]["pass"] is False
    assert by_name["modularity_above_bipartite_null_z"]["pass"] is False
    assert result["qualifying_clusters"][0]["internal_density"] == 1.0


def test_sweep_covers_the_grid(tmp_path: Path) -> None:
    graph_path, catalog_path = _write_fixture(tmp_path, _planted(3, 5))
    sweep = ap.run_sweep(
        graph_path, catalog_path, seeds=(0, 1), null_count=3, perturbation_repeats=1
    )
    assert len(sweep["rows"]) == 9
    assert {(r["min_shared"], r["resolution"]) for r in sweep["rows"]} == {
        (m, r) for m in (1, 2, 3) for r in (1.0, 2.0, 3.0)
    }
    assert sweep["owner_legibility_review"] == "pending"
    assert "| min_shared |" in ap.render_sweep_markdown(sweep)


def test_cli_writes_json_and_markdown_and_refuses_public_tree(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    graph_path, catalog_path = _write_fixture(tmp_path, _planted(3, 5))
    out = tmp_path / "out" / "study.json"
    common = [
        "--graph", str(graph_path), "--catalog", str(catalog_path),
        "--seeds", "2", "--null-count", "3", "--perturbation-repeats", "1",
    ]  # fmt: skip
    assert main(["research-album-projection", *common, "--output", str(out)]) == 0
    assert json.loads(out.read_text())["kind"] == "album_projection_study"
    assert "Qualifying clusters" in out.with_suffix(".md").read_text()

    sweep_out = tmp_path / "out" / "sweep.json"
    assert main(["research-album-projection-sweep", *common, "--output", str(sweep_out)]) == 0
    assert json.loads(sweep_out.read_text())["kind"] == "album_projection_sweep"

    refused = tmp_path / "apps" / "web" / "public" / "data" / "x.json"
    assert main(["research-album-projection", *common, "--output", str(refused)]) == 2
    assert not refused.exists()
    assert "refusing" in capsys.readouterr().err
