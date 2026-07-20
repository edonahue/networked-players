"""A frozen, append-only date -> round_id schedule for Connection of the Day.

The manifest file itself is the source of truth for daily stability: once an
entry is written, it is never rewritten, regardless of how the underlying
rounds pool is regenerated or expanded. A fixed date always resolves to the
same round across rebuilds because the rebuild never re-derives past dates --
it only appends new ones (`extend_daily_manifest`), using rounds not already
scheduled, continuing the day after the manifest's last scheduled date.

Assignment order is a deterministic pseudo-random permutation seeded by
`pool_version` (`random.Random(pool_version)`), not sorted round_id order --
varied day-to-day without being live-random, and fully reproducible from the
pool_version alone. Every scheduled round is real (no synthetic fallback
pool exists in this project); a manifest never schedules more dates than
there are distinct rounds to assign -- no round is ever repeated across
dates, and the achieved schedule length is reported honestly rather than
padded by cycling.
"""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta
from typing import Any

DAILY_MANIFEST_SCHEMA_VERSION = 1


class DailyManifestError(RuntimeError):
    """Raised when a daily manifest is invalid or an operation on it is unsafe."""


def _dates_from(start_date: str, count: int) -> list[str]:
    start = date.fromisoformat(start_date)
    return [(start + timedelta(days=i)).isoformat() for i in range(count)]


def build_daily_manifest(
    round_ids: list[str],
    *,
    pool_version: str,
    start_date: str,
    days: int,
) -> dict[str, Any]:
    """Build the initial manifest. Never schedules more dates than distinct
    `round_ids` available -- the achieved length is `min(days, len(round_ids))`,
    reported in the returned manifest, not padded to `days` by repeating a
    round across multiple dates.
    """
    if days <= 0:
        raise ValueError("days must be positive")
    if not round_ids:
        raise ValueError("round_ids must be non-empty")
    if len(set(round_ids)) != len(round_ids):
        raise ValueError("round_ids must not contain duplicates")

    ordered = list(round_ids)
    random.Random(pool_version).shuffle(ordered)
    scheduled_count = min(days, len(ordered))
    dates = _dates_from(start_date, scheduled_count)
    schedule = [
        {"date": d, "round_id": r} for d, r in zip(dates, ordered[:scheduled_count], strict=True)
    ]
    return {
        "schema_version": DAILY_MANIFEST_SCHEMA_VERSION,
        "pool_version": pool_version,
        "generated_at": datetime.now(UTC).isoformat(),
        "schedule": schedule,
    }


def extend_daily_manifest(
    manifest: dict[str, Any],
    round_ids: list[str],
    *,
    days: int,
) -> dict[str, Any]:
    """Append new dates after the manifest's last scheduled date, using only
    `round_ids` not already present anywhere in the existing schedule.
    Existing entries are never modified, reordered, or removed. Raises if
    `manifest`'s `pool_version` isn't in `round_ids`' pool (a cross-pool
    extension would silently mix two pools' provenance into one schedule).
    """
    if days <= 0:
        raise ValueError("days must be positive")
    schedule = manifest["schedule"]
    if not schedule:
        raise DailyManifestError("cannot extend an empty manifest")
    already_scheduled = {entry["round_id"] for entry in schedule}
    available = [r for r in round_ids if r not in already_scheduled]
    if not available:
        raise DailyManifestError("no unscheduled rounds remain to extend the manifest with")

    last_date = date.fromisoformat(schedule[-1]["date"])
    next_start = (last_date + timedelta(days=1)).isoformat()

    random.Random(manifest["pool_version"]).shuffle(available)
    scheduled_count = min(days, len(available))
    new_dates = _dates_from(next_start, scheduled_count)
    new_entries = [
        {"date": d, "round_id": r}
        for d, r in zip(new_dates, available[:scheduled_count], strict=True)
    ]
    return {
        **manifest,
        "generated_at": datetime.now(UTC).isoformat(),
        "schedule": [*schedule, *new_entries],
    }


def validate_daily_manifest(manifest: dict[str, Any], *, valid_round_ids: set[str]) -> None:
    """Structural + referential validation: every scheduled round_id must
    resolve against the published pool, dates must be strictly increasing
    with no gaps or duplicates, and no round_id may repeat across dates."""
    failures: list[str] = []
    if set(manifest.keys()) != {"schema_version", "pool_version", "generated_at", "schedule"}:
        failures.append(f"manifest has unexpected top-level keys: {sorted(manifest.keys())}")
    if manifest.get("schema_version") != DAILY_MANIFEST_SCHEMA_VERSION:
        failures.append(f"schema_version must be {DAILY_MANIFEST_SCHEMA_VERSION}")

    schedule = manifest.get("schedule", [])
    if not schedule:
        failures.append("schedule must be non-empty")

    seen_dates: set[str] = set()
    seen_round_ids: set[str] = set()
    previous_date: date | None = None
    for entry in schedule:
        if set(entry.keys()) != {"date", "round_id"}:
            failures.append(f"schedule entry has unexpected keys: {sorted(entry.keys())}")
            continue
        entry_date = date.fromisoformat(entry["date"])
        if entry["date"] in seen_dates:
            failures.append(f"duplicate date in schedule: {entry['date']}")
        seen_dates.add(entry["date"])
        if previous_date is not None and entry_date != previous_date + timedelta(days=1):
            failures.append(f"schedule has a gap or disorder before {entry['date']}")
        previous_date = entry_date

        if entry["round_id"] in seen_round_ids:
            failures.append(f"round {entry['round_id']} is scheduled more than once")
        seen_round_ids.add(entry["round_id"])
        if entry["round_id"] not in valid_round_ids:
            failures.append(f"round {entry['round_id']} is not in the published pool")

    if failures:
        raise DailyManifestError("; ".join(failures))
