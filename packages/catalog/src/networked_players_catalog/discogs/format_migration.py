"""Targeted schema-v3 migration for an existing release-shaped dataset."""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from networked_players_catalog import __version__

from .parquet import RELEASE_FORMAT_SCHEMA, SCHEMA_VERSION, _sha256
from .releases import iter_release_formats


def migrate_dataset_with_formats(
    input_dataset: Path,
    raw_dump: Path,
    output_root: Path,
    *,
    snapshot_date: str,
    source_url: str,
    chunk_rows: int = 50_000,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Copy an existing dataset and add formats for its release IDs.

    This avoids reprocessing the existing credit/track tables while still
    deriving format evidence from the authoritative local XML dump.
    """
    input_root = Path(input_dataset)
    output_root = Path(output_root)
    input_manifest_path = input_root / "manifest.json"
    if not input_manifest_path.is_file():
        raise ValueError(f"no manifest.json under {input_root}")
    input_manifest = json.loads(input_manifest_path.read_text())
    if str(input_manifest.get("snapshot_date")) != snapshot_date:
        raise ValueError("input dataset snapshot does not match requested snapshot")
    final_root = output_root / f"snapshot={snapshot_date}"
    if final_root.exists() and not overwrite:
        raise FileExistsError(f"dataset already exists: {final_root}")

    releases_glob = str(input_root / "table=releases" / "*.parquet")
    connection = duckdb.connect(database=":memory:")
    try:
        release_ids = {
            int(row[0])
            for row in connection.execute(
                f"SELECT release_id FROM read_parquet('{releases_glob}', hive_partitioning=false)"
            ).fetchall()
        }
    finally:
        connection.close()

    staging_root = output_root / f".snapshot={snapshot_date}.tmp-{uuid.uuid4().hex}"
    staging_root.mkdir(parents=True, exist_ok=False)
    files: list[dict[str, Any]] = []
    counts = dict(input_manifest.get("counts", {}))
    counts["release_formats"] = 0
    try:
        for child in input_root.iterdir():
            if child.name == "manifest.json" or not child.is_dir():
                continue
            shutil.copytree(child, staging_root / child.name)

        format_dir = staging_root / "table=release_formats"
        format_dir.mkdir(parents=True, exist_ok=True)
        rows: list[dict[str, object]] = []
        part = 0
        for row in iter_release_formats(
            raw_dump, snapshot_date=snapshot_date, release_ids=release_ids
        ):
            rows.append(row)
            if len(rows) >= chunk_rows:
                path = format_dir / f"part-{part:05d}.parquet"
                pq.write_table(pa.Table.from_pylist(rows, schema=RELEASE_FORMAT_SCHEMA), path)
                counts["release_formats"] += len(rows)
                part += 1
                rows = []
        if rows or part == 0:
            path = format_dir / f"part-{part:05d}.parquet"
            pq.write_table(pa.Table.from_pylist(rows, schema=RELEASE_FORMAT_SCHEMA), path)
            counts["release_formats"] += len(rows)

        for path in sorted(staging_root.glob("table=*/*.parquet")):
            files.append(
                {
                    "path": str(path.relative_to(staging_root)),
                    "size_bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                    "rows": int(pq.ParquetFile(path).metadata.num_rows),
                }
            )
        manifest = {
            "dataset_manifest_version": 1,
            "schema_version": SCHEMA_VERSION,
            "parser_version": __version__,
            "source": input_manifest.get("source", "Discogs monthly data dumps"),
            "source_url": source_url,
            "snapshot_date": snapshot_date,
            "generated_at": datetime.now(UTC).isoformat(),
            "compression": "zstd",
            "counts": counts,
            "files": files,
            "migration": {
                "kind": "add-release-formats",
                "source_manifest_sha256": _sha256(input_manifest_path),
                "raw_dump_not_embedded": True,
            },
        }
        (staging_root / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        )
        if final_root.exists():
            shutil.rmtree(final_root)
        staging_root.replace(final_root)
        return manifest
    except Exception:
        shutil.rmtree(staging_root, ignore_errors=True)
        raise
