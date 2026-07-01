from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

import pytest

from networked_players_catalog.discogs.api_client import (
    ApiClient,
    MissingCredentialError,
    ReleaseCache,
    fetch_releases,
    load_token,
)
from networked_players_catalog.discogs.download import USER_AGENT

RELEASE_PAYLOAD = {"id": 1, "title": "Fixture Release"}


class ReleaseHandler(BaseHTTPRequestHandler):
    requests: ClassVar[list[dict[str, str | None]]] = []
    fail_once_with_429: ClassVar[bool] = False

    def do_GET(self) -> None:
        type(self).requests.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "user_agent": self.headers.get("User-Agent"),
            }
        )
        if self.fail_once_with_429:
            type(self).fail_once_with_429 = False
            self.send_response(429)
            self.send_header("Retry-After", "0")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        body = json.dumps(RELEASE_PAYLOAD).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Discogs-Ratelimit-Remaining", "42")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


@contextmanager
def serving_release_fixture(*, fail_once_with_429: bool = False) -> Iterator[str]:
    ReleaseHandler.requests = []
    ReleaseHandler.fail_once_with_429 = fail_once_with_429
    server = ThreadingHTTPServer(("127.0.0.1", 0), ReleaseHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()


def test_fetch_release_sends_auth_and_user_agent() -> None:
    with serving_release_fixture() as base_url:
        client = ApiClient(token="test-token", base_url=base_url, request_delay_seconds=0)
        payload = client.fetch_release(1)

    assert payload == RELEASE_PAYLOAD
    assert len(ReleaseHandler.requests) == 1
    assert ReleaseHandler.requests[0]["authorization"] == "Discogs token=test-token"
    assert ReleaseHandler.requests[0]["user_agent"] == USER_AGENT
    assert ReleaseHandler.requests[0]["path"] == "/releases/1"


def test_fetch_release_retries_after_429() -> None:
    with serving_release_fixture(fail_once_with_429=True) as base_url:
        client = ApiClient(token="test-token", base_url=base_url, request_delay_seconds=0)
        payload = client.fetch_release(1)

    assert payload == RELEASE_PAYLOAD
    assert len(ReleaseHandler.requests) == 2


def test_release_cache_round_trip_avoids_second_http_call(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    with serving_release_fixture() as base_url:
        client = ApiClient(token="test-token", base_url=base_url, request_delay_seconds=0)
        cache = ReleaseCache(cache_dir)
        results = fetch_releases([1], client=client, cache=cache)
        assert results == {1: RELEASE_PAYLOAD}
        assert len(ReleaseHandler.requests) == 1

        # Second fetch should be served entirely from cache -- no new HTTP call.
        results_again = fetch_releases([1], client=client, cache=cache)
        assert results_again == {1: RELEASE_PAYLOAD}
        assert len(ReleaseHandler.requests) == 1


def test_release_cache_get_put_round_trip(tmp_path: Path) -> None:
    cache = ReleaseCache(tmp_path / "cache")
    assert cache.get(99) is None
    cache.put(99, RELEASE_PAYLOAD)
    assert cache.get(99) == RELEASE_PAYLOAD


def test_load_token_raises_when_missing() -> None:
    with pytest.raises(MissingCredentialError):
        load_token(env={})


def test_load_token_reads_from_given_env() -> None:
    assert load_token(env={"DISCOGS_TOKEN": " abc123 "}) == "abc123"
