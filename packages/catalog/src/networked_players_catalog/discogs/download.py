"""Resumable, checksummed download support for large catalog objects."""

from __future__ import annotations

import hashlib
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

USER_AGENT = "networked-players/0.1 (+https://github.com/edonahue/networked-players)"
CONTENT_RANGE_RE = re.compile(r"bytes\s+(\d+)-(\d+)/(\d+|\*)")


class DownloadError(RuntimeError):
    """Raised when a dump object cannot be transferred safely."""


@dataclass(frozen=True, slots=True)
class DownloadResult:
    path: Path
    size_bytes: int
    sha256: str
    resumed: bool
    etag: str | None


def sha256_file(path: Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _request(url: str, start: int, timeout: float) -> Any:
    headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
    if start:
        headers["Range"] = f"bytes={start}-"
    request = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(request, timeout=timeout)


def download_file(
    url: str,
    destination: Path,
    *,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
    timeout: float = 120,
    retries: int = 3,
    chunk_size: int = 4 * 1024 * 1024,
) -> DownloadResult:
    """Download to ``.part`` and atomically publish a verified file.

    A partial file is resumed only when the server answers a Range request with HTTP 206 and a
    matching starting offset. If Range is ignored, the transfer restarts rather than appending
    incompatible bytes.
    """

    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    original_partial_size = partial.stat().st_size if partial.exists() else 0
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        start = partial.stat().st_size if partial.exists() else 0
        try:
            with _request(url, start, timeout) as response:
                status = getattr(response, "status", response.getcode())
                resumed = bool(start and status == 206)
                if resumed:
                    content_range = response.headers.get("Content-Range", "")
                    match = CONTENT_RANGE_RE.fullmatch(content_range.strip())
                    if not match or int(match.group(1)) != start:
                        raise DownloadError(f"invalid resume response: {content_range!r}")
                    mode = "ab"
                else:
                    mode = "wb"
                    start = 0

                with partial.open(mode) as output:
                    while True:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())

                actual_size = partial.stat().st_size
                if expected_size is not None and actual_size != expected_size:
                    raise DownloadError(
                        f"size mismatch for {url}: expected {expected_size}, got {actual_size}"
                    )
                actual_sha256 = sha256_file(partial)
                if expected_sha256 is not None and actual_sha256.lower() != expected_sha256.lower():
                    raise DownloadError(f"SHA-256 mismatch for {url}")

                partial.replace(destination)
                return DownloadResult(
                    path=destination,
                    size_bytes=actual_size,
                    sha256=actual_sha256,
                    resumed=bool(original_partial_size and resumed),
                    etag=response.headers.get("ETag", "").strip('"') or None,
                )
        except (OSError, urllib.error.URLError, DownloadError) as error:
            last_error = error
            if attempt == retries:
                break
            time.sleep(2 ** (attempt - 1))

    raise DownloadError(f"failed to download {url} after {retries} attempts: {last_error}")
