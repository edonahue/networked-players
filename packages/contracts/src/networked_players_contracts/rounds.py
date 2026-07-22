"""Canonical, dependency-free Record Routes rounds-artifact validation.

Validates ONLY the Record Routes **path** contract (`from_album_id`/
`to_album_id`/`hops`/`from_artist_id`/`to_artist_id` -- album A -> artist X ->
album B via a shared third release), produced by
`packages/graph-core/.../rounds.py`/`rounds_generator.py`. It does NOT
validate the flagship Connection Guesser's `GameUniverse`/`GameRounds` pair
(`endpoints`/`answer_set`/`bridge_answer_sets`/`middle` -- a performer
credited on both displayed albums directly, or bridging a hidden middle
album); that pair has its own dependency-free validator at
`networked_players_contracts.connection_rounds`. Both pairs have historically
been published at the same file names (`universe.v1.json`/`rounds.v1.json`,
in different directories) -- do not assume "rounds.v1" alone identifies which
contract an artifact satisfies (see ADR 0043).

Mirrors `cohort.py`'s structure: pure-Python, no lxml/pyarrow/duckdb, safe to
run on the Pi fleet and in the web build for independent verification of an
already-generated Record Routes `universe.v1.json` / `rounds.v1.json` pair.
Generation-time validation lives in
`packages/graph-core/.../rounds.py::validate_rounds_artifact` -- if the two
disagree, treat it as a bug in whichever is stricter by mistake.
"""

from __future__ import annotations

import json
from typing import Any

ROUNDS_SCHEMA_VERSION = 1

_STRENGTH_FLAGS = frozenset({"co_billed_release_artists", "performer_credit", "non_performer_only"})
_SCOPE_FLAGS = frozenset({"same_recording", "release_scope_credit"})
_DIFFICULTIES = frozenset({"easy", "medium", "hard", "very_hard"})
_KINDS = frozenset({"one_hop", "two_hop"})
_FORBIDDEN_SUBSTRINGS = (
    "/" + "home/",
    "data/" + "private",
    "local" + "/",
    "DISCOGS" + "_TOKEN",
    "." + "ssh",
)
_FORBIDDEN_PHRASES = ("worked with", "collaborated with", "influenced")

_UNIVERSE_TOP_LEVEL_KEYS = frozenset(
    {"schema_version", "pool_version", "provenance", "counts", "albums"}
)
_ROUNDS_TOP_LEVEL_KEYS = frozenset(
    {"schema_version", "pool_version", "provenance", "rounds", "releases", "artists"}
)
_ALBUM_KEYS = frozenset(
    {"id", "master_id", "main_release_id", "title", "artist_id", "artist", "year", "cover_image"}
)
_ROUND_KEYS = frozenset(
    {
        "id",
        "kind",
        "difficulty",
        "from_album_id",
        "to_album_id",
        "from_artist_id",
        "to_artist_id",
        "hops",
        "distractors",
    }
)
_HOP_KEYS = frozenset(
    {"release_id", "artist_a_id", "artist_b_id", "role_a", "role_b", "quality_flags"}
)
_DISTRACTOR_KEYS = frozenset({"album_id", "reason"})


def _hop_failures(hop: Any, *, round_id: Any) -> list[str]:
    if not isinstance(hop, dict):
        return [f"round {round_id} hop must be an object"]
    if set(hop) != _HOP_KEYS:
        return [f"round {round_id} hop has unexpected keys: {sorted(hop)}"]
    failures: list[str] = []
    if not hop.get("role_a") or not hop.get("role_b"):
        failures.append(
            f"round {round_id} hop on release {hop.get('release_id')} is missing role_a/role_b"
        )
    quality_flags = hop.get("quality_flags")
    if not isinstance(quality_flags, list):
        failures.append(f"round {round_id} hop quality_flags must be an array")
        return failures
    strength_flags = [flag for flag in quality_flags if flag in _STRENGTH_FLAGS]
    if len(strength_flags) != 1:
        failures.append(
            f"round {round_id} hop on release {hop.get('release_id')} must have exactly one "
            f"strength flag, got {strength_flags}"
        )
    scope_flags = [flag for flag in quality_flags if flag in _SCOPE_FLAGS]
    if len(scope_flags) != 1:
        failures.append(
            f"round {round_id} hop on release {hop.get('release_id')} must have exactly one "
            f"scope flag, got {scope_flags}"
        )
    return failures


def _seed_key_paths(obj: Any, path: str = "") -> list[str]:
    """Recursively collect dotted paths to any dict key literally named ``seed``.

    Mirrors ``graph-core``'s generation-time ``rounds.py::_find_seed_keys`` so the
    dependency-free validator rejects a leaked pseudo-random seed anywhere in the
    tree, not just at the top level -- the two validators must agree (this closes
    a real gap where the generation-time validator caught nested ``seed`` keys and
    this one did not).
    """
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
    serialized = json.dumps(artifact)
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


def rounds_failures(universe: Any, rounds: Any) -> list[str]:
    """Return every contract failure in a universe.v1/rounds.v1 pair."""
    failures: list[str] = []
    if not isinstance(universe, dict):
        return ["universe artifact must be an object"]
    if not isinstance(rounds, dict):
        return ["rounds artifact must be an object"]

    if set(universe) != _UNIVERSE_TOP_LEVEL_KEYS:
        failures.append(f"universe has unexpected top-level keys: {sorted(universe)}")
    if universe.get("schema_version") != ROUNDS_SCHEMA_VERSION:
        failures.append(f"universe schema_version must be {ROUNDS_SCHEMA_VERSION}")

    if set(rounds) != _ROUNDS_TOP_LEVEL_KEYS:
        failures.append(f"rounds has unexpected top-level keys: {sorted(rounds)}")
    if rounds.get("schema_version") != ROUNDS_SCHEMA_VERSION:
        failures.append(f"rounds schema_version must be {ROUNDS_SCHEMA_VERSION}")
    if universe.get("pool_version") != rounds.get("pool_version"):
        failures.append("universe and rounds pool_version must match")

    album_ids: set[Any] = set()
    albums = universe.get("albums", [])
    if not isinstance(albums, list):
        failures.append("universe.albums must be an array")
        albums = []
    for album in albums:
        if not isinstance(album, dict):
            failures.append("album must be an object")
            continue
        if set(album) != _ALBUM_KEYS:
            failures.append(f"album {album.get('id')} has unexpected keys: {sorted(album)}")
            continue
        album_ids.add(album.get("id"))

    release_ids: set[Any] = {
        release.get("release_id")
        for release in rounds.get("releases", [])
        if isinstance(release, dict)
    }
    artist_ids: set[Any] = {
        artist.get("artist_id") for artist in rounds.get("artists", []) if isinstance(artist, dict)
    }

    round_entries = rounds.get("rounds", [])
    if not isinstance(round_entries, list):
        failures.append("rounds.rounds must be an array")
        round_entries = []
    seen_round_ids: set[Any] = set()
    for round_json in round_entries:
        if not isinstance(round_json, dict):
            failures.append("round must be an object")
            continue
        round_id = round_json.get("id")
        if round_id in seen_round_ids:
            failures.append(f"duplicate round id: {round_id}")
        seen_round_ids.add(round_id)
        if set(round_json) != _ROUND_KEYS:
            failures.append(f"round {round_id} has unexpected keys: {sorted(round_json)}")
            continue
        difficulty = round_json.get("difficulty")
        if difficulty not in _DIFFICULTIES:
            failures.append(f"round {round_id} has invalid difficulty: {difficulty!r}")
        kind = round_json.get("kind")
        hops = round_json.get("hops")
        if kind not in _KINDS:
            failures.append(f"round {round_id} has invalid kind: {kind!r}")
        elif not isinstance(hops, list) or len(hops) != (1 if kind == "one_hop" else 2):
            got = len(hops) if isinstance(hops, list) else hops
            failures.append(
                f"round {round_id} kind={kind!r} must have hops matching its kind, got {got}"
            )
        for album_field in ("from_album_id", "to_album_id"):
            if round_json.get(album_field) not in album_ids:
                failures.append(f"round {round_id} {album_field} references an unpublished album")
        for distractor in round_json.get("distractors", []):
            if not isinstance(distractor, dict) or set(distractor) != _DISTRACTOR_KEYS:
                failures.append(f"round {round_id} distractor has unexpected shape")
            elif distractor.get("album_id") not in album_ids:
                failures.append(f"round {round_id} distractor references an unpublished album")
        if isinstance(hops, list):
            for hop in hops:
                failures.extend(_hop_failures(hop, round_id=round_id))
                if isinstance(hop, dict):
                    if hop.get("release_id") not in release_ids:
                        failures.append(f"round {round_id} hop references an unpublished release")
                    if (
                        hop.get("artist_a_id") not in artist_ids
                        or hop.get("artist_b_id") not in artist_ids
                    ):
                        failures.append(f"round {round_id} hop references an unpublished artist")

    for artifact, name in ((universe, "universe"), (rounds, "rounds")):
        failures.extend(
            f"{name} must not have a 'seed' key ({seed_path})"
            for seed_path in _seed_key_paths(artifact)
        )
        failures.extend(_privacy_failures(artifact, name=name))
    return failures
