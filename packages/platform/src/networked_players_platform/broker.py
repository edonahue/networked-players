"""Redis storage for worker advertisements and queue naming."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Protocol

from redis import Redis

from .models import WorkerAdvertisement

WORKER_KEY_PREFIX = "networked-players:platform:worker:"
WORKER_TTL_SECONDS = 120


class AdvertisementStore(Protocol):
    def setex(self, name: str, time: int, value: str) -> object: ...

    def scan_iter(self, match: str) -> Iterable[bytes | str]: ...

    def get(self, name: bytes | str) -> bytes | str | None: ...


def redis_from_url(url: str) -> Redis:
    return Redis.from_url(url, decode_responses=False, socket_connect_timeout=5)


def queue_name(worker_id: str) -> str:
    return f"networked-players.platform.{worker_id}"


def publish_advertisement(
    store: AdvertisementStore,
    advertisement: WorkerAdvertisement,
    *,
    ttl_seconds: int = WORKER_TTL_SECONDS,
) -> None:
    key = WORKER_KEY_PREFIX + advertisement.worker_id
    store.setex(key, ttl_seconds, json.dumps(advertisement.to_dict(), sort_keys=True))


def read_advertisements(store: AdvertisementStore) -> list[WorkerAdvertisement]:
    advertisements: list[WorkerAdvertisement] = []
    for key in store.scan_iter(match=WORKER_KEY_PREFIX + "*"):
        raw = store.get(key)
        if raw is None:
            continue
        text = raw.decode() if isinstance(raw, bytes) else raw
        advertisements.append(WorkerAdvertisement.from_dict(json.loads(text)))
    return sorted(advertisements, key=lambda item: item.worker_id)
