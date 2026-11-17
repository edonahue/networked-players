"""Bounded Parquet output for normalized Discogs releases and masters."""

from __future__ import annotations

import hashlib
import itertools
import json
import logging
import os
import shutil
import uuid
from collections.abc import Iterable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pyarrow as pa
import pyarrow.parquet as pq

from networked_players_catalog import __version__

from .releases import (
    ParsedRelease,
    SkipReport,
    iter_releases,
    release_id_digest_update,
)
from .resume import (
    LOCK_FILENAME,
    PROGRESS_FILENAME,
    PROGRESS_VERSION,
    STATE_FINALIZED,
    STATE_IN_PROGRESS,
    ResumeRefused,
    check_input_identity,
    check_parameters,
    cleanup_promoted_leftovers,
    describe_input,
    find_staging_dirs,
    fsync_directory,
    load_progress,
    lock_is_held,
    sha256_file,
    validate_and_clean_staging,
    write_json_atomic,
    writer_lock,
)

if TYPE_CHECKING:
    from .artists import ParsedArtistRelations
    from .masters import ParsedMaster

logger = logging.getLogger(__name__)

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
    """Write one part atomically: temp name in the same directory, fsync, rename.

    A file under its final ``part-NNNNN.parquet`` name is therefore always complete. The
    temp name ends in ``.tmp`` (hidden, never matched by ``*.parquet`` globs).
    """
    if not rows and not allow_empty:
        return None
    directory = root / f"table={table_name}"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"part-{part:05d}.parquet"
    tmp = directory / f".{path.name}.tmp"
    table = pa.Table.from_pylist(rows, schema=schemas[table_name])
    with tmp.open("wb") as handle:
        pq.write_table(
            table,
            handle,
            compression="zstd",
            compression_level=6,
            use_dictionary=True,
            row_group_size=50_000,
            write_statistics=True,
        )
        handle.flush()
        os.fsync(handle.fileno())
    _replace_into_place(tmp, path)
    fsync_directory(directory)
    return path


def _replace_into_place(tmp: Path, final: Path) -> None:
    """Rename step of an atomic part write (a seam for crash-injection tests)."""
    os.replace(tmp, final)


def _promote(staging_root: Path, final_root: Path) -> None:
    """Promote a finished staging directory (a seam for crash-injection tests)."""
    if final_root.exists():
        shutil.rmtree(final_root)
    staging_root.replace(final_root)
    fsync_directory(final_root.parent)
    _remove_promoted_leftovers(final_root)


def _remove_promoted_leftovers(final_root: Path) -> None:
    """Drop the progress record and lock file that moved with the staging dir.

    Deliberately after the rename (never before: a finalized-but-unpromoted dir must stay
    resumable). A crash in between is healed by ``cleanup_promoted_leftovers``.
    """
    for name in (PROGRESS_FILENAME, LOCK_FILENAME):
        leftover = final_root / name
        if leftover.exists():
            leftover.unlink()


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


def _progress_payload(
    *,
    state: str,
    params: dict[str, object],
    parts_completed: int,
    releases_persisted: int,
    last_release_id: int | None,
    digest_hex: str,
    counts: dict[str, int],
    files: list[dict[str, object]],
    manifest_sha256: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "progress_version": PROGRESS_VERSION,
        "state": state,
        **params,
        "parts_completed": parts_completed,
        "releases_persisted": releases_persisted,
        "last_release_id": last_release_id,
        "release_id_digest": digest_hex,
        "counts": dict(counts),
        "files": list(files),
    }
    if manifest_sha256 is not None:
        payload["manifest_sha256"] = manifest_sha256
    return payload


def _run_params(
    *,
    snapshot_date: str,
    source_url: str,
    chunk_releases: int,
    max_releases: int | None,
    input_identity: dict[str, object] | None,
) -> dict[str, object]:
    return {
        "snapshot_date": snapshot_date,
        "source_url": source_url,
        "schema_version": SCHEMA_VERSION,
        "parser_version": __version__,
        "pyarrow_version": pa.__version__,
        "chunk_releases": chunk_releases,
        "max_releases": max_releases,
        "input": input_identity
        or {"filename": None, "size_bytes": None, "sha256": None, "sha256_source": None},
    }


def write_release_dataset(
    records: Iterable[ParsedRelease],
    output_root: Path,
    *,
    snapshot_date: str,
    source_url: str,
    chunk_releases: int = 5_000,
    overwrite: bool = False,
    max_releases: int | None = None,
    input_identity: dict[str, object] | None = None,
) -> dict[str, object]:
    """Write versioned, partitioned Parquet with bounded in-memory buffers.

    Starts a fresh staging directory (see ``parse_release_dump`` for resume). Each part is
    written atomically and a ``progress.json`` record is updated atomically after every
    completed part, so an interrupted run can be resumed.

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
    cleanup_promoted_leftovers(final_root)
    if final_root.exists() and not overwrite:
        raise FileExistsError(f"dataset already exists: {final_root}")
    existing = find_staging_dirs(output_root, snapshot_date)
    if existing:
        running = [p.name for p in existing if lock_is_held(p)]
        raise FileExistsError(
            f"a staging directory for snapshot {snapshot_date} already exists "
            f"({', '.join(p.name for p in existing)})"
            + (f"; {', '.join(running)} is locked by a running writer" if running else "")
            + ". It may hold resumable output: re-run with --resume, or inspect it with "
            "scripts/check-ingest-recovery.sh (scripts/check_ingest_recovery.py) and "
            "delete it to start over."
        )
    staging_root = output_root / f".snapshot={snapshot_date}.tmp-{uuid.uuid4().hex}"
    staging_root.mkdir(parents=True, exist_ok=False)
    params = _run_params(
        snapshot_date=snapshot_date,
        source_url=source_url,
        chunk_releases=chunk_releases,
        max_releases=max_releases,
        input_identity=input_identity,
    )
    with writer_lock(staging_root):
        return _write_release_dataset(
            records,
            staging_root,
            final_root,
            params=params,
            resume_record=None,
            skip_report=None,
        )


_END = object()


def _write_release_dataset(
    records: Iterable[ParsedRelease],
    staging_root: Path,
    final_root: Path,
    *,
    params: dict[str, object],
    resume_record: dict[str, Any] | None,
    skip_report: SkipReport | None,
) -> dict[str, object]:
    chunk_releases = int(str(params["chunk_releases"]))
    snapshot_date = str(params["snapshot_date"])
    source_url = str(params["source_url"])
    counts = {"releases": 0, "tracks": 0, "credits": 0, "release_formats": 0}
    files: list[dict[str, object]] = []
    release_rows: list[dict[str, object]] = []
    track_rows: list[dict[str, object]] = []
    credit_rows: list[dict[str, object]] = []
    format_rows: list[dict[str, object]] = []
    part = 0
    persisted = 0
    last_release_id: int | None = None
    digest = hashlib.sha256()
    pending: Future[list[dict[str, object]]] | None = None
    pending_boundary: dict[str, Any] | None = None
    progress_path = staging_root / PROGRESS_FILENAME

    def write_progress(
        *,
        boundary: dict[str, Any],
        state: str = STATE_IN_PROGRESS,
        manifest_sha256: str | None = None,
    ) -> None:
        write_json_atomic(
            progress_path,
            _progress_payload(
                state=state,
                params=params,
                parts_completed=boundary["parts"],
                releases_persisted=boundary["persisted"],
                last_release_id=boundary["last_id"],
                digest_hex=boundary["digest"],
                counts=boundary["counts"],
                files=files,
                manifest_sha256=manifest_sha256,
            ),
        )

    def boundary_now() -> dict[str, Any]:
        return {
            "parts": part,
            "persisted": persisted,
            "last_id": last_release_id,
            "digest": digest.hexdigest(),
            "counts": dict(counts),
        }

    try:
        iterator: Iterator[Any]
        if resume_record is not None:
            assert skip_report is not None
            files = [dict(item) for item in resume_record["files"]]
            counts = {key: int(value) for key, value in resume_record["counts"].items()}
            part = int(resume_record["parts_completed"])
            persisted = int(resume_record["releases_persisted"])
            last_release_id = resume_record["last_release_id"]
            iterator = iter(records)
            try:
                first = next(iterator, _END)  # performs the whole re-read-and-skip prefix
            except ResumeRefused:
                raise
            except Exception as error:
                if skip_report.skipped < persisted:
                    # Failure while re-reading the already-persisted prefix: the input is
                    # truncated/corrupt/different. Refuse; never touch the valid parts.
                    raise ResumeRefused(
                        f"could not re-read the {persisted} already-persisted releases "
                        f"(stopped after {skip_report.skipped}): {error!r}. The input is "
                        "truncated, corrupt or not the same dump; the staging directory "
                        "was left intact."
                    ) from error
                raise
            if skip_report.skipped != persisted:
                raise ResumeRefused(
                    f"input has only {skip_report.skipped} releases but the interrupted run "
                    f"had persisted {persisted}; it is not the same input"
                )
            if (
                skip_report.last_release_id != last_release_id
                or skip_report.digest.hexdigest() != resume_record["release_id_digest"]
            ):
                raise ResumeRefused(
                    f"the first {persisted} release ids of this input do not match the "
                    f"interrupted run (recorded last release_id {last_release_id}, input has "
                    f"{skip_report.last_release_id}); it is a different or modified dump"
                )
            digest = skip_report.digest
            if first is not _END:
                if persisted % chunk_releases != 0:
                    raise ResumeRefused(
                        "the interrupted run had already written its final (partial) part "
                        "but this input has more releases; it is not the same input"
                    )
                iterator = itertools.chain([first], iterator)
        else:
            iterator = iter(records)
            write_progress(boundary=boundary_now())

        with ThreadPoolExecutor(max_workers=1) as executor:

            def commit_pending() -> None:
                nonlocal pending, pending_boundary
                if pending is not None:
                    assert pending_boundary is not None
                    files.extend(pending.result())
                    write_progress(boundary=pending_boundary)
                    pending, pending_boundary = None, None

            def start_flush() -> None:
                nonlocal release_rows, track_rows, credit_rows, format_rows, part, pending
                nonlocal pending_boundary
                commit_pending()
                part += 1
                pending_boundary = boundary_now()
                pending = executor.submit(
                    _write_chunk,
                    staging_root,
                    part - 1,
                    release_rows,
                    track_rows,
                    credit_rows,
                    format_rows,
                )
                release_rows, track_rows, credit_rows, format_rows = [], [], [], []

            for record in iterator:
                release_rows.append(record.release)
                track_rows.extend(record.tracks)
                credit_rows.extend(record.credits)
                format_rows.extend(record.formats)
                last_release_id = int(str(record.release["release_id"]))
                release_id_digest_update(digest, last_release_id)
                persisted += 1
                counts["releases"] += 1
                counts["tracks"] += len(record.tracks)
                counts["credits"] += len(record.credits)
                counts["release_formats"] += len(record.formats)
                if len(release_rows) >= chunk_releases:
                    start_flush()
            if release_rows or track_rows or credit_rows or format_rows:
                start_flush()
            commit_pending()
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
        manifest_path = staging_root / "manifest.json"
        write_json_atomic(manifest_path, manifest)
        write_progress(
            boundary=boundary_now(),
            state=STATE_FINALIZED,
            manifest_sha256=_sha256(manifest_path),
        )
        _promote(staging_root, final_root)
        return manifest
    except ResumeRefused:
        # A refusal must leave the (possibly hours-old) staging directory intact.
        raise
    except Exception as error:
        # Keep-vs-delete rule: the staging dir is KEPT (for --resume) when at least one part
        # is committed AND the run is a resume (any failure after the verified prefix) or the
        # failure is environmental (OSError, e.g. ENOSPC; MemoryError). It is DELETED when
        # nothing is committed yet, or on a fresh run for a failure that is not environmental
        # (malformed input, no records) -- the original behaviour.
        if files and (resume_record is not None or isinstance(error, OSError | MemoryError)):
            logger.warning(
                "keeping staging directory %s with %d committed files for --resume (%r)",
                staging_root.name,
                len(files),
                error,
            )
        else:
            shutil.rmtree(staging_root, ignore_errors=True)
        raise


def parse_release_dump(
    input_path: Path,
    output_root: Path,
    *,
    snapshot_date: str,
    source_url: str,
    chunk_releases: int = 5_000,
    max_releases: int | None = None,
    overwrite: bool = False,
    resume: bool = False,
    input_manifest: Path | None = None,
) -> dict[str, object]:
    """Stream a release dump into Parquet; with ``resume``, continue an interrupted run.

    Resume is re-read-and-skip (see ``discogs/resume.py``): it validates the staging
    directory, then re-streams the dump from the start, discarding the already-persisted
    prefix, and continues at the next part index.
    """
    if chunk_releases <= 0:
        raise ValueError("chunk_releases must be positive")
    identity = describe_input(input_path, input_manifest=input_manifest)
    if not resume:
        records = iter_releases(
            input_path,
            snapshot_date=snapshot_date,
            source_url=source_url,
            max_releases=max_releases,
        )
        return write_release_dataset(
            records,
            output_root,
            snapshot_date=snapshot_date,
            source_url=source_url,
            chunk_releases=chunk_releases,
            overwrite=overwrite,
            max_releases=max_releases,
            input_identity=identity,
        )

    final_root = output_root / f"snapshot={snapshot_date}"
    cleanup_promoted_leftovers(final_root)
    if final_root.exists() and not overwrite:
        raise FileExistsError(f"dataset already exists: {final_root}")
    candidates = find_staging_dirs(output_root, snapshot_date)
    if not candidates:
        raise ResumeRefused(
            f"nothing to resume: no staging directory .snapshot={snapshot_date}.tmp-* "
            f"under {output_root}. Run without --resume to start a new parse."
        )
    if len(candidates) > 1:
        raise ResumeRefused(
            f"ambiguous resume: {len(candidates)} staging directories exist for snapshot "
            f"{snapshot_date} ({', '.join(p.name for p in candidates)}). Inspect them with "
            "scripts/check-ingest-recovery.sh and delete all but the one to resume."
        )
    staging_root = candidates[0]
    with writer_lock(staging_root):
        return _resume_locked(
            staging_root,
            final_root,
            input_path,
            identity,
            snapshot_date=snapshot_date,
            source_url=source_url,
            chunk_releases=chunk_releases,
            max_releases=max_releases,
        )


def _resume_locked(
    staging_root: Path,
    final_root: Path,
    input_path: Path,
    identity: dict[str, object],
    *,
    snapshot_date: str,
    source_url: str,
    chunk_releases: int,
    max_releases: int | None,
) -> dict[str, object]:
    record = load_progress(staging_root)
    params = _run_params(
        snapshot_date=snapshot_date,
        source_url=source_url,
        chunk_releases=chunk_releases,
        max_releases=max_releases,
        input_identity=identity,
    )
    check_parameters(record, {key: value for key, value in params.items() if key != "input"})
    check_input_identity(record, identity)
    # Keep the originally recorded identity (it may carry a sha256 this resume lacks).
    params["input"] = record["input"]
    release_rows = sum(
        int(item["rows"])
        for item in record["files"]
        if str(item["path"]).startswith("table=releases/")
    )
    if (
        record["counts"].get("releases") != record["releases_persisted"]
        or release_rows != record["releases_persisted"]
    ):
        raise ResumeRefused("progress record is internally inconsistent (release counts)")
    validate_and_clean_staging(staging_root, record)

    if record["state"] == STATE_FINALIZED:
        manifest_path = staging_root / "manifest.json"
        if not manifest_path.is_file() or sha256_file(manifest_path) != record.get(
            "manifest_sha256"
        ):
            raise ResumeRefused(
                "finalized staging directory has a missing or altered manifest.json"
            )
        _promote(staging_root, final_root)
        finalized: dict[str, object] = json.loads((final_root / "manifest.json").read_text())
        return finalized

    logger.warning(
        "resume: %d releases in %d parts already persisted; re-reading the dump from the "
        "start and discarding them (the skip still pays decompress/parse cost)",
        record["releases_persisted"],
        record["parts_completed"],
    )
    skip_report = SkipReport()
    records = iter_releases(
        input_path,
        snapshot_date=snapshot_date,
        source_url=source_url,
        max_releases=max_releases,
        skip_releases=int(record["releases_persisted"]),
        skip_report=skip_report,
    )
    return _write_release_dataset(
        records,
        staging_root,
        final_root,
        params=params,
        resume_record=record,
        skip_report=skip_report,
    )


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
