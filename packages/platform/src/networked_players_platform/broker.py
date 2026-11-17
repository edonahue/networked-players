"""Redis storage for worker advertisements and queue naming."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Protocol

from redis import Redis

from .models import WorkerAdvertisement

WORKER_KEY_PREFIX = "networked-players:platform:worker:"
WORKER_TTL_SECONDS = 120
QUEUE_PREFIX = "networked-players.platform."
RQ_WORKER_KEY_PREFIX = "rq:worker:"
# RQ's default worker_ttl: the `rq:worker:<name>` key expires this long after the
# worker last heartbeated (idle workers refresh it every dequeue timeout, running
# ones every ~30 s). The worker unit does not override it.
RQ_WORKER_TTL_SECONDS = 420
# While a job runs RQ refreshes the worker record every ~30 s with a 90 s expiry
# (job_monitoring_interval + 60), so a started job's worker is only "live" if its
# last heartbeat is this recent; used for the post-deadline timeout decision.
RQ_BUSY_WORKER_TTL_SECONDS = 90


class AdvertisementStore(Protocol):
    def setex(self, name: str, time: int, value: str) -> object: ...

    def scan_iter(self, match: str) -> Iterable[bytes | str]: ...

    def get(self, name: bytes | str) -> bytes | str | None: ...


def redis_from_url(url: str) -> Redis:
    return Redis.from_url(url, decode_responses=False, socket_connect_timeout=5)


def queue_name(worker_id: str) -> str:
    return QUEUE_PREFIX + worker_id


def publish_advertisement(
    store: AdvertisementStore,
    advertisement: WorkerAdvertisement,
    *,
    ttl_seconds: int = WORKER_TTL_SECONDS,
) -> None:
    key = WORKER_KEY_PREFIX + advertisement.worker_id
    store.setex(key, ttl_seconds, json.dumps(advertisement.to_dict(), sort_keys=True))


def read_advertisements_checked(
    store: AdvertisementStore,
) -> tuple[list[WorkerAdvertisement], dict[str, str]]:
    """(advertisements, problems): one malformed or unsupported advertisement is
    skipped with a per-worker reason instead of breaking submit, `jobs` and status.
    Note an old checkout's `WorkerAdvertisement` rejects schema 2 outright, so
    submitters from before ADR 0073 fail closed against an upgraded fleet."""
    advertisements: list[WorkerAdvertisement] = []
    problems: dict[str, str] = {}
    for key in store.scan_iter(match=WORKER_KEY_PREFIX + "*"):
        text_key = key.decode() if isinstance(key, bytes) else key
        worker_id = text_key.removeprefix(WORKER_KEY_PREFIX)
        raw = store.get(key)
        if raw is None:
            continue
        text = raw.decode() if isinstance(raw, bytes) else raw
        try:
            advertisements.append(WorkerAdvertisement.from_dict(json.loads(text)))
        except (ValueError, TypeError, KeyError) as exc:
            problems[worker_id] = f"unreadable advertisement: {type(exc).__name__}: {exc}"[:200]
    return sorted(advertisements, key=lambda item: item.worker_id), problems


def read_advertisements(store: AdvertisementStore) -> list[WorkerAdvertisement]:
    return read_advertisements_checked(store)[0]


class RqWorkerStore(Protocol):
    def hget(self, name: str, key: str) -> bytes | str | None: ...


def read_rq_worker_heartbeat(store: RqWorkerStore, worker_id: str) -> datetime | None:
    """RQ's own liveness for the consumer of `worker_id`'s queue: the `last_heartbeat`
    of its `rq:worker:<name>` record (None when the record is absent, i.e. the RQ
    worker process is not running or its key expired). Independent of the separate
    heartbeat timer that publishes the advertisement. Read-only."""
    raw = store.hget(RQ_WORKER_KEY_PREFIX + worker_id, "last_heartbeat")
    if raw is None:
        return None
    text = raw.decode() if isinstance(raw, bytes) else raw
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None
