"""Stdlib-only client for the Discogs REST API v2 (release lookups).

Centralized, coordination-host-only use per ADR 0005 and docs/DISCOGS_INGESTION.md:
credentials and the raw response cache never leave this host. See ADR 0012 for why
this module exists ahead of the formal dump-based pipeline (Milestones 3/5/6/7/8).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .download import USER_AGENT  # reuse the existing convention, don't redefine it

API_BASE_URL = "https://api.discogs.com"
DEFAULT_REQUEST_DELAY_SECONDS = 1.1  # ~54 req/min, under the documented ~60/min token ceiling
RATE_LIMIT_REMAINING_HEADER = "X-Discogs-Ratelimit-Remaining"


class DiscogsApiError(RuntimeError):
    """Raised when a release cannot be safely fetched from the Discogs API."""


class MissingCredentialError(DiscogsApiError):
    """Raised when DISCOGS_TOKEN is absent. Never fall back to an insecure default."""


def load_token(env: dict[str, str] | None = None) -> str:
    source = env if env is not None else os.environ
    token = (source.get("DISCOGS_TOKEN") or "").strip()
    if not token:
        raise MissingCredentialError(
            "DISCOGS_TOKEN is not set. Export a Discogs personal access token before "
            "running build-demo-challenge; see docs/DISCOGS_INGESTION.md."
        )
    return token


@dataclass(slots=True)
class ApiClient:
    token: str
    base_url: str = API_BASE_URL
    request_delay_seconds: float = DEFAULT_REQUEST_DELAY_SECONDS
    timeout: float = 30.0
    retries: int = 3
    _last_request_at: float | None = field(default=None, init=False)

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": USER_AGENT,
            "Authorization": f"Discogs token={self.token}",
            "Accept": "application/vnd.discogs.v2.discogs+json",
        }

    def _throttle(self) -> None:
        if self._last_request_at is None:
            return
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.request_delay_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def fetch_release(self, release_id: int) -> dict[str, Any]:
        url = f"{self.base_url}/releases/{release_id}"
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self._throttle()
            request = urllib.request.Request(url, headers=self._headers())
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    self._last_request_at = time.monotonic()
                    payload: dict[str, Any] = json.loads(response.read().decode("utf-8"))
                    remaining = response.headers.get(RATE_LIMIT_REMAINING_HEADER)
                    if remaining is not None and remaining.isdigit() and int(remaining) <= 1:
                        time.sleep(self.request_delay_seconds * 4)
                    return payload
            except urllib.error.HTTPError as error:
                self._last_request_at = time.monotonic()
                if error.code == 429:
                    retry_after = error.headers.get("Retry-After") if error.headers else None
                    time.sleep(
                        float(retry_after) if retry_after else self.request_delay_seconds * 5
                    )
                    last_error = error
                    continue
                raise DiscogsApiError(f"release {release_id}: HTTP {error.code}") from error
            except (urllib.error.URLError, TimeoutError) as error:
                last_error = error
                time.sleep(2**attempt)
        raise DiscogsApiError(
            f"release {release_id}: failed after {self.retries} attempts: {last_error}"
        )


@dataclass(slots=True)
class ReleaseCache:
    """Atomic on-disk cache for raw release API responses, keyed by release_id."""

    directory: Path

    def path_for(self, release_id: int) -> Path:
        return self.directory / f"{release_id}.json"

    def get(self, release_id: int) -> dict[str, Any] | None:
        path = self.path_for(release_id)
        if not path.exists():
            return None
        result: dict[str, Any] = json.loads(path.read_text())
        return result

    def put(self, release_id: int, payload: dict[str, Any]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.path_for(release_id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload))
        tmp.replace(path)


def fetch_releases(
    release_ids: list[int],
    *,
    client: ApiClient,
    cache: ReleaseCache,
    on_progress: Callable[[int, int, bool], None] | None = None,
) -> dict[int, dict[str, Any]]:
    """Fetch every release, preferring cache; only cache misses hit the network."""
    results: dict[int, dict[str, Any]] = {}
    total = len(release_ids)
    for index, release_id in enumerate(release_ids, start=1):
        cached = cache.get(release_id)
        if cached is not None:
            results[release_id] = cached
            if on_progress:
                on_progress(index, total, True)
            continue
        payload = client.fetch_release(release_id)
        cache.put(release_id, payload)
        results[release_id] = payload
        if on_progress:
            on_progress(index, total, False)
    return results
