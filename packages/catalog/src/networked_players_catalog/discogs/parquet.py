"""Bounded Parquet output for normalized Discogs releases."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from networked_players_catalog import __version__

from .releases import ParsedRelease

SCHEMA_VERSION = 2

RELEASE_SCHEMA = pa.schema(
    [
        ("snapshot_date", pa.string()),
        ("release_id", pa.int64()),
        ("status", pa.string()),
        ("title", pa.string()),
        ("country", pa.string()),
        ("released", pa.string()),
        ("master_id", pa.int64()),
        ("master_is_main_release", pa.bool_()),
        ("data_quality", pa.string()),
        ("source_url", pa.string()),
    ]
)
TRACK_SCHEMA = pa.schema(
    [
        ("snapshot_date", pa.string()),
        ("release_id", pa.int64()),
        ("track_index", pa.int32()),
        ("parent_track_index", pa.int32()),
        ("track_path", pa.string()),
        ("position", pa.string()),
        ("title", pa.string()),
        ("duration", pa.string()),
    ]
)
CREDIT_SCHEMA = pa.schema(
    [
        ("snapshot_date", pa.string()),
        ("release_id", pa.int64()),
        ("track_index", pa.int32()),
        ("track_path", pa.string()),
        ("track_position", pa.string()),
        ("track_title", pa.string()),
        ("credit_scope", pa.string()),
        ("artist_id", pa.int64()),
        ("name", pa.string()),
        ("anv", pa.string()),
        ("join_text", pa.string()),
        ("role_text", pa.string()),
        ("credited_tracks_text", pa.string()),
        ("is_linked", pa.bool_()),
        ("playable_identity", pa.bool_()),
    ]
)
SCHEMAS = {"releases": RELEASE_SCHEMA, "tracks": TRACK_SCHEMA, "credits": CREDIT_SCHEMA}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_rows(
    root: Path,
    table_name: str,
    part: int,
    rows: list[dict[str, object]],
    *,
    allow_empty: bool = False,
) -> Path | None:
    if not rows and not allow_empty:
        return None
    directory = root / f"table={table_name}"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"part-{part:05d}.parquet"
    table = pa.Table.from_pylist(rows, schema=SCHEMAS[table_name])
    pq.write_table(
        table,
        path,
        compression="zstd",
        compression_level=6,
        use_dictionary=True,
        row_group_size=50_000,
        write_statistics=True,
    )
    return path


def write_release_dataset(
    records: Iterable[ParsedRelease],
    output_root: Path,
    *,
    snapshot_date: str,
    source_url: str,
    chunk_releases: int = 5_000,
    overwrite: bool = False,
) -> dict[str, object]:
    """Write versioned, partitioned Parquet with bounded in-memory buffers."""

    if chunk_releases <= 0:
        raise ValueError("chunk_releases must be positive")
    final_root = output_root / f"snapshot={snapshot_date}"
    if final_root.exists() and not overwrite:
        raise FileExistsError(f"dataset already exists: {final_root}")

    staging_root = output_root / f".snapshot={snapshot_date}.tmp-{uuid.uuid4().hex}"
    staging_root.mkdir(parents=True, exist_ok=False)
    counts = {"releases": 0, "tracks": 0, "credits": 0}
    files: list[dict[str, object]] = []
    release_rows: list[dict[str, object]] = []
    track_rows: list[dict[str, object]] = []
    credit_rows: list[dict[str, object]] = []
    part = 0

    def flush() -> None:
        nonlocal part
        for table_name, rows in (
            ("releases", release_rows),
            ("tracks", track_rows),
            ("credits", credit_rows),
        ):
            path = _write_rows(staging_root, table_name, part, rows)
            if path is not None:
                files.append(
                    {
                        "path": str(path.relative_to(staging_root)),
                        "size_bytes": path.stat().st_size,
                        "sha256": _sha256(path),
                        "rows": len(rows),
                    }
                )
            rows.clear()
        part += 1

    try:
        for record in records:
            release_rows.append(record.release)
            track_rows.extend(record.tracks)
            credit_rows.extend(record.credits)
            counts["releases"] += 1
            counts["tracks"] += len(record.tracks)
            counts["credits"] += len(record.credits)
            if len(release_rows) >= chunk_releases:
                flush()
        if release_rows or track_rows or credit_rows:
            flush()
        if counts["releases"] == 0:
            raise ValueError("no release records were parsed")

        for table_name in ("tracks", "credits"):
            prefix = f"table={table_name}/"
            if not any(str(item["path"]).startswith(prefix) for item in files):
                path = _write_rows(staging_root, table_name, 0, [], allow_empty=True)
                if path is None:
                    raise AssertionError(f"failed to create empty {table_name} table")
                files.append(
                    {
                        "path": str(path.relative_to(staging_root)),
                        "size_bytes": path.stat().st_size,
                        "sha256": _sha256(path),
                        "rows": 0,
                    }
                )

        manifest: dict[str, object] = {
            "dataset_manifest_version": 1,
            "schema_version": SCHEMA_VERSION,
            "parser_version": __version__,
            "source": "Discogs monthly data dumps",
            "source_url": source_url,
            "snapshot_date": snapshot_date,
            "generated_at": datetime.now(UTC).isoformat(),
            "compression": "zstd",
            "counts": counts,
            "files": files,
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
