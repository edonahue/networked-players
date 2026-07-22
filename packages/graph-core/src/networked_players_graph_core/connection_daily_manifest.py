"""A frozen, append-only date -> round schedule for Connection of the Day,
scoped specifically to the flagship Connection Guesser's real one-hop pool
(slice 5, ADR 0043's corrective-slice-4.6 addendum).

Deliberately a NEW module, not a reuse of `daily_manifest.py`: that module
was built and proven against PR #43's Record Routes path-shaped
`universe.v1`/`rounds.v1` pair (`rounds.py::build_rounds_v1`, top-level
`pool_version`, no mode identity) -- confirmed by its own ADR 0041's
"172 scheduled dates from a 172-round pool" measurement, which is the
Record Routes round count, not the Connection Guesser's. Reusing it for the
Guesser's differently-shaped artifact (`provenance.pool_version`, not a
top-level field; no built-in one-hop/real-records filtering) would have been
exactly the "ambiguous between Record Routes and Connection Guesser" trap
already found and fixed once for the Pi-fleet validator wiring (corrective
slice 4.5, Finding 8). This module is explicit about which contract it
schedules and never silently accepts the other.

The manifest file itself is the source of truth for daily stability: once an
entry is written, it is never rewritten. A fixed date always resolves to the
same round across rebuilds because rebuilding never re-derives past dates --
it only appends new ones (`extend_connection_daily_manifest`), and every
extension re-verifies every EXISTING entry's `round_fingerprint` against the
current rounds artifact before appending anything, so a silent content
change to an already-scheduled round is caught, not propagated.
"""

from __future__ import annotations

import random
import re
from datetime import date, datetime, timedelta
from typing import Any

from .connection_rounds import round_content_fingerprint

CONNECTION_DAILY_MANIFEST_SCHEMA_VERSION = 1
CONNECTION_DAILY_MANIFEST_MODE = "connection_guesser_one_hop"

_MANIFEST_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "mode",
        "catalog_version",
        "pool_version",
        "artifact_version",
        "generated_at",
        "start_date",
        "schedule",
    }
)
_SCHEDULE_ENTRY_KEYS = frozenset({"date", "round_id", "round_fingerprint"})
_VERSION_FIELDS = ("catalog_version", "pool_version", "artifact_version")

_ROUND_ID_PATTERN = re.compile(r"^conn-[0-9a-f]{10}$")
_ROUND_FINGERPRINT_PATTERN = re.compile(r"^rfp-[0-9a-f]{16}$")
_FORBIDDEN_SUBSTRINGS = ("/home/", "data/private", "local/", "DISCOGS_TOKEN", ".ssh")
_FORBIDDEN_PHRASES = ("worked with", "collaborated with", "influenced")


class ConnectionDailyManifestError(RuntimeError):
    """Raised when a Connection Guesser daily manifest is invalid or an
    operation on it is unsafe."""


def _parse_iso_date(value: Any, *, context: str) -> date:
    if not isinstance(value, str):
        raise ConnectionDailyManifestError(f"{context} must be a string, got {value!r}")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ConnectionDailyManifestError(f"{context} {value!r} is not a valid date") from exc


def _parse_iso_datetime(value: Any, *, context: str) -> datetime:
    if not isinstance(value, str):
        raise ConnectionDailyManifestError(f"{context} must be a string, got {value!r}")
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ConnectionDailyManifestError(f"{context} {value!r} is not a valid datetime") from exc


def _dates_from(start_date: str, count: int) -> list[str]:
    start = _parse_iso_date(start_date, context="start_date")
    return [(start + timedelta(days=i)).isoformat() for i in range(count)]


def _version_mismatches(manifest: dict[str, Any], rounds_artifact: dict[str, Any]) -> list[str]:
    """Schema-v1 rule: a single manifest may only ever contain entries from
    ONE exact rounds-artifact generation. All three identity fields --
    `catalog_version`, `pool_version`, `artifact_version` -- must agree
    exactly between the manifest and the paired rounds artifact before
    building, validating, or extending. A mismatch on any of the three
    (including one caused by an unscheduled round's content silently
    changing, or the rounds array being reordered -- both move
    `artifact_version` even when `pool_version`/membership is unchanged)
    means this rounds artifact is a different generation than the one this
    manifest was built against. Mixing generations inside one manifest is
    not supported in schema v1: if the pool has genuinely moved on, that is
    an explicit, documented, versioned migration decision for an operator to
    make -- never something extension or validation silently papers over
    (see the module docstring, corrective slice 5.1)."""
    provenance = rounds_artifact.get("provenance", {})
    failures: list[str] = []
    for field_name in _VERSION_FIELDS:
        manifest_value = manifest.get(field_name)
        rounds_value = provenance.get(field_name)
        if manifest_value != rounds_value:
            failures.append(
                f"manifest {field_name} {manifest_value!r} does not match the paired rounds "
                f"artifact's {field_name} {rounds_value!r} -- this manifest was built against "
                f"a different generation of the rounds artifact; schema v1 does not support "
                f"mixing generations inside one manifest"
            )
    return failures


def _eligible_one_hop_rounds(rounds_artifact: dict[str, Any]) -> list[dict[str, Any]]:
    """Explicit filter -- never schedule every id in rounds.v1.json. Only
    real, one-hop rounds are ever daily-eligible (two-hop, Record Routes
    path rounds, and synthetic fixtures are never valid here even if they
    somehow appeared in the input)."""
    return [
        r
        for r in rounds_artifact.get("rounds", [])
        if r.get("pool") == "real-records" and r.get("kind") == "one_hop"
    ]


def _conflict_keys(round_json: dict[str, Any]) -> set[str]:
    """Endpoint album ids + accepted performer ids -- rounds sharing any of
    these are a poor pair for adjacent days (repeated record or repeated
    answer, two days running)."""
    keys = {f"album:{e['id']}" for e in round_json.get("endpoints", [])}
    keys |= {f"performer:{a['id']}" for a in round_json.get("answer_set", [])}
    return keys


def _quality_scheduled_order(
    eligible: list[dict[str, Any]],
    *,
    seed: str,
    previous_round: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """A deterministic pseudo-random permutation (seeded by `seed`, e.g.
    `pool_version` -- reproducible, not live-random, not sorted-by-id order
    so consecutive days don't visibly correlate with generation order),
    followed by a single deterministic forward lookahead-swap pass that
    avoids the worst adjacent-day repetition: a round sharing an endpoint
    album or an accepted performer with the immediately preceding day is
    swapped with the nearest later round that does not conflict. Bounded,
    single-pass, and deliberately not a recommendation system -- it does not
    optimize decade/difficulty balance, only reports it (see
    `schedule_diagnostics`).

    `previous_round`, when given (extension only), is the manifest's current
    LAST scheduled round -- the boundary between old and new entries is just
    as much an "adjacent day" as any internal one, so the first newly
    ordered round is swapped away from a conflict with it exactly like any
    internal pair (corrective slice 5.1). `None` for the initial build,
    where there is no prior day."""
    ordered = list(eligible)
    random.Random(seed).shuffle(ordered)

    if previous_round is not None and ordered:
        boundary_keys = _conflict_keys(previous_round)
        if _conflict_keys(ordered[0]) & boundary_keys:
            for j in range(1, len(ordered)):
                if not (_conflict_keys(ordered[j]) & boundary_keys):
                    ordered[0], ordered[j] = ordered[j], ordered[0]
                    break
            # If no non-conflicting candidate remains, leave it -- a forced
            # repeat is honestly reported by diagnostics, not hidden.

    for i in range(1, len(ordered)):
        previous_keys = _conflict_keys(ordered[i - 1])
        if not (_conflict_keys(ordered[i]) & previous_keys):
            continue
        for j in range(i + 1, len(ordered)):
            if not (_conflict_keys(ordered[j]) & previous_keys):
                ordered[i], ordered[j] = ordered[j], ordered[i]
                break
        # If no non-conflicting candidate remains ahead, leave it -- a
        # forced repeat is honestly reported by diagnostics, not hidden.
    return ordered


def build_connection_daily_manifest(
    rounds_artifact: dict[str, Any], *, start_date: str, days: int, generated_at: str
) -> dict[str, Any]:
    """Build the initial manifest. Never schedules more dates than there are
    eligible one-hop rounds -- the achieved length is
    `min(days, len(eligible))`, reported honestly rather than padded by
    repeating a round across dates (no repeat policy until the whole
    eligible pool has been used once; see the module docstring).

    `generated_at` is an explicit caller-supplied ISO datetime, never the
    wall clock -- so that running this function twice with identical
    arguments (including `generated_at`) produces a byte-identical
    manifest, which a committed artifact and its own reproducibility tests
    require (corrective slice 5.1). Callers that want "now" must pass
    `datetime.now(UTC).isoformat()` themselves; this function never reads
    the clock internally."""
    if days <= 0:
        raise ValueError("days must be positive")
    _parse_iso_datetime(generated_at, context="generated_at")
    provenance = rounds_artifact.get("provenance", {})
    eligible = _eligible_one_hop_rounds(rounds_artifact)
    if not eligible:
        raise ConnectionDailyManifestError(
            "no eligible one-hop real-records rounds found in the rounds artifact"
        )

    pool_version = provenance.get("pool_version")
    for field_name in _VERSION_FIELDS:
        if not provenance.get(field_name):
            raise ConnectionDailyManifestError(
                f"rounds artifact provenance.{field_name} is required and must be non-empty"
            )

    ordered = _quality_scheduled_order(eligible, seed=str(pool_version))
    scheduled_count = min(days, len(ordered))
    dates = _dates_from(start_date, scheduled_count)
    schedule = [
        {
            "date": d,
            "round_id": r["id"],
            "round_fingerprint": round_content_fingerprint(r),
        }
        for d, r in zip(dates, ordered[:scheduled_count], strict=True)
    ]
    return {
        "schema_version": CONNECTION_DAILY_MANIFEST_SCHEMA_VERSION,
        "mode": CONNECTION_DAILY_MANIFEST_MODE,
        "catalog_version": provenance.get("catalog_version"),
        "pool_version": pool_version,
        "artifact_version": provenance.get("artifact_version"),
        "generated_at": generated_at,
        "start_date": start_date,
        "schedule": schedule,
    }


def extend_connection_daily_manifest(
    manifest: dict[str, Any], rounds_artifact: dict[str, Any], *, days: int, generated_at: str
) -> dict[str, Any]:
    """Append new dates after the manifest's last scheduled date.

    Before anything else -- before any output is produced -- the manifest's
    `catalog_version`/`pool_version`/`artifact_version` must agree exactly
    with the paired `rounds_artifact`'s provenance (`_version_mismatches`,
    schema-v1's single-generation rule; corrective slice 5.1). Only once
    that passes does every EXISTING entry's `round_fingerprint` get
    re-verified against `rounds_artifact` -- if a previously-scheduled round
    is missing or its content has silently changed, this raises rather than
    extending on top of a corrupted history. New dates are drawn only from
    eligible one-hop rounds not already anywhere in the schedule, ordered
    with the manifest's current last round as adjacency context (so the
    first appended date also avoids repeating the prior day's endpoint or
    performer when a non-conflicting candidate exists); once the eligible
    pool is exhausted, this raises rather than silently cycling or
    reshuffling prior dates (no cycling policy is implemented yet -- see the
    module docstring). Metadata is never silently rewritten: only
    `generated_at` (an explicit caller-supplied value, never the wall clock)
    and the appended `schedule` entries change -- `catalog_version`/
    `pool_version`/`artifact_version`/`mode`/`schema_version`/`start_date`
    are carried over unchanged from the input manifest."""
    if days <= 0:
        raise ValueError("days must be positive")
    _parse_iso_datetime(generated_at, context="generated_at")
    schedule = manifest.get("schedule")
    if not schedule:
        raise ConnectionDailyManifestError("cannot extend an empty manifest")

    version_failures = _version_mismatches(manifest, rounds_artifact)
    if version_failures:
        raise ConnectionDailyManifestError("; ".join(version_failures))

    eligible = _eligible_one_hop_rounds(rounds_artifact)
    eligible_by_id = {r["id"]: r for r in eligible}

    for entry in schedule:
        round_json = eligible_by_id.get(entry["round_id"])
        if round_json is None:
            raise ConnectionDailyManifestError(
                f"existing entry for {entry['date']} references round {entry['round_id']!r}, "
                "which is missing from the current rounds artifact (or is no longer a "
                "real one-hop round) -- refusing to extend on top of a broken history"
            )
        current_fingerprint = round_content_fingerprint(round_json)
        if current_fingerprint != entry["round_fingerprint"]:
            raise ConnectionDailyManifestError(
                f"existing entry for {entry['date']} (round {entry['round_id']}) has a "
                f"content fingerprint mismatch: manifest expects "
                f"{entry['round_fingerprint']!r}, current artifact has "
                f"{current_fingerprint!r} -- the round's published content changed "
                f"silently, refusing to extend on top of a broken history"
            )

    already_scheduled = {entry["round_id"] for entry in schedule}
    available = [r for r in eligible if r["id"] not in already_scheduled]
    if not available:
        raise ConnectionDailyManifestError(
            "every eligible one-hop round has already been scheduled once; no repeat "
            "policy is implemented yet (see the module docstring) -- either grow the "
            "real round pool or make an explicit, documented decision about cycling"
        )

    last_date = _parse_iso_date(schedule[-1]["date"], context="schedule[-1].date")
    next_start = (last_date + timedelta(days=1)).isoformat()
    last_round_json = eligible_by_id[schedule[-1]["round_id"]]

    ordered = _quality_scheduled_order(
        available, seed=str(manifest.get("pool_version")), previous_round=last_round_json
    )
    scheduled_count = min(days, len(ordered))
    new_dates = _dates_from(next_start, scheduled_count)
    new_entries = [
        {
            "date": d,
            "round_id": r["id"],
            "round_fingerprint": round_content_fingerprint(r),
        }
        for d, r in zip(new_dates, ordered[:scheduled_count], strict=True)
    ]
    return {
        **manifest,
        "generated_at": generated_at,
        "schedule": [*schedule, *new_entries],
    }


def _find_seed_keys(obj: Any, path: str = "") -> list[str]:
    """Recursively collect dotted paths to any dict key literally named
    ``seed`` anywhere in the manifest -- mirrors the same recursive scan used
    for the Connection Guesser universe/rounds pair (`connection_rounds.py
    ::_find_seed_keys`)."""
    found: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            child = f"{path}.{key}" if path else str(key)
            if key == "seed":
                found.append(child)
            found.extend(_find_seed_keys(value, child))
    elif isinstance(obj, list):
        for index, item in enumerate(obj):
            found.extend(_find_seed_keys(item, f"{path}[{index}]"))
    return found


def _privacy_failures(manifest: dict[str, Any]) -> list[str]:
    serialized = str(manifest)
    failures = [
        f"manifest contains forbidden substring: {forbidden!r}"
        for forbidden in _FORBIDDEN_SUBSTRINGS
        if forbidden in serialized
    ]
    lowered = serialized.lower()
    failures.extend(
        f"manifest contains forbidden phrase: {phrase!r}"
        for phrase in _FORBIDDEN_PHRASES
        if phrase in lowered
    )
    return failures


def _safe_parse(parser: Any, value: str) -> Any:
    try:
        return parser(value)
    except ValueError:
        return None


def validate_connection_daily_manifest(
    manifest: dict[str, Any], rounds_artifact: dict[str, Any]
) -> None:
    """Structural, referential, version-agreement, and content-integrity
    validation. Every scheduled round must resolve in `rounds_artifact` as a
    real one-hop round, dates must be contiguous and unique, round ids must
    not repeat, every entry's `round_fingerprint` must match a fresh
    recomputation, and the manifest's own `catalog_version`/`pool_version`/
    `artifact_version` must agree exactly with the paired rounds artifact
    (schema v1's single-generation rule, `_version_mismatches`) -- a
    silently-changed round, a reordered rounds array, or hand-edited
    manifest metadata are all validation failures, not runtime surprises."""
    failures: list[str] = [
        f"manifest must not have a 'seed' key ({p})" for p in _find_seed_keys(manifest)
    ]
    failures.extend(_privacy_failures(manifest))

    if set(manifest.keys()) != _MANIFEST_TOP_LEVEL_KEYS:
        failures.append(f"manifest has unexpected top-level keys: {sorted(manifest.keys())}")
    if manifest.get("schema_version") != CONNECTION_DAILY_MANIFEST_SCHEMA_VERSION:
        failures.append(f"schema_version must be {CONNECTION_DAILY_MANIFEST_SCHEMA_VERSION}")
    if manifest.get("mode") != CONNECTION_DAILY_MANIFEST_MODE:
        failures.append(f"mode must be {CONNECTION_DAILY_MANIFEST_MODE!r}")
    for field_name in (*_VERSION_FIELDS, "start_date"):
        if not manifest.get(field_name):
            failures.append(f"{field_name} is required")

    generated_at = manifest.get("generated_at")
    if not generated_at:
        failures.append("generated_at is required")
    elif (
        not isinstance(generated_at, str)
        or _safe_parse(datetime.fromisoformat, generated_at) is None
    ):
        failures.append(f"generated_at {generated_at!r} is not a valid ISO datetime")

    start_date = manifest.get("start_date")
    if start_date is not None and (
        not isinstance(start_date, str) or _safe_parse(date.fromisoformat, start_date) is None
    ):
        failures.append(f"start_date {start_date!r} is not a valid ISO date")

    failures.extend(_version_mismatches(manifest, rounds_artifact))

    eligible_by_id = {r["id"]: r for r in _eligible_one_hop_rounds(rounds_artifact)}
    all_rounds_by_id = {r["id"]: r for r in rounds_artifact.get("rounds", [])}

    schedule = manifest.get("schedule", [])
    if not schedule:
        failures.append("schedule must be non-empty")
    elif start_date is not None and schedule[0].get("date") != start_date:
        failures.append(
            f"start_date {start_date!r} does not match schedule[0].date {schedule[0].get('date')!r}"
        )

    seen_dates: set[str] = set()
    seen_round_ids: set[str] = set()
    previous_date: date | None = None
    for entry in schedule:
        if not isinstance(entry, dict):
            failures.append(f"schedule entry must be an object, got {entry!r}")
            continue
        if set(entry.keys()) != _SCHEDULE_ENTRY_KEYS:
            failures.append(f"schedule entry has unexpected keys: {sorted(entry.keys())}")
            continue

        raw_date = entry.get("date")
        entry_date = (
            _safe_parse(date.fromisoformat, raw_date) if isinstance(raw_date, str) else None
        )
        if entry_date is None or not isinstance(raw_date, str):
            failures.append(f"schedule entry date {raw_date!r} is not a valid ISO date")
            continue
        entry_date_str: str = raw_date
        if entry_date_str in seen_dates:
            failures.append(f"duplicate date in schedule: {entry_date_str}")
        seen_dates.add(entry_date_str)
        if previous_date is not None and entry_date != previous_date + timedelta(days=1):
            failures.append(f"schedule has a gap or disorder before {entry_date_str}")
        previous_date = entry_date

        round_id = entry["round_id"]
        if not isinstance(round_id, str) or not _ROUND_ID_PATTERN.match(round_id):
            failures.append(
                f"round id {round_id!r} (date {entry_date_str}) is not a stable content-derived id"
            )
        if round_id in seen_round_ids:
            failures.append(f"round {round_id} is scheduled more than once")
        seen_round_ids.add(round_id)

        fingerprint = entry.get("round_fingerprint")
        if not isinstance(fingerprint, str) or not _ROUND_FINGERPRINT_PATTERN.match(fingerprint):
            failures.append(
                f"round_fingerprint {fingerprint!r} (date {entry_date_str}) is not a "
                f"well-formed content fingerprint"
            )

        round_json = eligible_by_id.get(round_id)
        if round_json is None:
            if round_id in all_rounds_by_id:
                failures.append(
                    f"round {round_id} (date {entry_date_str}) is not a real one-hop round "
                    f"(kind={all_rounds_by_id[round_id].get('kind')!r}, "
                    f"pool={all_rounds_by_id[round_id].get('pool')!r})"
                )
            else:
                failures.append(
                    f"round {round_id} (date {entry_date_str}) is not in the published pool"
                )
            continue

        expected_fingerprint = round_content_fingerprint(round_json)
        if fingerprint != expected_fingerprint:
            failures.append(
                f"round {round_id} (date {entry_date_str}) fingerprint mismatch: manifest "
                f"has {fingerprint!r}, current content is {expected_fingerprint!r}"
            )

    if failures:
        raise ConnectionDailyManifestError("; ".join(failures))


def schedule_diagnostics(
    manifest: dict[str, Any], rounds_artifact: dict[str, Any]
) -> dict[str, Any]:
    """Honest, non-optimizing diagnostics for a schedule: distinct/repeated
    round counts, endpoint and accepted-performer use frequency, difficulty
    and decade distribution, multi-answer round count, and the longest
    immediate-repeat streak for an endpoint album or accepted performer.
    Never used to gate generation -- purely observational reporting."""
    rounds_by_id = {r["id"]: r for r in rounds_artifact.get("rounds", [])}
    schedule = manifest.get("schedule", [])

    endpoint_uses: dict[str, int] = {}
    performer_uses: dict[int, int] = {}
    difficulty_counts: dict[str, int] = {}
    decade_counts: dict[int, int] = {}
    multi_answer_count = 0
    round_ids = [entry["round_id"] for entry in schedule]

    for round_id in round_ids:
        round_json = rounds_by_id.get(round_id)
        if round_json is None:
            continue
        for endpoint in round_json.get("endpoints", []):
            endpoint_uses[endpoint["id"]] = endpoint_uses.get(endpoint["id"], 0) + 1
            year = endpoint.get("year")
            if year:
                decade = (int(year) // 10) * 10
                decade_counts[decade] = decade_counts.get(decade, 0) + 1
        for answer in round_json.get("answer_set", []):
            performer_uses[answer["id"]] = performer_uses.get(answer["id"], 0) + 1
        difficulty = round_json.get("difficulty", "unknown")
        difficulty_counts[difficulty] = difficulty_counts.get(difficulty, 0) + 1
        if len(round_json.get("answer_set", [])) > 1:
            multi_answer_count += 1

    def _longest_repeat_streak(key_fn: Any) -> int:
        longest = 0
        current = 0
        previous_keys: set[Any] = set()
        for round_id in round_ids:
            round_json = rounds_by_id.get(round_id)
            keys = key_fn(round_json) if round_json else set()
            if keys & previous_keys:
                current += 1
                longest = max(longest, current)
            else:
                current = 0
            previous_keys = keys
        return longest + 1 if longest else (1 if round_ids else 0)

    return {
        "total_dates": len(schedule),
        "distinct_rounds": len(set(round_ids)),
        "repeated_rounds": len(round_ids) - len(set(round_ids)),
        "endpoint_use_counts": dict(sorted(endpoint_uses.items(), key=lambda kv: -kv[1])[:10]),
        "max_endpoint_use": max(endpoint_uses.values(), default=0),
        "performer_use_counts": dict(sorted(performer_uses.items(), key=lambda kv: -kv[1])[:10]),
        "max_performer_use": max(performer_uses.values(), default=0),
        "difficulty_distribution": difficulty_counts,
        "decade_distribution": dict(sorted(decade_counts.items())),
        "multi_answer_round_count": multi_answer_count,
        "longest_adjacent_endpoint_repeat_streak": _longest_repeat_streak(
            lambda r: {e["id"] for e in r.get("endpoints", [])}
        ),
        "longest_adjacent_performer_repeat_streak": _longest_repeat_streak(
            lambda r: {a["id"] for a in r.get("answer_set", [])}
        ),
    }


def schedule_expiry_status(
    manifest: dict[str, Any], *, as_of: str, warn_within_days: int = 14
) -> dict[str, Any]:
    """How much runway is left before the schedule runs out, given an
    explicit `as_of` date -- never the wall clock; callers that want "now"
    pass `datetime.now(UTC).date().isoformat()` themselves, matching this
    module's convention of never reading the clock internally (this
    function's own output is neither committed nor published, so an
    operator-facing default-to-now is fine at the CLI layer, unlike
    `build_connection_daily_manifest`/`extend_connection_daily_manifest`).

    Purely diagnostic reporting, like `schedule_diagnostics` -- never used
    to gate generation or extension, and never a substitute for
    `validate_connection_daily_manifest`/`connection_daily_manifest_failures`
    (a schedule can be perfectly valid and also about to run out). Only
    needs the manifest's own last scheduled date, not the paired rounds
    artifact -- there is nothing here that requires cross-referencing the
    rounds pool."""
    schedule = manifest.get("schedule", [])
    if not schedule:
        raise ConnectionDailyManifestError("schedule must be non-empty")
    last_scheduled_date = _parse_iso_date(schedule[-1]["date"], context="schedule[-1].date")
    as_of_date = _parse_iso_date(as_of, context="as_of")
    days_remaining = (last_scheduled_date - as_of_date).days
    return {
        "last_scheduled_date": schedule[-1]["date"],
        "as_of": as_of,
        "total_dates": len(schedule),
        "days_remaining": days_remaining,
        "warn_within_days": warn_within_days,
        "needs_extension_soon": days_remaining <= warn_within_days,
        "already_expired": days_remaining < 0,
    }
