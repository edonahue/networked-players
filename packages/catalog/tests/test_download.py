from __future__ import annotations

import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from networked_players_catalog.discogs.download import download_file

PAYLOAD = b"networked-players-discogs-fixture\n" * 200_000


class RangeHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        start = 0
        range_header = self.headers.get("Range")
        if range_header:
            start = int(range_header.removeprefix("bytes=").removesuffix("-"))
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(PAYLOAD) - 1}/{len(PAYLOAD)}")
        else:
            self.send_response(200)
        body = PAYLOAD[start:]
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", '"fixture-etag"')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def test_download_resumes_and_verifies(tmp_path: Path) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), RangeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        destination = tmp_path / "fixture.xml.gz"
        partial = destination.with_name(destination.name + ".part")
        partial.write_bytes(PAYLOAD[:123_456])
        expected_hash = hashlib.sha256(PAYLOAD).hexdigest()
        result = download_file(
            f"http://127.0.0.1:{server.server_port}/fixture",
            destination,
            expected_size=len(PAYLOAD),
            expected_sha256=expected_hash,
        )
        assert result.resumed is True
        assert result.sha256 == expected_hash
        assert result.etag == "fixture-etag"
        assert destination.read_bytes() == PAYLOAD
        assert not partial.exists()
    finally:
        server.shutdown()
        thread.join()
