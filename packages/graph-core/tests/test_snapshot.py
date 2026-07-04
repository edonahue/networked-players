from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from networked_players_graph_core.snapshot import SnapshotError, export_graph_snapshot


def _read_table(root: Path, table: str) -> list[dict]:
    return pq.read_table(root / f"table={table}" / "part-00000.parquet").to_pylist()


def test_export_produces_expected_artists_and_edges(dataset_root: Path, tmp_path: Path) -> None:
    output_root = tmp_path / "graph"

    manifest = export_graph_snapshot(dataset_root, output_root)

    assert manifest["counts"] == {"artists": 8, "edges": 10}
    final_root = output_root / "snapshot=20260601"

    artists = _read_table(final_root, "artists")
    assert sorted(a["artist_id"] for a in artists) == [100, 200, 300, 400, 500, 501, 502, 600]
    alice = next(a for a in artists if a["artist_id"] == 100)
    assert alice["name"] == "Alice"

    edges = {(e["artist_a_id"], e["artist_b_id"]): e for e in _read_table(final_root, "edges")}
    assert set(edges) == {
        (100, 200),
        (100, 500),
        (100, 501),
        (100, 502),
        (200, 300),
        (300, 400),
        (400, 500),
        (500, 501),
        (500, 502),
        (501, 502),
    }
    # The Mega Compilation (release 4) drives six of the ten edges.
    assert edges[(100, 500)]["release_ids"] == [4]
    assert edges[(400, 500)]["release_ids"] == [6]
    assert edges[(100, 200)]["release_count"] == 1


def test_export_respects_max_artists_per_release_cap(dataset_root: Path, tmp_path: Path) -> None:
    manifest = export_graph_snapshot(dataset_root, tmp_path / "graph", max_artists_per_release=3)

    # Release 4 (4 distinct artists) is excluded; only the four two-artist
    # releases (1, 2, 3, 6) remain, each contributing exactly one edge.
    assert manifest["counts"]["edges"] == 4
    # Artist rows are never capped -- every playable artist still appears.
    assert manifest["counts"]["artists"] == 8


def test_export_is_deterministic(dataset_root: Path, tmp_path: Path) -> None:
    first = export_graph_snapshot(dataset_root, tmp_path / "graph-a")
    second = export_graph_snapshot(dataset_root, tmp_path / "graph-b")

    first_hashes = {f["path"]: f["sha256"] for f in first["files"]}
    second_hashes = {f["path"]: f["sha256"] for f in second["files"]}
    assert first_hashes == second_hashes


def test_export_refuses_to_overwrite_without_flag(dataset_root: Path, tmp_path: Path) -> None:
    output_root = tmp_path / "graph"
    export_graph_snapshot(dataset_root, output_root)

    with pytest.raises(FileExistsError):
        export_graph_snapshot(dataset_root, output_root)

    # overwrite=True succeeds and replaces the snapshot cleanly.
    manifest = export_graph_snapshot(dataset_root, output_root, overwrite=True)
    assert manifest["counts"]["artists"] == 8


def test_export_records_generation_provenance(dataset_root: Path, tmp_path: Path) -> None:
    manifest = export_graph_snapshot(dataset_root, tmp_path / "graph", max_artists_per_release=7)

    generation = manifest["generation"]
    assert generation["max_artists_per_release"] == 7
    assert "CreditGraph" in generation["method"]
    assert len(generation["source_manifest_sha256"]) == 64


def test_export_raises_on_missing_manifest(tmp_path: Path) -> None:
    with pytest.raises(SnapshotError, match=r"no manifest\.json"):
        export_graph_snapshot(tmp_path / "does-not-exist", tmp_path / "graph")


def test_export_cli_wiring(dataset_root: Path, tmp_path: Path, capsys) -> None:
    from networked_players_catalog.cli import main

    output_root = tmp_path / "graph"
    exit_code = main(
        [
            "export-graph-snapshot",
            "--dataset",
            str(dataset_root),
            "--output-root",
            str(output_root),
        ]
    )
    assert exit_code == 0
    manifest = json.loads(capsys.readouterr().out)
    assert manifest["counts"]["artists"] == 8
