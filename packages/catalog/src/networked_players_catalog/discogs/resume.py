"""Durable progress record and resume validation for ``parse-releases``.

The release dump is one gzip XML stream, so it cannot be seeked. Resume is therefore
*re-read and skip*: the stream is re-read from the start, the first
``releases_persisted`` releases are parsed (ids only) and discarded, and writing continues
at the next part index. This saves the transform/Parquet-write/hash cost of the completed
portion; it does not save the decompress/XML-parse cost of the skipped portion.

Stream position is the release *ordinal* (0-based count of ``<release>`` elements in
document order). It is verified with the last persisted ``release_id`` and a running
SHA-256 over every persisted release id, so a different or re-downloaded input is refused
instead of silently producing a corrupt dataset.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROGRESS_FILENAME = "progress.json"
LOCK_FILENAME = ".writer.lock"
MANIFEST_FILENAME = "manifest.json"
PROGRESS_VERSION = 1
STATE_IN_PROGRESS = "in_progress"
STATE_FINALIZED = "finalized"

_REQUIRED_KEYS = (
    "progress_version",
    "state",
    "snapshot_date",
    "source_url",
    "schema_version",
    "parser_version",
    "chunk_releases",
    "max_releases",
    "input",
    "parts_completed",
    "releases_persisted",
    "last_release_id",
    "release_id_digest",
    "counts",
    "files",
)


class ResumeRefused(Exception):
    """A resume (or a non-resume start) was refused; the staging directory is left intact."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fsync_directory(directory: Path) -> None:
    """Best-effort directory fsync (not available on every platform/filesystem)."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Write-temp + fsync + rename + directory fsync."""
    tmp = path.with_name(f".{path.name}.tmp")
    with tmp.open("w") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    _replace_json(tmp, path)
    fsync_directory(path.parent)


def _replace_json(tmp: Path, final: Path) -> None:
    """Rename step of an atomic JSON write (a seam for crash-injection tests)."""
    os.replace(tmp, final)


# Tables that mark a staging directory as belonging to a different dataset type that uses
# the same ``.snapshot=DATE.tmp-*`` naming (masters, artist relations, one-hop).
_OTHER_DATASET_TABLES = (
    "table=masters",
    "table=master_artists",
    "table=artist_relations",
    "table=frontier_artists",
    "table=seed_releases",
)


def is_release_staging_dir(path: Path) -> bool:
    """True if ``path`` is a release-parse staging dir (not masters/artists/one-hop).

    Our own markers (progress record, writer lock) win; otherwise a dir holding another
    dataset's tables is not ours; otherwise a ``table=releases`` dir (e.g. one left by a
    pre-resume build) is ours.
    """
    if (path / PROGRESS_FILENAME).exists() or (path / LOCK_FILENAME).exists():
        return True
    if any((path / name).exists() for name in _OTHER_DATASET_TABLES):
        return False
    return (path / "table=releases").exists()


def find_staging_dirs(output_root: Path, snapshot_date: str) -> list[Path]:
    return sorted(
        p
        for p in output_root.glob(f".snapshot={snapshot_date}.tmp-*")
        if p.is_dir() and is_release_staging_dir(p)
    )


@contextmanager
def writer_lock(staging_root: Path) -> Iterator[None]:
    """Exclusive non-blocking flock on the staging dir for the writer's whole lifetime.

    A second process (resume or fresh) is refused. A stale lock file with no holder does
    not block: the kernel drops the lock when the holder exits or is killed.
    """
    lock_path = staging_root / LOCK_FILENAME
    handle = lock_path.open("a")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ResumeRefused(
                f"{staging_root.name} is locked by another running parse-releases "
                f"(lock file {LOCK_FILENAME}); nothing was touched. Wait for it to finish, "
                "or stop it first."
            ) from error
        yield
    finally:
        handle.close()


def lock_is_held(staging_root: Path) -> bool:
    """Read-only check: is another process currently holding the writer lock?"""
    lock_path = staging_root / LOCK_FILENAME
    if not lock_path.exists():
        return False
    try:
        handle = lock_path.open("rb")
    except OSError:
        return False
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError:
            return True
        return False
    finally:
        handle.close()


def describe_input(input_path: Path, *, input_manifest: Path | None = None) -> dict[str, object]:
    """Identity of the dump without hashing it.

    ``sha256`` comes from the download manifest (recorded by ``download`` after a
    verified transfer) when ``input_manifest`` is given and its object has one;
    otherwise it is ``None`` and identity rests on filename + size + the stream-prefix
    digest verified on resume.
    """
    size = input_path.stat().st_size
    identity: dict[str, object] = {
        "filename": input_path.name,
        "size_bytes": size,
        "sha256": None,
        "sha256_source": None,
    }
    if input_manifest is not None:
        from .manifest import DumpKind, SnapshotManifest

        manifest = SnapshotManifest.read(input_manifest)
        item = manifest.object_for(DumpKind.RELEASES)
        if item.filename != input_path.name:
            raise ResumeRefused(
                f"input manifest names {item.filename!r} but --input is {input_path.name!r}"
            )
        if item.size_bytes is not None and item.size_bytes != size:
            raise ResumeRefused(
                f"input manifest records {item.size_bytes} bytes but {input_path.name!r} "
                f"is {size} bytes"
            )
        if item.sha256:
            identity["sha256"] = item.sha256
            identity["sha256_source"] = "download_manifest"
    return identity


def load_progress(staging_root: Path) -> dict[str, Any]:
    path = staging_root / PROGRESS_FILENAME
    if not path.is_file():
        if not any(staging_root.glob("table=*/*")):
            raise ResumeRefused(
                f"{staging_root.name} holds no completed work (the run stopped before its "
                f"first {PROGRESS_FILENAME} was written); delete it and re-run without --resume."
            )
        raise ResumeRefused(
            f"{staging_root.name} has no {PROGRESS_FILENAME}; it was not written by a "
            "resumable run (or the record was lost). Inspect it with "
            "scripts/check-ingest-recovery.sh, then delete it and re-run without --resume."
        )
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise ResumeRefused(
            f"{path} is unreadable or corrupt ({error}). Delete the staging directory and "
            "re-run without --resume."
        ) from error
    if not isinstance(record, dict):
        raise ResumeRefused(f"{path} is corrupt (not a JSON object)")
    missing = [key for key in _REQUIRED_KEYS if key not in record]
    if missing:
        raise ResumeRefused(f"{path} is corrupt (missing keys: {', '.join(missing)})")
    if record["progress_version"] != PROGRESS_VERSION:
        raise ResumeRefused(
            f"{path} has progress_version {record['progress_version']!r}; "
            f"this build understands {PROGRESS_VERSION}"
        )
    if record["state"] not in (STATE_IN_PROGRESS, STATE_FINALIZED):
        raise ResumeRefused(f"{path} has unknown state {record['state']!r}")
    return dict(record)


def check_parameters(record: dict[str, Any], expected: dict[str, object]) -> None:
    mismatches = [
        f"{key}: recorded {record[key]!r}, requested {value!r}"
        for key, value in expected.items()
        if record.get(key) != value
    ]
    if mismatches:
        raise ResumeRefused(
            "parameters differ from the interrupted run; resume requires identical "
            "parameters (" + "; ".join(mismatches) + ")"
        )


def check_input_identity(record: dict[str, Any], identity: dict[str, object]) -> None:
    recorded = record["input"]
    problems: list[str] = []
    for key in ("filename", "size_bytes"):
        if recorded.get(key) != identity.get(key):
            problems.append(f"{key}: recorded {recorded.get(key)!r}, now {identity.get(key)!r}")
    rec_sha, now_sha = recorded.get("sha256"), identity.get("sha256")
    if rec_sha and not now_sha:
        problems.append(
            f"sha256: the original run recorded {rec_sha} from the download manifest but "
            "this resume supplies none (pass --input-manifest with the same manifest)"
        )
    elif rec_sha and now_sha and rec_sha != now_sha:
        problems.append(f"sha256: recorded {rec_sha}, now {now_sha}")
    if problems:
        raise ResumeRefused("input differs from the interrupted run (" + "; ".join(problems) + ")")


def validate_and_clean_staging(staging_root: Path, record: dict[str, Any]) -> None:
    """Verify every recorded part (size + sha256); delete anything unrecorded.

    A missing or altered *recorded* part is a refusal (it was durable and is now wrong, so
    something other than an interruption happened). Unrecorded files -- temp files,
    complete-but-uncommitted parts, a stale manifest -- are removed with a logged line.
    """
    recorded: dict[str, dict[str, Any]] = {str(item["path"]): item for item in record["files"]}
    for relative, item in sorted(recorded.items()):
        path = staging_root / relative
        if not path.is_file():
            raise ResumeRefused(f"recorded part is missing: {relative}")
        size = path.stat().st_size
        if size != item["size_bytes"]:
            raise ResumeRefused(
                f"recorded part {relative} has size {size}, recorded {item['size_bytes']}"
            )
        if sha256_file(path) != item["sha256"]:
            raise ResumeRefused(f"recorded part {relative} does not match its recorded sha256")

    for path in unrecorded_files(staging_root, record):
        logger.warning("resume: deleting unrecorded file %s", path.relative_to(staging_root))
        path.unlink()


def unrecorded_files(staging_root: Path, record: dict[str, Any]) -> list[Path]:
    """Files in the staging dir that resume would delete (the single source of the rule).

    Kept: recorded parts, the progress record, the writer lock, and -- only for a
    finalized record -- ``manifest.json``. Everything else (temp files, complete-but-
    uncommitted parts, a stale manifest of an unfinalized run) is deleted.
    """
    keep = {str(item["path"]) for item in record["files"]} | {PROGRESS_FILENAME, LOCK_FILENAME}
    if record["state"] == STATE_FINALIZED:
        keep.add(MANIFEST_FILENAME)
    return [
        path
        for path in sorted(staging_root.rglob("*"))
        if path.is_file() and path.relative_to(staging_root).as_posix() not in keep
    ]


def cleanup_promoted_leftovers(final_root: Path) -> list[str]:
    """Remove a leftover ``progress.json`` / lock file from a promoted snapshot.

    A crash between the staging->final rename and the unlink leaves them behind. They are
    removed only when the snapshot's manifest verifies against the finalized record
    (manifest sha256 matches and every listed part exists with its recorded size).
    """
    leftovers = [
        name for name in (PROGRESS_FILENAME, LOCK_FILENAME) if (final_root / name).exists()
    ]
    if not leftovers:
        return []
    manifest_path = final_root / MANIFEST_FILENAME
    progress_path = final_root / PROGRESS_FILENAME
    if not manifest_path.is_file():
        return []
    if progress_path.exists():
        try:
            record = json.loads(progress_path.read_text())
            manifest = json.loads(manifest_path.read_text())
            ok = (
                record.get("state") == STATE_FINALIZED
                and record.get("manifest_sha256") == sha256_file(manifest_path)
                and all(
                    (final_root / item["path"]).is_file()
                    and (final_root / item["path"]).stat().st_size == item["size_bytes"]
                    for item in manifest["files"]
                )
            )
        except (OSError, ValueError, KeyError, TypeError):
            ok = False
        if not ok:
            return []
    removed = []
    for name in leftovers:
        (final_root / name).unlink()
        logger.warning("removed leftover %s from promoted snapshot %s", name, final_root.name)
        removed.append(name)
    return removed
