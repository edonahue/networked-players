"""Fetch and verify a served dataset into a local, disposable, read-only cache.

This module is self-contained and stdlib-only (json, hashlib, urllib, shutil,
os, argparse, pathlib) so it can be copied to a worker and run under the
worker's bare system ``python3`` -- it must NOT import anything else from
this package, and must not rely on any Python version newer than 3.9 at
runtime (no ``dataclass(slots=True)``, no ``match`` statements). It is
type-checked under this repo's newer mypy config, which is fine; only the
*runtime* behavior needs to stay 3.9-compatible.

A "validated cache" means a dataset directory containing both a
``manifest.json`` (as served) and a ``.verified.json`` marker written by a
successful ``fetch_dataset`` or ``verify_dataset`` call. Nothing else in this
project should treat a local dataset directory as trustworthy without that
marker -- see ``dataset_locator.resolve_dataset``.

Master/coordination host stays the single authoritative source for
``local/processed/``; anything fetched by this tool is a disposable,
rebuildable replica (ADR 0025).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any
from urllib.request import urlopen

_CHUNK_SIZE = 64 * 1024


class FetchError(RuntimeError):
    """Raised when a dataset can't be fetched or verified as requested."""


def _fetch_manifest(base_url: str, *, timeout_seconds: float) -> dict[str, Any]:
    manifest_url = f"{base_url.rstrip('/')}/manifest.json"
    try:
        with urlopen(manifest_url, timeout=timeout_seconds) as response:
            manifest: dict[str, Any] = json.loads(response.read().decode("utf-8"))
    except OSError as exc:
        raise FetchError(f"could not fetch {manifest_url}: {exc}") from exc

    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise FetchError(f"{manifest_url} has no usable 'files' list")
    for entry in files:
        if not isinstance(entry, dict):
            raise FetchError(f"{manifest_url} has a malformed files entry: {entry!r}")
        path = str(entry.get("path", ""))
        if not path or path.startswith("/") or ".." in Path(path).parts:
            raise FetchError(f"{manifest_url} lists an unsafe file path: {path!r}")
    return manifest


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_local_manifest(dataset_root: Path) -> dict[str, Any]:
    manifest_path = dataset_root / "manifest.json"
    if not manifest_path.exists():
        raise FetchError(f"no manifest.json under {dataset_root}")
    manifest: dict[str, Any] = json.loads(manifest_path.read_text())
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise FetchError(f"{manifest_path} has no usable 'files' list")
    return manifest


def verify_dataset(dataset_root: Path) -> dict[str, Any]:
    """Recompute size+sha256 of every manifest file against what's on disk.

    Writes a fresh ``.verified.json`` marker on success. Raises FetchError
    naming every missing or mismatched file on failure -- the marker is left
    untouched (or absent) so a failed verify never looks validated.
    """
    dataset_root = Path(dataset_root)
    manifest = _check_local_manifest(dataset_root)

    failures: list[str] = []
    for entry in manifest["files"]:
        path = dataset_root / str(entry["path"])
        if not path.exists():
            failures.append(f"{entry['path']}: missing")
            continue
        actual_size = path.stat().st_size
        expected_size = int(entry["size_bytes"])
        if actual_size != expected_size:
            failures.append(f"{entry['path']}: size {actual_size} != expected {expected_size}")
            continue
        actual_sha256 = _sha256_file(path)
        expected_sha256 = str(entry["sha256"])
        if actual_sha256 != expected_sha256:
            failures.append(f"{entry['path']}: sha256 mismatch")

    if failures:
        raise FetchError("verification failed: " + "; ".join(failures))

    _write_verified_marker(dataset_root, manifest)
    return {
        "status": "verified",
        "dest": str(dataset_root),
        "files_verified": len(manifest["files"]),
    }


def _write_verified_marker(dataset_root: Path, manifest: dict[str, Any]) -> None:
    marker = {
        "verified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "manifest_sha256": hashlib.sha256(
            json.dumps(manifest, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "tool_version": 1,
    }
    (dataset_root / ".verified.json").write_text(json.dumps(marker, indent=2) + "\n")


def fetch_dataset(
    base_url: str,
    dest_root: Path,
    *,
    max_total_bytes: int | None = None,
    headroom_bytes: int = 1_000_000_000,
    timeout_seconds: float = 60.0,
    overwrite: bool = False,
) -> dict[str, Any]:
    dest_root = Path(dest_root)

    if dest_root.exists():
        try:
            verify_dataset(dest_root)
            return {"status": "already-valid", "dest": str(dest_root)}
        except FetchError:
            if not overwrite:
                raise FetchError(
                    f"{dest_root} exists and failed verification; pass overwrite=True to replace it"
                ) from None

    manifest = _fetch_manifest(base_url, timeout_seconds=timeout_seconds)
    files = manifest["files"]
    base = base_url.rstrip("/")

    total_bytes = sum(int(entry["size_bytes"]) for entry in files)
    if max_total_bytes is not None and total_bytes > max_total_bytes:
        raise FetchError(
            f"dataset is {total_bytes} bytes, exceeding the {max_total_bytes}-byte cap "
            f"for this host class -- refusing to fetch"
        )

    disk_usage = shutil.disk_usage(dest_root.parent if dest_root.parent.exists() else Path.cwd())
    if disk_usage.free < total_bytes + headroom_bytes:
        raise FetchError(
            f"insufficient free space: {disk_usage.free} bytes free, need "
            f"{total_bytes} + {headroom_bytes} headroom"
        )

    # Deterministic, not random: a staging directory that survives an interrupted
    # or failed run, so a retry resumes from whatever already-verified files are
    # in it instead of redownloading the whole dataset from scratch. A per-file
    # failure below is NOT caught here -- the good files already staged stay put
    # for the next call; only the one bad temp file is removed.
    staging_root = dest_root.parent / f".{dest_root.name}.partial"
    staging_root.mkdir(parents=True, exist_ok=True)

    files_downloaded = 0
    files_reused = 0
    bytes_downloaded = 0
    for entry in files:
        rel_path = str(entry["path"])
        expected_size = int(entry["size_bytes"])
        expected_sha256 = str(entry["sha256"])
        local_path = staging_root / rel_path
        local_path.parent.mkdir(parents=True, exist_ok=True)

        if (
            local_path.exists()
            and local_path.stat().st_size == expected_size
            and _sha256_file(local_path) == expected_sha256
        ):
            files_reused += 1
            continue

        file_url = f"{base}/{rel_path}"
        digest = hashlib.sha256()
        size = 0
        tmp_path = local_path.with_suffix(local_path.suffix + ".part")
        try:
            with (
                urlopen(file_url, timeout=timeout_seconds) as response,
                tmp_path.open("wb") as handle,
            ):
                while True:
                    chunk = response.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    handle.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
        except OSError as exc:
            tmp_path.unlink(missing_ok=True)
            raise FetchError(f"could not fetch {file_url}: {exc}") from exc

        if size != expected_size or digest.hexdigest() != expected_sha256:
            tmp_path.unlink(missing_ok=True)
            raise FetchError(
                f"{rel_path}: fetched {size} bytes / sha256 {digest.hexdigest()}, "
                f"expected {expected_size} bytes / sha256 {expected_sha256}"
            )
        tmp_path.replace(local_path)
        files_downloaded += 1
        bytes_downloaded += size

    (staging_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    _write_verified_marker(staging_root, manifest)

    if dest_root.exists():
        shutil.rmtree(dest_root)
    staging_root.replace(dest_root)
    return {
        "status": "fetched",
        "dest": str(dest_root),
        "files_total": len(files),
        "files_downloaded": files_downloaded,
        "files_reused": files_reused,
        "bytes_downloaded": bytes_downloaded,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch and verify a read-only, disposable dataset cache from a "
        "catalog-data HTTP server (ADR 0024/0025)."
    )
    parser.add_argument(
        "--base-url", help="dataset root URL, e.g. http://host:8791/discogs/snapshot=20260601"
    )
    parser.add_argument("--dest", required=True, type=Path)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--max-total-bytes", type=int, default=None)
    parser.add_argument("--headroom-bytes", type=int, default=1_000_000_000)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.verify_only:
        result = verify_dataset(args.dest)
    else:
        if not args.base_url:
            print("--base-url is required unless --verify-only is set", file=sys.stderr)
            return 2
        result = fetch_dataset(
            args.base_url,
            args.dest,
            max_total_bytes=args.max_total_bytes,
            headroom_bytes=args.headroom_bytes,
            timeout_seconds=args.timeout,
            overwrite=args.overwrite,
        )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
