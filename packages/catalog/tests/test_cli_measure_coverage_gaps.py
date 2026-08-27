"""CLI round-trip for `measure-coverage-gaps` -- Phase 7 Bucket C's
measurement input. Unit coverage for the underlying pure functions lives in
packages/graph-core/tests/test_coverage_gaps.py; this pins the CLI wiring,
the snapshot cross-check, the known-vocabulary derivation, and the
local-only output guard."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")
pytest.importorskip("duckdb")

import pyarrow as pa
import pyarrow.parquet as pq

from networked_players_catalog.cli import main

SNAPSHOT = "20260601"


def _write_masters(root: Path, rows: list[dict], *, snapshot_date: str = SNAPSHOT) -> Path:
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
    (root / "manifest.json").write_text(json.dumps({"snapshot_date": snapshot_date}))
    return root


def _write_catalog(path: Path, albums: list[dict], *, snapshot_date: str = SNAPSHOT) -> Path:
    path.write_text(
        json.dumps(
            {
                "catalog_version": f"catalog-v1-{snapshot_date}-test",
                "snapshot_date": snapshot_date,
                "albums": albums,
            }
        )
    )
    return path


def test_measures_composition_and_writes_underrepresented_gaps(tmp_path: Path) -> None:
    catalog_path = _write_catalog(
        tmp_path / "albums.v1.json",
        [
            {"master_id": 1, "year": 1999},
            {"master_id": 2, "year": 1999},
            {"master_id": 3, "year": 1999},
        ],
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
    assert payload["album_count"] == 3
    assert payload["masters_resolved"] == 3
    assert payload["composition"]["decades"] == {"1970s": 2, "2000s": 1}
    assert payload["composition"]["genres"] == {"Jazz": 1, "Rock": 2}
    gap_buckets = {(f["dimension"], f["bucket"]) for f in payload["underrepresented"]}
    assert ("decades", "2000s") in gap_buckets
    assert ("genres", "Jazz") in gap_buckets
    assert ("decades", "1970s") not in gap_buckets


def test_a_genre_absent_from_the_catalog_but_real_in_the_masters_snapshot_is_a_zero_gap(
    tmp_path: Path,
) -> None:
    """The real bug this guards: without deriving a known vocabulary from the
    full masters snapshot, a genre with zero catalog representation never
    gets a key in `composition` at all -- the strongest possible coverage
    gap would be silently invisible."""
    catalog_path = _write_catalog(tmp_path / "albums.v1.json", [{"master_id": 1, "year": 1999}])
    # The masters table carries a master for a genre no catalog album uses
    # (Reggae, master_id=2) -- real evidence the genre exists in the wider
    # snapshot, even though nothing in the small catalog above references it.
    masters_root = _write_masters(
        tmp_path / "masters",
        [
            {"master_id": 1, "year": 1999, "genres": ["Rock"], "styles": []},
            {"master_id": 2, "year": 1999, "genres": ["Reggae"], "styles": []},
        ],
    )
    output = tmp_path / "local" / "gaps.json"

    exit_code = main(
        [
            "measure-coverage-gaps",
            "--catalog",
            str(catalog_path),
            "--masters-root",
            str(masters_root),
            "--min-count",
            "1",
            "--output",
            str(output),
        ]
    )
    assert exit_code == 0
    payload = json.loads(output.read_text())
    reggae = [f for f in payload["underrepresented"] if f["bucket"] == "Reggae"]
    assert reggae == [{"dimension": "genres", "bucket": "Reggae", "count": 0}]


def test_masters_snapshot_mismatch_is_refused(tmp_path: Path) -> None:
    catalog_path = _write_catalog(tmp_path / "albums.v1.json", [], snapshot_date="20260601")
    masters_root = _write_masters(tmp_path / "masters", [], snapshot_date="20200101")
    output = tmp_path / "local" / "gaps.json"

    with pytest.raises(ValueError, match="mismatched-snapshot"):
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


def test_refuses_to_write_outside_local(tmp_path: Path) -> None:
    catalog_path = _write_catalog(tmp_path / "albums.v1.json", [])
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
