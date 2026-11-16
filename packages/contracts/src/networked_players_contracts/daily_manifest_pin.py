"""Pin for already-played daily dates (Atlas F4a; ADR 0041, ADR 0066).

The daily manifest is append-only: once a visitor has played a date, that
date must keep resolving to the same round. `connection_daily_manifest*`
verifies each entry's `round_fingerprint` against its generation's rounds
file, but that cannot notice a past date being re-pointed at a *different*
valid round of the same generation. This module closes that gap with a small
committed pin over the played prefix of the schedule.

ADR 0066 allows rewriting only dates on or after a generation cutover, i.e.
dates nobody has played yet. The pin never covers such dates: `advance_pin`
refuses a `pinned_through` that is not strictly before `as_of` (today, UTC),
so a future-dated entry stays rewritable.

Pin file (`data/integrity/daily-manifest-pin-v1.json`, deliberately NOT under
the served `apps/web/public/` tree -- it is a repository integrity record,
not something a browser needs):

    schema_version   1
    pinned_through   ISO date; every schedule entry with date <= this is pinned
    entry_count      number of pinned entries
    content_hash     content_hash over the ordered
                     [date, generation, round_id, round_fingerprint] tuples
    date_digests     {date: 8-hex digest of that one tuple}; lets the validator
                     name the first differing date cheaply. 32 bits per date
                     cannot recover a round, so this does not duplicate the
                     schedule.

Dependency-free, like every module in this package. A schema-v1 manifest has
no per-entry `generation`; its tuples carry `None` there.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .canonical import content_hash

DAILY_MANIFEST_PIN_SCHEMA_VERSION = 1
_PIN_KEYS = frozenset(
    {"schema_version", "pinned_through", "entry_count", "content_hash", "date_digests"}
)
_HASH_LENGTH = 32
_DIGEST_LENGTH = 8


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _entry_tuple(entry: dict[str, Any]) -> list[Any]:
    return [
        entry.get("date"),
        entry.get("generation"),
        entry.get("round_id"),
        entry.get("round_fingerprint"),
    ]


def pinned_prefix(manifest: Any, through: str) -> list[list[Any]]:
    """Ordered `[date, generation, round_id, round_fingerprint]` tuples for
    every manifest entry with date <= `through`. Dates are parsed, so a
    malformed one is skipped (the manifest validator reports it) rather than
    mis-ordered."""
    limit = _parse_date(through)
    schedule = manifest.get("schedule") if isinstance(manifest, dict) else None
    if limit is None or not isinstance(schedule, list):
        return []
    tuples: list[list[Any]] = []
    for entry in schedule:
        if not isinstance(entry, dict):
            continue
        entry_date = _parse_date(entry.get("date"))
        if entry_date is not None and entry_date <= limit:
            tuples.append(_entry_tuple(entry))
    return tuples


def build_pin(manifest: Any, through: str) -> dict[str, Any]:
    """The pin for `manifest` through `through` (no policy checks; see
    `advance_pin` for the guarded operation)."""
    tuples = pinned_prefix(manifest, through)
    return {
        "schema_version": DAILY_MANIFEST_PIN_SCHEMA_VERSION,
        "pinned_through": through,
        "entry_count": len(tuples),
        "content_hash": content_hash(tuples, length=_HASH_LENGTH),
        "date_digests": {t[0]: content_hash(t, length=_DIGEST_LENGTH) for t in tuples},
    }


def daily_manifest_pin_failures(manifest: Any, pin: Any) -> list[str]:
    """Contract failures: the committed manifest's played prefix no longer
    matches the pin. Names the first differing date when determinable."""
    if not isinstance(pin, dict):
        return ["daily manifest pin must be an object"]
    if not isinstance(manifest, dict):
        return ["manifest artifact must be an object"]
    if set(pin.keys()) != _PIN_KEYS:
        return [f"daily manifest pin has unexpected keys: {sorted(pin.keys())}"]
    if pin.get("schema_version") != DAILY_MANIFEST_PIN_SCHEMA_VERSION:
        return [f"daily manifest pin schema_version must be {DAILY_MANIFEST_PIN_SCHEMA_VERSION}"]
    through = pin.get("pinned_through")
    if _parse_date(through) is None or not isinstance(through, str):
        return [f"daily manifest pin pinned_through {through!r} is not a valid ISO date"]
    digests = pin.get("date_digests")
    if not isinstance(digests, dict):
        return ["daily manifest pin date_digests must be an object"]

    tuples = pinned_prefix(manifest, through)
    current = {t[0]: content_hash(t, length=_DIGEST_LENGTH) for t in tuples}
    if (
        content_hash(tuples, length=_HASH_LENGTH) == pin.get("content_hash")
        and len(tuples) == pin.get("entry_count")
        and current == digests
    ):
        return []

    problems: list[str] = []
    for pinned_date in sorted(digests):
        if pinned_date not in current:
            problems.append(f"pinned date {pinned_date} is missing from the manifest")
        elif current[pinned_date] != digests[pinned_date]:
            problems.append(
                f"pinned date {pinned_date} was changed (its round, generation or "
                f"fingerprint differs from the pin)"
            )
    for manifest_date in sorted(current):
        if manifest_date not in digests:
            problems.append(f"manifest has date {manifest_date} inside the pinned range, unpinned")
    if not problems:
        problems.append("the pinned prefix hash differs (entry order or digest set changed)")
    problems.sort()
    return [
        f"already-played daily dates (<= {through}) differ from the committed pin; first "
        f"difference: {problems[0]}; {len(problems)} difference(s) in total. The daily "
        f"manifest is append-only for played dates (ADR 0041, ADR 0066)."
    ]


def advance_pin(
    manifest: Any,
    existing_pin: Any,
    through: str,
    *,
    as_of: str,
) -> dict[str, Any]:
    """The pin advanced to `through`, or ValueError naming the refusal.

    Refuses: a malformed date; a date not strictly before `as_of` (a played
    date is a past date); a date beyond the manifest's last date; moving
    backwards from an existing pin; and any advance while the already-pinned
    prefix no longer matches the manifest (re-pinning must never launder a
    changed past date)."""
    through_date = _parse_date(through)
    as_of_date = _parse_date(as_of)
    if through_date is None:
        raise ValueError(f"--through {through!r} is not a valid ISO date")
    if as_of_date is None:
        raise ValueError(f"as-of {as_of!r} is not a valid ISO date")
    if through_date >= as_of_date:
        raise ValueError(
            f"refusing to pin {through}: only dates strictly before {as_of} have been played; "
            f"future dates may still legitimately be rewritten at a generation cutover (ADR 0066)"
        )
    schedule = manifest.get("schedule") if isinstance(manifest, dict) else None
    dates = [
        d for d in (_parse_date(e.get("date")) for e in schedule or [] if isinstance(e, dict)) if d
    ]
    if not dates:
        raise ValueError("manifest has no schedule dates to pin")
    if through_date > max(dates):
        raise ValueError(f"refusing to pin {through}: beyond the manifest's last date {max(dates)}")
    if through_date < min(dates):
        raise ValueError(f"refusing to pin {through}: before the manifest's first date")
    if existing_pin is not None:
        failures = daily_manifest_pin_failures(manifest, existing_pin)
        if failures:
            raise ValueError(
                "refusing to advance: the already-pinned prefix no longer matches the "
                f"manifest -- {failures[0]}"
            )
        previous = _parse_date(existing_pin.get("pinned_through"))
        if previous is not None and through_date < previous:
            raise ValueError(
                f"refusing to move the pin backwards ({through} < {existing_pin['pinned_through']})"
            )
    return build_pin(manifest, through)
