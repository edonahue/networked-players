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


# --- Schema v2: multi-generation manifest (Phase 7 catalog expansion) ------
#
# Schema v1 is single-generation by design (see `_version_mismatches`'s own
# docstring: "mixing generations inside one manifest is not supported").
# Phase 7 needs exactly that: the catalog expansion regenerates the whole
# Connection Guesser pool, and every one of the 90 dates already scheduled
# under v1 must remain resolvable to its EXACT original round, forever --
# ADR 0066 records the full design and why it is a bounded, human-authored
# exception to ADR 0041's own revisit trigger, not a general rewrite path.
#
# v2 adds one thing to v1's shape: a `generations[]` list, each entry naming
# one pool generation's `catalog_version`/`pool_version`/`artifact_version`
# and the published rounds file that generation's rounds live in
# (`rounds_url` -- gen-1's frozen copy lives at a *different* URL than the
# live `rounds.v1.json`, which becomes gen-2). Every schedule entry gains a
# `generation` field naming which one it resolves against. `generations` is
# itself append-only: a migration may only ever ADD a new generation, never
# remove or reorder an existing one.
#
# The one deliberate mutation v2 permits on an already-published schedule:
# entries whose `date` is on or after an operator-chosen `cutover_date` may
# be REPLACED (never entries strictly before it). This is safe specifically
# because a date at or after "today" has never had its round content
# revealed -- the manifest schema carries only `date`/`round_id`/
# `round_fingerprint`, never round content, and the archive/game UI never
# renders a future date's round (see `dailyArchive.ts`). Removing an
# unreached, unrevealed future entry changes nothing any visitor has ever
# seen, played, or shared. `migrate_connection_daily_manifest_generation`
# is the one function allowed to do this, and only for dates `>= cutover_date`.

CONNECTION_DAILY_MANIFEST_SCHEMA_VERSION_V2 = 2

# Real timezone spread is ~26 hours (UTC-12 to UTC+14): at any instant,
# player-local calendar dates (apps/web/src/game/localDate.ts's
# localIsoDate, which deliberately never uses UTC) span at most two
# consecutive date labels. A cutover must land at least this many full days
# after generated_at's own UTC date so no player's local calendar could
# already have reached it -- see migrate_connection_daily_manifest_generation.
_MIN_CUTOVER_LEAD_DAYS = 2

_GENERATION_KEYS = frozenset(
    {"generation_id", "catalog_version", "pool_version", "artifact_version", "rounds_url"}
)
_MANIFEST_V2_TOP_LEVEL_KEYS = frozenset(
    {"schema_version", "mode", "generated_at", "start_date", "generations", "schedule"}
)
_SCHEDULE_ENTRY_V2_KEYS = frozenset({"date", "round_id", "round_fingerprint", "generation"})


def upgrade_connection_daily_manifest_to_v2(
    manifest: dict[str, Any], *, generation_id: str, rounds_url: str
) -> dict[str, Any]:
    """Pure structural upgrade of an already-valid schema-v1 manifest to v2
    -- ZERO content change. Every existing schedule entry keeps its exact
    `date`/`round_id`/`round_fingerprint` and gains only a `generation`
    field naming `generation_id`; the v1 manifest's own `catalog_version`/
    `pool_version`/`artifact_version` become `generations[0]`, paired with
    `rounds_url` (where that generation's rounds now live -- the real
    migration runbook copies the current `rounds.v1.json` there BYTE-
    IDENTICALLY before calling this, so `rounds_url` names real, already-
    frozen content, not a promise).

    This function does not add a second generation and does not touch the
    cutover-date logic at all -- it only proves the v1 -> v2 SHAPE change is
    itself lossless. See `migrate_connection_daily_manifest_generation` for
    actually introducing a new generation.
    """
    if manifest.get("schema_version") != CONNECTION_DAILY_MANIFEST_SCHEMA_VERSION:
        raise ConnectionDailyManifestError(
            f"upgrade_connection_daily_manifest_to_v2 expects a schema_version="
            f"{CONNECTION_DAILY_MANIFEST_SCHEMA_VERSION} input, got "
            f"{manifest.get('schema_version')!r}"
        )
    generation = {
        "generation_id": generation_id,
        "catalog_version": manifest["catalog_version"],
        "pool_version": manifest["pool_version"],
        "artifact_version": manifest["artifact_version"],
        "rounds_url": rounds_url,
    }
    schedule_v2 = [{**entry, "generation": generation_id} for entry in manifest["schedule"]]
    return {
        "schema_version": CONNECTION_DAILY_MANIFEST_SCHEMA_VERSION_V2,
        "mode": manifest["mode"],
        "generated_at": manifest["generated_at"],
        "start_date": manifest["start_date"],
        "generations": [generation],
        "schedule": schedule_v2,
    }


def migrate_connection_daily_manifest_generation(
    manifest: dict[str, Any],
    new_rounds_artifact: dict[str, Any],
    *,
    cutover_date: str,
    new_generation_id: str,
    new_rounds_url: str,
    days: int,
    generated_at: str,
    existing_generation_rounds: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Introduce a new pool generation, effective `cutover_date` onward.

    Every entry with `date < cutover_date` is preserved EXACTLY --
    unchanged `date`/`round_id`/`round_fingerprint`/`generation`, same
    relative order. Every entry with `date >= cutover_date` is DROPPED and
    replaced by newly-scheduled entries drawn from `new_rounds_artifact`.
    This is the one sanctioned mutation of an already-published schedule
    (see the module-level note above for why it is safe); this function
    refuses to run at all if `cutover_date` is less than
    `_MIN_CUTOVER_LEAD_DAYS` (2) full days after `generated_at`'s own date.
    A plain "strictly after" (1-day) margin is not enough: Connection of the
    Day rolls over at each PLAYER'S OWN local midnight
    (`apps/web/src/game/localDate.ts`), not UTC midnight, so a player in a
    timezone far enough ahead of UTC could already be on a later local date
    than `generated_at`'s own UTC date. Requiring two full days closes that
    gap, so this can never be used to rewrite a date that might already have
    been reached by any player, anywhere.

    `existing_generation_rounds` must map every generation_id referenced by
    a KEPT entry to that generation's own rounds artifact, so every kept
    entry's `round_fingerprint` can be re-verified before anything is
    written -- exactly the same paranoia `extend_connection_daily_manifest`
    already applies within one generation, extended across generations
    here. A missing mapping or a fingerprint mismatch raises rather than
    migrating on top of a silently-corrupted history.

    `generations` gains exactly one new entry; no existing entry in it is
    ever modified. New dates are drawn only from `new_rounds_artifact`'s
    eligible one-hop rounds, ordered with the last KEPT round as adjacency
    context (or `None` if the cutover empties the schedule entirely).
    """
    if manifest.get("schema_version") != CONNECTION_DAILY_MANIFEST_SCHEMA_VERSION_V2:
        raise ConnectionDailyManifestError(
            "migrate_connection_daily_manifest_generation requires a schema_version="
            f"{CONNECTION_DAILY_MANIFEST_SCHEMA_VERSION_V2} manifest, got "
            f"{manifest.get('schema_version')!r} -- upgrade it first"
        )
    if days <= 0:
        raise ValueError("days must be positive")

    generated_at_dt = _parse_iso_datetime(generated_at, context="generated_at")
    cutover = _parse_iso_date(cutover_date, context="cutover_date")
    # `apps/web/src/game/localDate.ts` deliberately rolls a date over at each
    # PLAYER'S OWN local midnight, not UTC midnight -- a real player's local
    # calendar date can already be one day ahead of generated_at's own UTC
    # date at the instant this function runs (the real timezone spread is
    # ~26 hours, UTC-12 to UTC+14, so at any instant player-local dates span
    # at most two consecutive calendar-date labels). Requiring only "the day
    # after generated_at" would let a cutover target a date some player's
    # browser has ALREADY reached -- exactly the "already reached or passed"
    # case this check exists to refuse, just missed by one day. Requiring
    # two full days closes that gap: no player's local calendar can reach
    # `generated_at.date() + 2` before a full day has passed in every
    # timezone following the furthest-ahead one.
    earliest_safe_cutover = generated_at_dt.date() + timedelta(days=_MIN_CUTOVER_LEAD_DAYS)
    if cutover < earliest_safe_cutover:
        raise ConnectionDailyManifestError(
            f"cutover_date {cutover_date!r} is too soon after generated_at "
            f"({generated_at_dt.date().isoformat()}) -- the earliest safe cutover is "
            f"{earliest_safe_cutover.isoformat()} ({_MIN_CUTOVER_LEAD_DAYS} full days out). "
            "Connection of the Day rolls over at each PLAYER'S OWN local midnight "
            "(apps/web/src/game/localDate.ts), not UTC midnight, so a player in a "
            "timezone far ahead of UTC could already be on a later local date than "
            "generated_at's own date -- a cutover may only ever remove schedule entries "
            "that no player's local calendar could possibly have reached yet"
        )

    existing_generation_ids = {g["generation_id"] for g in manifest["generations"]}
    if new_generation_id in existing_generation_ids:
        raise ConnectionDailyManifestError(
            f"generation_id {new_generation_id!r} already exists in this manifest -- "
            "generations are append-only and never reused"
        )

    schedule = manifest["schedule"]
    kept = [e for e in schedule if e["date"] < cutover_date]

    if kept:
        expected_cutover = (
            _parse_iso_date(kept[-1]["date"], context="kept[-1].date") + timedelta(days=1)
        ).isoformat()
        if cutover_date != expected_cutover:
            raise ConnectionDailyManifestError(
                f"cutover_date {cutover_date!r} would leave a gap or overlap after the last "
                f"kept date {kept[-1]['date']!r} -- expected {expected_cutover!r}. The "
                "published schedule must stay contiguous; if a deliberate gap is ever "
                "wanted, that is a bigger product decision than this function is allowed "
                "to make silently."
            )

    # Re-verify every KEPT entry against its own generation's rounds
    # artifact before writing anything -- a kept entry whose round silently
    # changed, or whose named generation isn't provided, aborts the whole
    # migration rather than producing a manifest with an unverifiable past.
    for entry in kept:
        generation_id = entry["generation"]
        rounds_for_generation = existing_generation_rounds.get(generation_id)
        if rounds_for_generation is None:
            raise ConnectionDailyManifestError(
                f"kept entry for {entry['date']} references generation {generation_id!r}, "
                "but no rounds artifact was supplied for it in existing_generation_rounds "
                "-- refusing to migrate without being able to verify every kept entry"
            )
        all_rounds_by_id = {r["id"]: r for r in rounds_for_generation.get("rounds", [])}
        round_json = all_rounds_by_id.get(entry["round_id"])
        if round_json is None:
            raise ConnectionDailyManifestError(
                f"kept entry for {entry['date']} references round {entry['round_id']!r}, "
                f"which is missing from generation {generation_id!r}'s rounds artifact -- "
                "refusing to migrate on top of a broken history"
            )
        current_fingerprint = round_content_fingerprint(round_json)
        if current_fingerprint != entry["round_fingerprint"]:
            raise ConnectionDailyManifestError(
                f"kept entry for {entry['date']} (round {entry['round_id']}, generation "
                f"{generation_id!r}) has a content fingerprint mismatch: manifest expects "
                f"{entry['round_fingerprint']!r}, current artifact has "
                f"{current_fingerprint!r} -- the round's published content changed "
                "silently, refusing to migrate on top of a broken history"
            )

    eligible = _eligible_one_hop_rounds(new_rounds_artifact)
    # Round ids are CONTENT-derived, so a regenerated pool legitimately
    # contains rounds byte-identical to ones the kept (older-generation)
    # schedule already uses -- same album pair, same answer set, same id.
    # Scheduling such a round again under the new generation would put one
    # id on two dates under two different generations, which
    # `validate_connection_daily_manifest_v2` rejects (it makes `generation`
    # an ambiguous lookup key for that id) and which would also repeat a
    # round a visitor has already played. Mirrors ADR 0041's rule for
    # `extend_connection_daily_manifest`: draw only from rounds not already
    # scheduled anywhere in the manifest.
    kept_round_ids = {entry["round_id"] for entry in kept}
    eligible = [r for r in eligible if r["id"] not in kept_round_ids]
    if not eligible:
        raise ConnectionDailyManifestError(
            "no eligible one-hop real-records rounds found in new_rounds_artifact "
            "that are not already scheduled under a kept generation"
        )
    provenance = new_rounds_artifact.get("provenance", {})
    for field_name in _VERSION_FIELDS:
        if not provenance.get(field_name):
            raise ConnectionDailyManifestError(
                f"new_rounds_artifact provenance.{field_name} is required and must be non-empty"
            )

    last_kept_round_json = None
    if kept:
        last_kept_generation_id = kept[-1]["generation"]
        last_kept_rounds = existing_generation_rounds[last_kept_generation_id]
        last_kept_round_json = {r["id"]: r for r in last_kept_rounds.get("rounds", [])}.get(
            kept[-1]["round_id"]
        )

    ordered = _quality_scheduled_order(
        eligible, seed=str(provenance.get("pool_version")), previous_round=last_kept_round_json
    )
    scheduled_count = min(days, len(ordered))
    new_dates = _dates_from(cutover_date, scheduled_count)
    new_entries = [
        {
            "date": d,
            "round_id": r["id"],
            "round_fingerprint": round_content_fingerprint(r),
            "generation": new_generation_id,
        }
        for d, r in zip(new_dates, ordered[:scheduled_count], strict=True)
    ]

    new_generation = {
        "generation_id": new_generation_id,
        "catalog_version": provenance["catalog_version"],
        "pool_version": provenance["pool_version"],
        "artifact_version": provenance["artifact_version"],
        "rounds_url": new_rounds_url,
    }

    return {
        "schema_version": CONNECTION_DAILY_MANIFEST_SCHEMA_VERSION_V2,
        "mode": manifest["mode"],
        "generated_at": generated_at,
        "start_date": manifest["start_date"],
        "generations": [*manifest["generations"], new_generation],
        "schedule": [*kept, *new_entries],
    }


def validate_connection_daily_manifest_v2(
    manifest: dict[str, Any], rounds_by_generation: dict[str, dict[str, Any]]
) -> None:
    """Structural, referential, and content-integrity validation for a
    schema-v2 manifest. `rounds_by_generation` must map every
    `generation_id` named in `manifest["generations"]` to that generation's
    real rounds artifact (gen-1's frozen copy, gen-2's live `rounds.v1.json`,
    ...) -- every schedule entry's fingerprint is re-verified against its
    OWN named generation, never any other one.

    Beyond v1's checks (contiguous/unique dates, well-formed ids/
    fingerprints, real one-hop rounds, fresh fingerprint recomputation):
    round ids must be unique ACROSS every generation combined (the same
    content-derived id appearing under two generations would make
    `generation` ambiguous for that id), every entry's `generation` must
    name a real entry in `generations[]`, and `generations[]` itself must
    have unique, non-empty `generation_id`s with the exact documented key
    set.
    """
    failures: list[str] = [
        f"manifest must not have a 'seed' key ({p})" for p in _find_seed_keys(manifest)
    ]
    failures.extend(_privacy_failures(manifest))

    if set(manifest.keys()) != _MANIFEST_V2_TOP_LEVEL_KEYS:
        failures.append(f"manifest has unexpected top-level keys: {sorted(manifest.keys())}")
    if manifest.get("schema_version") != CONNECTION_DAILY_MANIFEST_SCHEMA_VERSION_V2:
        failures.append(f"schema_version must be {CONNECTION_DAILY_MANIFEST_SCHEMA_VERSION_V2}")
    if manifest.get("mode") != CONNECTION_DAILY_MANIFEST_MODE:
        failures.append(f"mode must be {CONNECTION_DAILY_MANIFEST_MODE!r}")

    generated_at = manifest.get("generated_at")
    if not generated_at or _safe_parse(datetime.fromisoformat, generated_at) is None:
        failures.append(f"generated_at {generated_at!r} is not a valid ISO datetime")

    start_date = manifest.get("start_date")
    if not start_date or _safe_parse(date.fromisoformat, start_date) is None:
        failures.append(f"start_date {start_date!r} is not a valid ISO date")

    generations = manifest.get("generations")
    generation_ids: set[str] = set()
    if not isinstance(generations, list) or not generations:
        failures.append("generations must be a non-empty array")
        generations = []
    for generation in generations:
        if not isinstance(generation, dict) or set(generation.keys()) != _GENERATION_KEYS:
            failures.append(f"generation entry has unexpected shape: {generation!r}")
            continue
        generation_id = generation.get("generation_id")
        if not generation_id or not isinstance(generation_id, str):
            failures.append(f"generation_id {generation_id!r} must be a non-empty string")
            continue
        if generation_id in generation_ids:
            failures.append(f"duplicate generation_id: {generation_id}")
        generation_ids.add(generation_id)
        for field_name in _VERSION_FIELDS:
            if not generation.get(field_name):
                failures.append(f"generation {generation_id} is missing {field_name}")
        if not generation.get("rounds_url"):
            failures.append(f"generation {generation_id} is missing rounds_url")
        # A generation entry's version fields are the manifest's own claim
        # about which frozen artifact a generation resolves against; without
        # comparing them to the SUPPLIED artifact's own provenance, a
        # hand-edited generation entry (or a validator call given the wrong
        # rounds artifact for that generation_id) would pass this loop's
        # non-emptiness checks while naming a different frozen generation
        # than the one actually being verified -- exactly schema v1's
        # `_version_mismatches` guarantee, extended per-generation here.
        rounds_artifact_for_generation = rounds_by_generation.get(generation_id)
        if rounds_artifact_for_generation is not None:
            generation_provenance = rounds_artifact_for_generation.get("provenance", {})
            for field_name in _VERSION_FIELDS:
                manifest_value = generation.get(field_name)
                artifact_value = generation_provenance.get(field_name)
                if manifest_value and artifact_value and manifest_value != artifact_value:
                    failures.append(
                        f"generation {generation_id} {field_name} {manifest_value!r} does not "
                        f"match the supplied rounds artifact's provenance.{field_name} "
                        f"{artifact_value!r} -- this manifest identifies a different frozen "
                        "generation than the artifact used to verify it"
                    )

    schedule = manifest.get("schedule")
    if not isinstance(schedule, list) or not schedule:
        failures.append("schedule must be non-empty")
        schedule = []
    elif isinstance(start_date, str) and schedule[0].get("date") != start_date:
        failures.append(
            f"start_date {start_date!r} does not match schedule[0].date {schedule[0].get('date')!r}"
        )

    seen_dates: set[str] = set()
    seen_round_ids: set[str] = set()
    previous_date: date | None = None
    for entry in schedule:
        if not isinstance(entry, dict) or set(entry.keys()) != _SCHEDULE_ENTRY_V2_KEYS:
            failures.append(f"schedule entry has unexpected shape: {entry!r}")
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

        round_id = entry.get("round_id")
        if not isinstance(round_id, str) or not _ROUND_ID_PATTERN.match(round_id):
            failures.append(
                f"round id {round_id!r} (date {entry_date_str}) is not a stable content-derived id"
            )
        elif round_id in seen_round_ids:
            failures.append(f"round {round_id} is scheduled more than once across generations")
        if isinstance(round_id, str):
            seen_round_ids.add(round_id)

        fingerprint = entry.get("round_fingerprint")
        if not isinstance(fingerprint, str) or not _ROUND_FINGERPRINT_PATTERN.match(fingerprint):
            failures.append(
                f"round_fingerprint {fingerprint!r} (date {entry_date_str}) is not a "
                "well-formed content fingerprint"
            )

        generation_id = entry.get("generation")
        if generation_id not in generation_ids:
            failures.append(
                f"schedule entry for {entry_date_str} names generation {generation_id!r}, "
                "which is not in this manifest's generations[]"
            )
            continue

        rounds_artifact = rounds_by_generation.get(generation_id)
        if rounds_artifact is None:
            failures.append(
                f"no rounds artifact supplied for generation {generation_id!r} "
                f"(needed to verify the entry for {entry_date_str})"
            )
            continue

        eligible_by_id = {r["id"]: r for r in _eligible_one_hop_rounds(rounds_artifact)}
        all_rounds_by_id = {r["id"]: r for r in rounds_artifact.get("rounds", [])}
        round_json = eligible_by_id.get(round_id) if isinstance(round_id, str) else None
        if round_json is None:
            if isinstance(round_id, str) and round_id in all_rounds_by_id:
                other = all_rounds_by_id[round_id]
                failures.append(
                    f"round {round_id} (date {entry_date_str}, generation {generation_id}) "
                    f"is not a real one-hop round (kind={other.get('kind')!r}, "
                    f"pool={other.get('pool')!r})"
                )
            else:
                failures.append(
                    f"round {round_id} (date {entry_date_str}, generation {generation_id}) "
                    "is not in the published pool for that generation"
                )
            continue

        expected_fingerprint = round_content_fingerprint(round_json)
        if fingerprint != expected_fingerprint:
            failures.append(
                f"round {round_id} (date {entry_date_str}, generation {generation_id}) "
                f"fingerprint mismatch: manifest has {fingerprint!r}, current content is "
                f"{expected_fingerprint!r}"
            )

    if failures:
        raise ConnectionDailyManifestError("; ".join(failures))
