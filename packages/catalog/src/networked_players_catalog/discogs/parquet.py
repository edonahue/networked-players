"""Bounded Parquet output for normalized Discogs releases and masters."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from collections.abc import Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.parquet as pq

from networked_players_catalog import __version__

from .releases import ParsedRelease

if TYPE_CHECKING:
    from .artists import ParsedArtistRelations
    from .masters import ParsedMaster

SCHEMA_VERSION = 3
MASTER_SCHEMA_VERSION = 1

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
RELEASE_FORMAT_SCHEMA = pa.schema(
    [
        ("snapshot_date", pa.string()),
        ("release_id", pa.int64()),
        ("format_index", pa.int32()),
        ("format_name", pa.string()),
        ("quantity", pa.int32()),
        ("format_text", pa.string()),
        ("descriptions", pa.list_(pa.string())),
    ]
)
SCHEMAS = {
    "releases": RELEASE_SCHEMA,
    "tracks": TRACK_SCHEMA,
    "credits": CREDIT_SCHEMA,
    "release_formats": RELEASE_FORMAT_SCHEMA,
}

MASTERS_SCHEMA = pa.schema(
    [
        ("snapshot_date", pa.string()),
        ("master_id", pa.int64()),
        ("main_release_id", pa.int64()),
        ("title", pa.string()),
        ("year", pa.int32()),
        ("genres", pa.list_(pa.string())),
        ("styles", pa.list_(pa.string())),
        ("data_quality", pa.string()),
        ("source_url", pa.string()),
    ]
)
MASTER_ARTISTS_SCHEMA = pa.schema(
    [
        ("snapshot_date", pa.string()),
        ("master_id", pa.int64()),
        ("artist_id", pa.int64()),
        ("name", pa.string()),
        ("anv", pa.string()),
        ("join_text", pa.string()),
        ("is_linked", pa.bool_()),
        ("playable_identity", pa.bool_()),
    ]
)
MASTER_SCHEMAS = {"masters": MASTERS_SCHEMA, "master_artists": MASTER_ARTISTS_SCHEMA}

ARTIST_RELATIONS_SCHEMA_VERSION = 1
ARTIST_RELATIONS_SCHEMA = pa.schema(
    [
        ("snapshot_date", pa.string()),
        ("artist_id", pa.int64()),
        ("related_artist_id", pa.int64()),
        ("related_name", pa.string()),
        ("relation", pa.string()),
        ("source_url", pa.string()),
    ]
)
ARTIST_RELATIONS_SCHEMAS = {"artist_relations": ARTIST_RELATIONS_SCHEMA}


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
    schemas: dict[str, pa.Schema] = SCHEMAS,
) -> Path | None:
    if not rows and not allow_empty:
        return None
    directory = root / f"table={table_name}"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"part-{part:05d}.parquet"
    table = pa.Table.from_pylist(rows, schema=schemas[table_name])
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


def _write_chunk(
    staging_root: Path,
    part: int,
    release_rows: list[dict[str, object]],
    track_rows: list[dict[str, object]],
    credit_rows: list[dict[str, object]],
    format_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    chunk_files: list[dict[str, object]] = []
    for table_name, rows in (
        ("releases", release_rows),
        ("tracks", track_rows),
        ("credits", credit_rows),
        ("release_formats", format_rows),
    ):
        path = _write_rows(staging_root, table_name, part, rows)
        if path is not None:
            chunk_files.append(
                {
                    "path": str(path.relative_to(staging_root)),
                    "size_bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                    "rows": len(rows),
                }
            )
    return chunk_files


def write_release_dataset(
    records: Iterable[ParsedRelease],
    output_root: Path,
    *,
    snapshot_date: str,
    source_url: str,
    chunk_releases: int = 5_000,
    overwrite: bool = False,
) -> dict[str, object]:
    """Write versioned, partitioned Parquet with bounded in-memory buffers.

    Each chunk's write (Parquet/zstd serialization + SHA-256 hashing) runs on a
    single background thread while the next chunk continues accumulating on the
    main thread. Real profiling (docs/DATA_SIZING.md) found writing is ~9% of
    total time -- pyarrow's C++ write path and hashlib's C-backed digest updates
    both release the GIL for their actual work, so this is genuine overlap, not
    just thread-switching overhead. At most one write is ever in flight (a fresh
    set of row lists starts accumulating immediately after handing the completed
    chunk to the executor; the *next* flush waits for that prior write's result
    before submitting again), so memory stays bounded exactly like before --
    this never turns into an unbounded background queue.
    """

    if chunk_releases <= 0:
        raise ValueError("chunk_releases must be positive")
    final_root = output_root / f"snapshot={snapshot_date}"
    if final_root.exists() and not overwrite:
        raise FileExistsError(f"dataset already exists: {final_root}")

    staging_root = output_root / f".snapshot={snapshot_date}.tmp-{uuid.uuid4().hex}"
    staging_root.mkdir(parents=True, exist_ok=False)
    counts = {"releases": 0, "tracks": 0, "credits": 0, "release_formats": 0}
    files: list[dict[str, object]] = []
    release_rows: list[dict[str, object]] = []
    track_rows: list[dict[str, object]] = []
    credit_rows: list[dict[str, object]] = []
    format_rows: list[dict[str, object]] = []
    part = 0
    pending: Future[list[dict[str, object]]] | None = None

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:

            def start_flush() -> None:
                nonlocal release_rows, track_rows, credit_rows, format_rows, part, pending
                if pending is not None:
                    files.extend(pending.result())
                pending = executor.submit(
                    _write_chunk,
                    staging_root,
                    part,
                    release_rows,
                    track_rows,
                    credit_rows,
                    format_rows,
                )
                release_rows, track_rows, credit_rows, format_rows = [], [], [], []
                part += 1

            for record in records:
                release_rows.append(record.release)
                track_rows.extend(record.tracks)
                credit_rows.extend(record.credits)
                format_rows.extend(record.formats)
                counts["releases"] += 1
                counts["tracks"] += len(record.tracks)
                counts["credits"] += len(record.credits)
                counts["release_formats"] += len(record.formats)
                if len(release_rows) >= chunk_releases:
                    start_flush()
            if release_rows or track_rows or credit_rows or format_rows:
                start_flush()
            if pending is not None:
                files.extend(pending.result())
        if counts["releases"] == 0:
            raise ValueError("no release records were parsed")

        for table_name in ("tracks", "credits", "release_formats"):
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


def write_master_dataset(
    records: Iterable[ParsedMaster],
    output_root: Path,
    *,
    snapshot_date: str,
    source_url: str,
    chunk_masters: int = 10_000,
    overwrite: bool = False,
) -> dict[str, object]:
    """Write a versioned masters dataset -- same staging-dir/atomic-rename/
    manifest posture as ``write_release_dataset``, two tables (``masters``
    and ``master_artists``), its own ``MASTER_SCHEMA_VERSION``. Kept as a
    sibling rather than folded into the release writer: the chunking and
    background-write machinery is simple enough that sharing it would couple
    two independently-versioned schemas to one function signature.
    """

    if chunk_masters <= 0:
        raise ValueError("chunk_masters must be positive")
    final_root = output_root / f"snapshot={snapshot_date}"
    if final_root.exists() and not overwrite:
        raise FileExistsError(f"dataset already exists: {final_root}")

    staging_root = output_root / f".snapshot={snapshot_date}.tmp-{uuid.uuid4().hex}"
    staging_root.mkdir(parents=True, exist_ok=False)
    counts = {"masters": 0, "master_artists": 0}
    files: list[dict[str, object]] = []
    master_rows: list[dict[str, object]] = []
    artist_rows: list[dict[str, object]] = []
    part = 0
    pending: Future[list[dict[str, object]]] | None = None

    def _write_master_chunk(
        chunk_part: int,
        chunk_masters_rows: list[dict[str, object]],
        chunk_artist_rows: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        chunk_files: list[dict[str, object]] = []
        for table_name, rows in (
            ("masters", chunk_masters_rows),
            ("master_artists", chunk_artist_rows),
        ):
            path = _write_rows(staging_root, table_name, chunk_part, rows, schemas=MASTER_SCHEMAS)
            if path is not None:
                chunk_files.append(
                    {
                        "path": str(path.relative_to(staging_root)),
                        "size_bytes": path.stat().st_size,
                        "sha256": _sha256(path),
                        "rows": len(rows),
                    }
                )
        return chunk_files

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:

            def start_flush() -> None:
                nonlocal master_rows, artist_rows, part, pending
                if pending is not None:
                    files.extend(pending.result())
                pending = executor.submit(_write_master_chunk, part, master_rows, artist_rows)
                master_rows, artist_rows = [], []
                part += 1

            for record in records:
                master_rows.append(record.master)
                artist_rows.extend(record.artists)
                counts["masters"] += 1
                counts["master_artists"] += len(record.artists)
                if len(master_rows) >= chunk_masters:
                    start_flush()
            if master_rows or artist_rows:
                start_flush()
            if pending is not None:
                files.extend(pending.result())
        if counts["masters"] == 0:
            raise ValueError("no master records were parsed")

        artists_prefix = "table=master_artists/"
        if not any(str(item["path"]).startswith(artists_prefix) for item in files):
            path = _write_rows(
                staging_root, "master_artists", 0, [], allow_empty=True, schemas=MASTER_SCHEMAS
            )
            if path is None:
                raise AssertionError("failed to create empty master_artists table")
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
            "schema_version": MASTER_SCHEMA_VERSION,
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


def write_artist_relations_dataset(
    records: Iterable[ParsedArtistRelations],
    output_root: Path,
    *,
    snapshot_date: str,
    source_url: str,
    chunk_artists: int = 50_000,
    overwrite: bool = False,
) -> dict[str, object]:
    """Write a versioned artist-relations dataset -- same staging-dir/atomic-
    rename/manifest posture as ``write_master_dataset``, one table
    (``artist_relations``), its own ``ARTIST_RELATIONS_SCHEMA_VERSION``.
    Every parsed artist record contributes zero or more rows (most artists
    have neither ``<groups>`` nor ``<members>``), so ``counts["artists_seen"]``
    (records streamed) and ``counts["artist_relations"]`` (rows written) are
    tracked separately.
    """

    if chunk_artists <= 0:
        raise ValueError("chunk_artists must be positive")
    final_root = output_root / f"snapshot={snapshot_date}"
    if final_root.exists() and not overwrite:
        raise FileExistsError(f"dataset already exists: {final_root}")

    staging_root = output_root / f".snapshot={snapshot_date}.tmp-{uuid.uuid4().hex}"
    staging_root.mkdir(parents=True, exist_ok=False)
    counts = {"artists_seen": 0, "artist_relations": 0}
    files: list[dict[str, object]] = []
    relation_rows: list[dict[str, object]] = []
    part = 0
    pending: Future[list[dict[str, object]]] | None = None

    def _write_relations_chunk(
        chunk_part: int, chunk_rows: list[dict[str, object]]
    ) -> list[dict[str, object]]:
        path = _write_rows(
            staging_root,
            "artist_relations",
            chunk_part,
            chunk_rows,
            schemas=ARTIST_RELATIONS_SCHEMAS,
        )
        if path is None:
            return []
        return [
            {
                "path": str(path.relative_to(staging_root)),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
                "rows": len(chunk_rows),
            }
        ]

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:

            def start_flush() -> None:
                nonlocal relation_rows, part, pending
                if pending is not None:
                    files.extend(pending.result())
                pending = executor.submit(_write_relations_chunk, part, relation_rows)
                relation_rows = []
                part += 1

            for record in records:
                counts["artists_seen"] += 1
                relation_rows.extend(record.relations)
                counts["artist_relations"] += len(record.relations)
                if len(relation_rows) >= chunk_artists:
                    start_flush()
            if relation_rows:
                start_flush()
            if pending is not None:
                files.extend(pending.result())
        if counts["artists_seen"] == 0:
            raise ValueError("no artist records were parsed")

        relations_prefix = "table=artist_relations/"
        if not any(str(item["path"]).startswith(relations_prefix) for item in files):
            path = _write_rows(
                staging_root,
                "artist_relations",
                0,
                [],
                allow_empty=True,
                schemas=ARTIST_RELATIONS_SCHEMAS,
            )
            if path is None:
                raise AssertionError("failed to create empty artist_relations table")
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
            "schema_version": ARTIST_RELATIONS_SCHEMA_VERSION,
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
