"""Canonical, dependency-free Connection Guesser rounds-artifact validation.

Validates the flagship Connection Guesser's real `GameUniverse`/`GameRounds`
pair (`apps/web/public/data/game/universe.v1.json` /
`apps/web/public/data/game/rounds.v1.json`, `apps/web/src/game/types.ts`): a
one-hop round's answer is a performer explicitly credited on BOTH displayed
albums directly (`endpoints`/`answer_set`), a two-hop round hides a middle
album bridged by two independently-guessed performer sets
(`middle`/`bridge_answer_sets`). This is a genuinely different contract from
`networked_players_contracts.rounds`'s Record Routes **path** semantic
(`from_album_id`/`to_album_id`/`hops`) -- see that module's docstring. Both
pairs have historically been published at the same file names in different
directories; do not assume "rounds.v1" alone identifies which contract
applies (see ADR 0043).

Mirrors `cohort.py`'s/`rounds.py`'s structure: pure-Python, no
lxml/pyarrow/duckdb, safe to run on the Pi fleet and in the web build for
independent verification of an already-generated pair. Generation-time
validation lives in
`packages/graph-core/.../connection_rounds.py::validate_connection_rounds_artifact`
-- if the two disagree, treat it as a bug in whichever is stricter by
mistake.
"""

from __future__ import annotations

import re
from typing import Any

CONNECTION_ROUNDS_SCHEMA_VERSION = 1

_ROUND_ID_PATTERN = re.compile(r"^conn-[0-9a-f]{10}$")
_KINDS = frozenset({"one_hop", "two_hop"})
_DIFFICULTIES = frozenset({"easy", "medium", "hard"})
_FORBIDDEN_SUBSTRINGS = (
    "/" + "home/",
    "data/" + "private",
    "local" + "/",
    "DISCOGS" + "_TOKEN",
    "." + "ssh",
)
_FORBIDDEN_PHRASES = ("worked with", "collaborated with", "influenced")
_PROVENANCE_REQUIRED_FIELDS = (
    "source",
    "license",
    "snapshot_date",
    "generated_by",
    "note",
    "catalog_version",
    "pool_version",
)


def _seed_key_paths(obj: Any, path: str = "") -> list[str]:
    """Recursively collect dotted paths to any dict key literally named
    ``seed`` -- must agree with graph-core's generation-time mirror
    (`connection_rounds.py::_find_seed_keys`)."""
    found: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            child = f"{path}.{key}" if path else str(key)
            if key == "seed":
                found.append(child)
            found.extend(_seed_key_paths(value, child))
    elif isinstance(obj, list):
        for index, item in enumerate(obj):
            found.extend(_seed_key_paths(item, f"{path}[{index}]"))
    return found


def _privacy_failures(artifact: dict[str, Any], *, name: str) -> list[str]:
    serialized = str(artifact)
    failures = [
        f"{name} contains forbidden substring: {forbidden!r}"
        for forbidden in _FORBIDDEN_SUBSTRINGS
        if forbidden in serialized
    ]
    lowered = serialized.lower()
    failures.extend(
        f"{name} contains forbidden phrase: {phrase!r}"
        for phrase in _FORBIDDEN_PHRASES
        if phrase in lowered
    )
    return failures


def connection_rounds_failures(universe: Any, rounds: Any) -> list[str]:
    """Return every contract failure in a Connection Guesser universe.v1/
    rounds.v1 pair."""
    failures: list[str] = []
    if not isinstance(universe, dict):
        return ["universe artifact must be an object"]
    if not isinstance(rounds, dict):
        return ["rounds artifact must be an object"]

    if universe.get("schema_version") != CONNECTION_ROUNDS_SCHEMA_VERSION:
        failures.append(f"universe schema_version must be {CONNECTION_ROUNDS_SCHEMA_VERSION}")
    if rounds.get("schema_version") != CONNECTION_ROUNDS_SCHEMA_VERSION:
        failures.append(f"rounds schema_version must be {CONNECTION_ROUNDS_SCHEMA_VERSION}")
    if universe.get("provenance") != rounds.get("provenance"):
        failures.append("universe and rounds provenance must match exactly")

    album_ids: set[Any] = {a.get("id") for a in universe.get("albums", []) if isinstance(a, dict)}
    contributor_ids: set[Any] = {
        c.get("id") for c in universe.get("contributors", []) if isinstance(c, dict)
    }
    release_ids: set[Any] = {
        r.get("id") for r in universe.get("releases", []) if isinstance(r, dict)
    }

    round_entries = rounds.get("rounds", [])
    if not isinstance(round_entries, list):
        return ["rounds.rounds must be an array"]

    seen_round_ids: set[Any] = set()
    for round_json in round_entries:
        if not isinstance(round_json, dict):
            failures.append("round must be an object")
            continue
        round_id = round_json.get("id")
        if round_id in seen_round_ids:
            failures.append(f"duplicate round id: {round_id}")
        seen_round_ids.add(round_id)
        if not isinstance(round_id, str) or not _ROUND_ID_PATTERN.match(round_id):
            failures.append(f"round id {round_id!r} is not a stable content-derived id")
        if round_json.get("pool") != "real-records":
            failures.append(f"round {round_id} pool must be 'real-records'")
        kind = round_json.get("kind")
        if kind not in _KINDS:
            failures.append(f"round {round_id} has invalid kind: {kind!r}")
        if round_json.get("difficulty") not in _DIFFICULTIES:
            failures.append(f"round {round_id} has invalid difficulty")

        answer_set = round_json.get("answer_set", [])
        if kind == "one_hop" and not answer_set:
            failures.append(f"round {round_id} has an empty answer set")
        answer_ids = {a.get("id") for a in answer_set if isinstance(a, dict)}
        bridges = round_json.get("bridge_answer_sets") or []
        bridge_ids: set[Any] = {
            a.get("id") for group in bridges for a in group if isinstance(a, dict)
        }
        all_valid_ids = answer_ids | bridge_ids

        evidence = round_json.get("evidence", [])
        if not evidence:
            failures.append(f"round {round_id} has no evidence rows")
        evidence_ids = {row.get("contributor_id") for row in evidence if isinstance(row, dict)}
        for aid in all_valid_ids:
            if aid not in evidence_ids:
                failures.append(f"round {round_id} answer {aid} lacks evidence")

        for distractor in round_json.get("distractors", []):
            if not isinstance(distractor, dict):
                continue
            if distractor.get("id") in all_valid_ids:
                failures.append(f"round {round_id} distractor {distractor.get('id')} is an answer")
            if distractor.get("id") not in contributor_ids:
                failures.append(
                    f"round {round_id} distractor {distractor.get('id')} not in universe"
                )

        for clue in round_json.get("clues", []):
            if isinstance(clue, dict) and clue.get("kind") == "eliminate":
                for eliminated_id in clue.get("eliminate_ids") or []:
                    if eliminated_id in all_valid_ids:
                        failures.append(
                            f"round {round_id} eliminate clue targets valid answer {eliminated_id}"
                        )

        for endpoint in round_json.get("endpoints", []):
            if not isinstance(endpoint, dict) or endpoint.get("id") not in album_ids:
                failures.append(f"round {round_id} endpoint not in universe")

        if kind == "two_hop":
            middle = round_json.get("middle")
            if not middle or not bridges or len(bridges) != 2:
                failures.append(f"two-hop round {round_id} missing middle/bridge_answer_sets")
            else:
                choices = middle.get("choices", [])
                middle_album_id = middle.get("album", {}).get("id")
                if not any(c.get("id") == middle_album_id for c in choices):
                    failures.append(f"round {round_id} middle answer missing from its own choices")
                if not bridges[0] or not bridges[1]:
                    failures.append(f"round {round_id} needs at least one bridge answer per side")

    for artifact, name in ((universe, "universe"), (rounds, "rounds")):
        failures.extend(
            f"{name} must not have a 'seed' key ({seed_path})"
            for seed_path in _seed_key_paths(artifact)
        )
        failures.extend(_privacy_failures(artifact, name=name))

    for field_name in _PROVENANCE_REQUIRED_FIELDS:
        if not universe.get("provenance", {}).get(field_name):
            failures.append(f"universe.provenance.{field_name} is required")
    source = str(universe.get("provenance", {}).get("source", "")).lower()
    generated_by = str(universe.get("provenance", {}).get("generated_by", "")).lower()
    if "discogs" not in source:
        failures.append("universe provenance.source does not identify a real Discogs source")
    if "synthetic" in generated_by or "ci placeholder" in generated_by:
        failures.append("universe provenance.generated_by marks this as a synthetic fixture")

    for credit in universe.get("credits", []):
        if not isinstance(credit, dict):
            continue
        if credit.get("contributor_id") not in contributor_ids:
            failures.append(f"credit references unknown contributor {credit.get('contributor_id')}")
        if credit.get("release_id") not in release_ids:
            failures.append(f"credit references unknown release {credit.get('release_id')}")

    return failures
