"""CLI round-trip for `measure-coverage-gaps` -- Phase 7 Bucket C's
measurement input. Unit coverage for the underlying pure functions lives in
packages/graph-core/tests/test_coverage_gaps.py; this pins the CLI wiring,
the local-only output guard, and the masters-lookup batching only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")
pytest.importorskip("duckdb")

import pyarrow as pa
import pyarrow.parquet as pq

from networked_players_catalog.cli import main


def _write_masters(root: Path, rows: list[dict]) -> Path:
    (root / "table=masters").mkdir(parents=True)
    schema = pa.schema(
        [
            ("master_id", pa.int64()),
            ("year", pa.int32()),
            ("genres", pa.list_(pa.string())),
            ("styles", pa.list_(pa.string())),
        ]
    )
    pq.write_table(
        pa.Table.from_pylist(rows, schema=schema), root / "table=masters" / "part-00000.parquet"
    )
    return root


def test_measures_composition_and_writes_underrepresented_gaps(tmp_path: Path) -> None:
    catalog_path = tmp_path / "albums.v1.json"
    catalog_path.write_text(
        json.dumps(
            {
                "catalog_version": "catalog-v1-20260601-test",
                "albums": [
                    {"master_id": 1, "year": 1999},
                    {"master_id": 2, "year": 1999},
                    {"master_id": 3, "year": 1999},
                ],
            }
        )
    )
    masters_root = _write_masters(
        tmp_path / "masters",
        [
            {"master_id": 1, "year": 1972, "genres": ["Rock"], "styles": ["Pop Rock"]},
            {"master_id": 2, "year": 1972, "genres": ["Rock"], "styles": ["Pop Rock"]},
            {"master_id": 3, "year": 2005, "genres": ["Jazz"], "styles": ["Bop"]},
        ],
    )
    output = tmp_path / "local" / "research" / "coverage-gaps.json"

    exit_code = main(
        [
            "measure-coverage-gaps",
            "--catalog",
            str(catalog_path),
            "--masters-root",
            str(masters_root),
            "--min-count",
            "2",
            "--output",
            str(output),
        ]
    )
    assert exit_code == 0

    payload = json.loads(output.read_text())
    assert payload["catalog_version"] == "catalog-v1-20260601-test"
    assert payload["album_count"] == 3
    assert payload["masters_resolved"] == 3
    assert payload["composition"]["decades"] == {"1970s": 2, "2000s": 1}
    assert payload["composition"]["genres"] == {"Jazz": 1, "Rock": 2}
    gap_buckets = {(f["dimension"], f["bucket"]) for f in payload["underrepresented"]}
    assert ("decades", "2000s") in gap_buckets
    assert ("genres", "Jazz") in gap_buckets
    assert ("decades", "1970s") not in gap_buckets


def test_refuses_to_write_outside_local(tmp_path: Path) -> None:
    catalog_path = tmp_path / "albums.v1.json"
    catalog_path.write_text(json.dumps({"catalog_version": "x", "albums": []}))
    masters_root = _write_masters(tmp_path / "masters", [])
    output = tmp_path / "apps" / "web" / "public" / "data" / "gaps.json"

    with pytest.raises(ValueError, match="refuses to write outside local/"):
        main(
            [
                "measure-coverage-gaps",
                "--catalog",
                str(catalog_path),
                "--masters-root",
                str(masters_root),
                "--output",
                str(output),
            ]
        )
    assert not output.exists()
