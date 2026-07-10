"""Canonical, dependency-free cohort artifact validation."""

from __future__ import annotations

import json
from typing import Any

CONNECTIVITY_SCHEMA_VERSION = 1
PLAYABLE_COHORT_SCHEMA_VERSION = 1

_STRENGTH_FLAGS = frozenset({"co_billed_release_artists", "performer_credit", "non_performer_only"})
_DIFFICULTIES = frozenset({"easy", "medium", "hard", "very_hard"})
_FORBIDDEN_SUBSTRINGS = (
    "/" + "home/",
    "data/" + "private",
    "local" + "/",
    "DISCOGS" + "_TOKEN",
    "." + "ssh",
)

_CONNECTIVITY_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "source",
        "scorer_version",
        "generated_at",
        "dataset_snapshot_date",
        "max_hops",
        "pairs",
        "unresolved",
    }
)
_CONNECTIVITY_OPTIONAL_TOP_LEVEL_KEYS = frozenset({"scoring_params"})
_CONNECTIVITY_PAIR_KEYS = frozenset(
    {
        "album_a_id",
        "album_b_id",
        "artist_a_id",
        "artist_b_id",
        "status",
        "hop_count",
        "difficulty",
        "hops",
        "warnings",
        "skip_reason",
    }
)
_CONNECTIVITY_HOP_KEYS = frozenset({"release_id", "artist_a_id", "artist_b_id", "quality_flags"})
_CONNECTIVITY_STATUSES = frozenset({"found", "no_path", "skipped"})
_CONNECTIVITY_SKIP_REASONS = frozenset(
    {"seed_expansion_timeout", "frontier_too_large", "reach_too_large"}
)

_PLAYABLE_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "cohort_id",
        "attribution_label",
        "source_url",
        "generated_from_scorer_version",
        "reviewed_at",
        "review_note",
        "albums",
        "pairs",
    }
)
_PLAYABLE_ALBUM_KEYS = frozenset({"id", "artist_id", "artist", "title", "year"})
_PLAYABLE_PAIR_KEYS = frozenset(
    {
        "album_a_id",
        "album_b_id",
        "artist_a_id",
        "artist_b_id",
        "difficulty",
        "hop_count",
        "hops",
        "warnings",
    }
)
_PLAYABLE_HOP_KEYS = _CONNECTIVITY_HOP_KEYS
_PLAYABLE_FORBIDDEN_PHRASES = ("worked with", "collaborated with", "influenced")


def _hop_failures(hop: Any) -> list[str]:
    if not isinstance(hop, dict):
        return ["hop must be an object"]
    if set(hop) != _CONNECTIVITY_HOP_KEYS:
        return [f"hop has unexpected keys: {sorted(hop)}"]
    quality_flags = hop.get("quality_flags")
    if not isinstance(quality_flags, list):
        return [f"hop on release {hop.get('release_id')} quality_flags must be an array"]
    strength_flags = [flag for flag in quality_flags if flag in _STRENGTH_FLAGS]
    if len(strength_flags) != 1:
        return [
            f"hop on release {hop.get('release_id')} must have exactly one strength flag, "
            f"got {strength_flags}"
        ]
    return []


def _privacy_failures(artifact: dict[str, Any]) -> list[str]:
    serialized = json.dumps(artifact)
    return [
        f"artifact contains forbidden substring: {forbidden!r}"
        for forbidden in _FORBIDDEN_SUBSTRINGS
        if forbidden in serialized
    ]


def connectivity_failures(artifact: dict[str, Any]) -> list[str]:
    """Return every contract failure in an album-cohort-connectivity-v1 artifact."""
    failures: list[str] = []
    keys = set(artifact)
    allowed = _CONNECTIVITY_TOP_LEVEL_KEYS | _CONNECTIVITY_OPTIONAL_TOP_LEVEL_KEYS
    if not (_CONNECTIVITY_TOP_LEVEL_KEYS <= keys <= allowed):
        failures.append(f"unexpected top-level keys: {sorted(artifact)}")
    if artifact.get("schema_version") != CONNECTIVITY_SCHEMA_VERSION:
        failures.append(f"schema_version must be {CONNECTIVITY_SCHEMA_VERSION}")
    if "scoring_params" in artifact and not isinstance(artifact["scoring_params"], dict):
        failures.append("scoring_params must be an object when present")

    pairs = artifact.get("pairs", [])
    if not isinstance(pairs, list):
        failures.append("pairs must be an array")
        pairs = []
    for pair in pairs:
        if not isinstance(pair, dict):
            failures.append("pair must be an object")
            continue
        if set(pair) != _CONNECTIVITY_PAIR_KEYS:
            failures.append(f"pair has unexpected keys: {sorted(pair)}")
            continue
        status = pair.get("status")
        if status not in _CONNECTIVITY_STATUSES:
            failures.append(f"invalid status: {status!r}")
            continue
        if status == "no_path":
            if pair.get("difficulty") is not None or pair.get("hop_count") is not None:
                failures.append("no_path pair must have null hop_count/difficulty")
            if pair.get("skip_reason") is not None:
                failures.append("no_path pair must have null skip_reason")
        elif status == "skipped":
            if pair.get("difficulty") is not None or pair.get("hop_count") is not None:
                failures.append("skipped pair must have null hop_count/difficulty")
            if pair.get("skip_reason") not in _CONNECTIVITY_SKIP_REASONS:
                failures.append(f"invalid skip_reason: {pair.get('skip_reason')!r}")
        else:
            if pair.get("skip_reason") is not None:
                failures.append("found pair must have null skip_reason")
            if pair.get("difficulty") not in _DIFFICULTIES:
                failures.append(f"invalid difficulty: {pair.get('difficulty')!r}")
            hops = pair.get("hops", [])
            if not isinstance(hops, list):
                failures.append("hops must be an array")
            else:
                for hop in hops:
                    failures.extend(_hop_failures(hop))

    failures.extend(_privacy_failures(artifact))
    return failures


def playable_cohort_failures(artifact: dict[str, Any]) -> list[str]:
    """Return every contract failure in a playable-cohort-v1 artifact."""
    failures: list[str] = []
    if set(artifact) != _PLAYABLE_TOP_LEVEL_KEYS:
        failures.append(f"unexpected top-level keys: {sorted(artifact)}")
    if artifact.get("schema_version") != PLAYABLE_COHORT_SCHEMA_VERSION:
        failures.append(f"schema_version must be {PLAYABLE_COHORT_SCHEMA_VERSION}")

    album_ids: set[Any] = set()
    albums = artifact.get("albums", [])
    if not isinstance(albums, list):
        failures.append("albums must be an array")
        albums = []
    for album in albums:
        if not isinstance(album, dict):
            failures.append("album must be an object")
            continue
        if set(album) != _PLAYABLE_ALBUM_KEYS:
            failures.append(f"album {album.get('id')} has unexpected keys: {sorted(album)}")
            continue
        album_ids.add(album.get("id"))

    pairs = artifact.get("pairs", [])
    if not isinstance(pairs, list):
        failures.append("pairs must be an array")
        pairs = []
    for pair in pairs:
        if not isinstance(pair, dict):
            failures.append("pair must be an object")
            continue
        if set(pair) != _PLAYABLE_PAIR_KEYS:
            failures.append(f"pair has unexpected keys: {sorted(pair)}")
            continue
        if pair.get("album_a_id") not in album_ids or pair.get("album_b_id") not in album_ids:
            failures.append(
                f"pair {pair.get('album_a_id')} <-> {pair.get('album_b_id')} references an "
                "unpublished album"
            )
        if pair.get("difficulty") not in _DIFFICULTIES:
            failures.append(f"invalid difficulty: {pair.get('difficulty')!r}")
        hops = pair.get("hops", [])
        if not isinstance(hops, list):
            failures.append("hops must be an array")
        else:
            for hop in hops:
                failures.extend(_hop_failures(hop))

    failures.extend(_privacy_failures(artifact))
    lowered = json.dumps(artifact).lower()
    failures.extend(
        f"artifact contains forbidden phrase: {phrase!r}"
        for phrase in _PLAYABLE_FORBIDDEN_PHRASES
        if phrase in lowered
    )
    return failures
