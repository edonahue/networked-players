"""Canonical, dependency-free Connection Guesser daily-manifest validation.

Validates the frozen, append-only date -> round schedule for Connection of
the Day (`apps/web/public/data/game/daily-manifest.v1.json`,
`packages/graph-core/.../connection_daily_manifest.py`), scoped specifically
to the flagship Connection Guesser's real one-hop pool (slice 5, ADR 0043's
corrective-slice-4.6/5.1 addenda). This is a near-mechanical port of that
module's `validate_connection_daily_manifest` -- same checks, same failure
wording where practical -- with the raise replaced by a returned failures
list, matching every sibling in this package (`rounds.py`,
`connection_rounds.py`, `album_art.py`, `record_routes.py`).

Mirrors those siblings' structure: pure-Python, no lxml/pyarrow/duckdb, safe
to run on the Pi fleet and in the web build for independent verification of
an already-generated manifest. `round_content_fingerprint` is imported from
`.connection_rounds` rather than reimplemented -- it is a genuinely shared
primitive between the Connection Guesser's rounds contract and this
manifest, not a coincidental duplicate (both must agree on what "the same
round content" means, or a manifest entry could silently drift from its
round without either validator noticing).

What this module deliberately does NOT check:

- That `rounds_artifact` is itself a structurally valid Connection Guesser
  pool. Call `connection_rounds_failures(universe, rounds_artifact)`
  separately for that -- this module only trusts whatever dict it is handed
  to resolve round ids/fingerprints/eligibility against.
- The "no repeat until the eligible pool is exhausted" extension policy.
  That is a property of how `extend_connection_daily_manifest` built the
  schedule, not something derivable by inspecting one already-built
  manifest.
- Days remaining until the schedule runs out. That is an operational
  diagnostic (`schedule_expiry_status`, graph-core), not a pass/fail
  contract question -- a manifest can be perfectly valid and also about to
  need extending.

If this module and its graph-core reference disagree, treat it as a bug in
whichever is stricter by mistake (same rule `connection_rounds.py` states).
"""

from __future__ import annotations

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


def _safe_parse(parser: Any, value: str) -> Any:
    try:
        return parser(value)
    except ValueError:
        return None


def _find_seed_keys(obj: Any, path: str = "") -> list[str]:
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


def _eligible_one_hop_rounds(rounds_artifact: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rounds = rounds_artifact.get("rounds", [])
    if not isinstance(rounds, list):
        return {}
    return {
        r["id"]: r
        for r in rounds
        if isinstance(r, dict)
        and isinstance(r.get("id"), str)
        and r.get("pool") == "real-records"
        and r.get("kind") == "one_hop"
    }


def _all_rounds_by_id(rounds_artifact: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rounds = rounds_artifact.get("rounds", [])
    if not isinstance(rounds, list):
        return {}
    return {r["id"]: r for r in rounds if isinstance(r, dict) and isinstance(r.get("id"), str)}


def _version_mismatches(manifest: dict[str, Any], rounds_artifact: dict[str, Any]) -> list[str]:
    provenance = rounds_artifact.get("provenance", {})
    if not isinstance(provenance, dict):
        provenance = {}
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


def connection_daily_manifest_failures(manifest: Any, rounds_artifact: Any) -> list[str]:
    """Return every contract failure in a Connection Guesser daily manifest,
    checked against its paired rounds artifact."""
    if not isinstance(manifest, dict):
        return ["manifest artifact must be an object"]
    if not isinstance(rounds_artifact, dict):
        return ["rounds artifact must be an object"]

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

    eligible_by_id = _eligible_one_hop_rounds(rounds_artifact)
    all_rounds_by_id = _all_rounds_by_id(rounds_artifact)

    schedule = manifest.get("schedule", [])
    if not isinstance(schedule, list) or not schedule:
        failures.append("schedule must be non-empty")
        schedule = []
    elif (
        isinstance(start_date, str)
        and isinstance(schedule[0], dict)
        and schedule[0].get("date") != start_date
    ):
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

        round_id = entry.get("round_id")
        if not isinstance(round_id, str) or not _ROUND_ID_PATTERN.match(round_id):
            failures.append(
                f"round id {round_id!r} (date {entry_date_str}) is not a stable content-derived id"
            )
        elif round_id in seen_round_ids:
            failures.append(f"round {round_id} is scheduled more than once")
        if isinstance(round_id, str):
            seen_round_ids.add(round_id)

        fingerprint = entry.get("round_fingerprint")
        if not isinstance(fingerprint, str) or not _ROUND_FINGERPRINT_PATTERN.match(fingerprint):
            failures.append(
                f"round_fingerprint {fingerprint!r} (date {entry_date_str}) is not a "
                f"well-formed content fingerprint"
            )

        round_json = eligible_by_id.get(round_id) if isinstance(round_id, str) else None
        if round_json is None:
            if isinstance(round_id, str) and round_id in all_rounds_by_id:
                other = all_rounds_by_id[round_id]
                failures.append(
                    f"round {round_id} (date {entry_date_str}) is not a real one-hop round "
                    f"(kind={other.get('kind')!r}, pool={other.get('pool')!r})"
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

    return failures
