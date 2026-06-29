from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

import pytest

from networked_players_catalog.discogs.download import download_file

PAYLOAD = b"networked-players-discogs-fixture\n" * 200_000


class RangeHandler(BaseHTTPRequestHandler):
    range_headers: ClassVar[list[str | None]] = []
    truncate_first_full_response: ClassVar[bool] = False

    def do_GET(self) -> None:
        range_header = self.headers.get("Range")
        self.range_headers.append(range_header)
        start = 0
        if range_header:
            start = int(range_header.removeprefix("bytes=").removesuffix("-"))
            if start >= len(PAYLOAD):
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{len(PAYLOAD)}")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(PAYLOAD) - 1}/{len(PAYLOAD)}")
        else:
            self.send_response(200)
        body = PAYLOAD[start:]
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", '"fixture-etag"')
        self.end_headers()
        if range_header is None and self.truncate_first_full_response:
            type(self).truncate_first_full_response = False
            self.wfile.write(body[: 5 * 1024 * 1024])
            self.close_connection = True
            return
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


@contextmanager
def serving_range_fixture(*, truncate_first_full_response: bool = False) -> Iterator[str]:
    RangeHandler.range_headers = []
    RangeHandler.truncate_first_full_response = truncate_first_full_response
    server = ThreadingHTTPServer(("127.0.0.1", 0), RangeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/fixture"
    finally:
        server.shutdown()
        thread.join()


def test_download_resumes_and_verifies(tmp_path: Path) -> None:
    with serving_range_fixture() as url:
        destination = tmp_path / "fixture.xml.gz"
        partial = destination.with_name(destination.name + ".part")
        partial.write_bytes(PAYLOAD[:123_456])
        expected_hash = hashlib.sha256(PAYLOAD).hexdigest()
        result = download_file(
            url,
            destination,
            expected_size=len(PAYLOAD),
            expected_sha256=expected_hash,
        )

    assert result.resumed is True
    assert result.sha256 == expected_hash
    assert result.etag == "fixture-etag"
    assert destination.read_bytes() == PAYLOAD
    assert not partial.exists()
    assert RangeHandler.range_headers == ["bytes=123456-"]


def test_interrupted_transfer_retries_from_new_partial(tmp_path: Path) -> None:
    with serving_range_fixture(truncate_first_full_response=True) as url:
        destination = tmp_path / "fixture.xml.gz"
        expected_hash = hashlib.sha256(PAYLOAD).hexdigest()
        result = download_file(
            url,
            destination,
            expected_size=len(PAYLOAD),
            expected_sha256=expected_hash,
            chunk_size=1024 * 1024,
        )

    assert result.resumed is True
    assert result.sha256 == expected_hash
    assert destination.read_bytes() == PAYLOAD
    assert RangeHandler.range_headers[0] is None
    assert RangeHandler.range_headers[1] == f"bytes={5 * 1024 * 1024}-"


def test_checksum_failure_restarts_without_corrupt_partial(tmp_path: Path) -> None:
    with serving_range_fixture() as url:
        destination = tmp_path / "fixture.xml.gz"
        partial = destination.with_name(destination.name + ".part")
        partial.write_bytes(b"x" * 123_456)
        expected_hash = hashlib.sha256(PAYLOAD).hexdigest()
        result = download_file(
            url,
            destination,
            expected_size=len(PAYLOAD),
            expected_sha256=expected_hash,
        )

    assert result.resumed is False
    assert result.sha256 == expected_hash
    assert destination.read_bytes() == PAYLOAD
    assert not partial.exists()
    assert RangeHandler.range_headers == ["bytes=123456-", None]


def test_unsatisfiable_range_restarts_without_stale_partial(tmp_path: Path) -> None:
    with serving_range_fixture() as url:
        destination = tmp_path / "fixture.xml.gz"
        partial = destination.with_name(destination.name + ".part")
        partial.write_bytes(b"x" * len(PAYLOAD))
        expected_hash = hashlib.sha256(PAYLOAD).hexdigest()
        result = download_file(
            url,
            destination,
            expected_size=len(PAYLOAD),
            expected_sha256=expected_hash,
        )

    assert result.resumed is False
    assert result.sha256 == expected_hash
    assert destination.read_bytes() == PAYLOAD
    assert not partial.exists()
    assert RangeHandler.range_headers == [f"bytes={len(PAYLOAD)}-", None]


@pytest.mark.parametrize(("retries", "chunk_size"), [(0, 1024), (1, 0)])
def test_download_rejects_non_positive_limits(
    tmp_path: Path, retries: int, chunk_size: int
) -> None:
    with pytest.raises(ValueError):
        download_file(
            "https://example.test/fixture",
            tmp_path / "fixture.xml.gz",
            retries=retries,
            chunk_size=chunk_size,
        )
