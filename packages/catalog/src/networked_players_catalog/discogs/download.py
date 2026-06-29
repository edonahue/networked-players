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


class _RestartDownload(DownloadError):
    """Raised when retrying must discard the current partial file."""


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
    incompatible bytes. Integrity failures discard the partial file before another attempt.
    """

    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    initial_partial_size = partial.stat().st_size if partial.exists() else 0
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        start = partial.stat().st_size if partial.exists() else 0
        try:
            with _request(url, start, timeout) as response:
                status = getattr(response, "status", response.getcode())
                resumed = bool(start and status == 206)
                response_size = expected_size
                if resumed:
                    content_range = response.headers.get("Content-Range", "")
                    match = CONTENT_RANGE_RE.fullmatch(content_range.strip())
                    if not match or int(match.group(1)) != start:
                        raise _RestartDownload(f"invalid resume response: {content_range!r}")
                    range_total = match.group(3)
                    if range_total != "*":
                        reported_size = int(range_total)
                        if expected_size is not None and reported_size != expected_size:
                            raise _RestartDownload(
                                f"server size mismatch for {url}: "
                                f"expected {expected_size}, reported {reported_size}"
                            )
                        response_size = expected_size or reported_size
                    mode = "ab"
                else:
                    mode = "wb"
                    start = 0
                    content_length = response.headers.get("Content-Length")
                    if response_size is None and content_length and content_length.isdigit():
                        response_size = int(content_length)

                with partial.open(mode) as output:
                    while True:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())

                actual_size = partial.stat().st_size
                if response_size is not None and actual_size < response_size:
                    raise DownloadError(
                        f"incomplete download for {url}: "
                        f"expected {response_size}, got {actual_size}"
                    )
                if response_size is not None and actual_size > response_size:
                    raise _RestartDownload(
                        f"size mismatch for {url}: expected {response_size}, got {actual_size}"
                    )

                actual_sha256 = sha256_file(partial)
                if expected_sha256 is not None and actual_sha256.lower() != expected_sha256.lower():
                    raise _RestartDownload(f"SHA-256 mismatch for {url}")

                partial.replace(destination)
                return DownloadResult(
                    path=destination,
                    size_bytes=actual_size,
                    sha256=actual_sha256,
                    resumed=bool(initial_partial_size and resumed),
                    etag=response.headers.get("ETag", "").strip('"') or None,
                )
        except urllib.error.HTTPError as error:
            last_error = error
            if error.code == 416:
                partial.unlink(missing_ok=True)
        except _RestartDownload as error:
            last_error = error
            partial.unlink(missing_ok=True)
        except (OSError, urllib.error.URLError, DownloadError) as error:
            last_error = error

        if attempt < retries:
            time.sleep(2 ** (attempt - 1))

    raise DownloadError(f"failed to download {url} after {retries} attempts: {last_error}")
