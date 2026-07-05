"""Human-reviewed promotion of local cohort connectivity output into a small,
public playable-cohort artifact. See data/contracts/playable-cohort-v1.md and
docs/decisions/0031-human-reviewed-cohort-promotion.md.

This is the explicit promotion step docs/DATA_AND_RIGHTS.md and
docs/PUBLIC_PRIVATE_BOUNDARY.md already anticipated: nothing in
cohort_source/cohort_resolve/cohort_connectivity ever writes outside
`local/` or `data/private/` -- this module is the only place a curated
cohort's output is ever meant to cross that boundary, and only after an
operator-authored selection file explicitly approves specific pairs.

Deliberately pure Python -- no CreditGraph/DuckDB dependency anywhere in this
module's call graph, the same shape `summarize_connectivity` already
established, since this only reads/writes already-computed JSON.

This module never imports from `networked_players_catalog` (graph-core's
standing rule: catalog -> graph-core only, never the reverse). It does
import a couple of private helpers from `.cohort_connectivity` -- that's a
same-package reach, not a cross-package one, so the no-reverse-dependency
rule doesn't apply.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .cohort_connectivity import _STRENGTH_FLAGS, _album_id

PLAYABLE_COHORT_SCHEMA_VERSION = 1

_TOP_LEVEL_KEYS = frozenset(
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
_ALBUM_KEYS = frozenset({"id", "artist_id", "artist", "title", "year"})
_PAIR_KEYS = frozenset(
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
_HOP_KEYS = frozenset({"release_id", "artist_a_id", "artist_b_id", "quality_flags"})
_DIFFICULTIES = frozenset({"easy", "medium", "hard", "very_hard"})
_FORBIDDEN_SUBSTRINGS = ("/home/", "data/private", "local/", "DISCOGS_TOKEN", ".ssh")
# Extends the existing "connected via a shared release credit" tone rule
# (docs/DATA_AND_RIGHTS.md) to this artifact's free-text review_note field.
_FORBIDDEN_PHRASES = ("worked with", "collaborated with", "influenced")


class CohortPromoteError(RuntimeError):
    """Raised when a cohort can't be promoted, or a promoted artifact violates its contract."""


def validate_selection_file(selection: dict[str, Any]) -> None:
    """Light structural check on the operator-authored, private-only
    selection file -- catches a typo with a clear message rather than a
    confusing downstream KeyError. Not a data/contracts/ schema (it's
    hand-authored, not machine-generated); documented in
    data/contracts/playable-cohort-v1.md's "Promotion inputs" section.
    """
    failures: list[str] = []

    if selection.get("schema_version") != 1:
        failures.append("selection schema_version must be 1")
    if not isinstance(selection.get("allow_flagged_pairs", False), bool):
        failures.append("allow_flagged_pairs must be a boolean")

    approved_pairs = selection.get("approved_pairs")
    if not isinstance(approved_pairs, list):
        failures.append("approved_pairs must be an array")
    else:
        for entry in approved_pairs:
            if not isinstance(entry.get("album_a_id"), str) or not isinstance(
                entry.get("album_b_id"), str
            ):
                failures.append(f"approved_pairs entry missing album_a_id/album_b_id: {entry!r}")
            if "allow_flagged_pairs" in entry and not isinstance(
                entry["allow_flagged_pairs"], bool
            ):
                failures.append(
                    f"approved_pairs entry allow_flagged_pairs must be boolean: {entry!r}"
                )

    if failures:
        raise CohortPromoteError("; ".join(failures))


def _pair_lookup(connectivity: dict[str, Any]) -> dict[frozenset[str], dict[str, Any]]:
    return {
        frozenset({pair["album_a_id"], pair["album_b_id"]}): pair
        for pair in connectivity.get("pairs", [])
    }


def promote_playable_cohort(
    resolved: dict[str, Any],
    connectivity: dict[str, Any],
    selection: dict[str, Any],
    *,
    cohort_id: str,
) -> dict[str, Any]:
    """Promote a human-approved subset of `connectivity["pairs"]` into a
    small, public playable-cohort artifact. Never drops or reinterprets an
    approval silently: an approved pair absent from `connectivity`, not
    `status: "found"`, or flagged without explicit `allow_flagged_pairs`
    always raises `CohortPromoteError` rather than being skipped quietly.
    """
    validate_selection_file(selection)

    if resolved.get("dataset_snapshot_date") != connectivity.get("dataset_snapshot_date"):
        raise CohortPromoteError(
            "resolved.json and connectivity.json disagree on dataset_snapshot_date "
            f"({resolved.get('dataset_snapshot_date')!r} vs "
            f"{connectivity.get('dataset_snapshot_date')!r}) -- refusing to promote from "
            "mismatched pipeline runs"
        )
    resolved_source_url = resolved.get("source", {}).get("source_url")
    connectivity_source_url = connectivity.get("source", {}).get("source_url")
    if resolved_source_url != connectivity_source_url:
        raise CohortPromoteError(
            "resolved.json and connectivity.json disagree on source.source_url -- "
            "refusing to promote from mismatched pipeline runs"
        )

    resolved_by_album_id = {_album_id(album): album for album in resolved.get("resolved", [])}
    pairs_by_key = _pair_lookup(connectivity)
    cohort_allow_flagged = bool(selection.get("allow_flagged_pairs", False))

    promoted_pairs: list[dict[str, Any]] = []
    referenced_album_ids: set[str] = set()

    for approved in selection["approved_pairs"]:
        key = frozenset({approved["album_a_id"], approved["album_b_id"]})
        pair = pairs_by_key.get(key)
        if pair is None:
            raise CohortPromoteError(
                f"approved pair {approved['album_a_id']} <-> {approved['album_b_id']} "
                "was not found in connectivity.json -- check for a typo"
            )
        if pair["status"] != "found":
            raise CohortPromoteError(
                f"approved pair {approved['album_a_id']} <-> {approved['album_b_id']} has "
                f"status={pair['status']!r}, not 'found' -- only a confirmed found path can "
                "be promoted"
            )
        if pair["warnings"] and not (
            cohort_allow_flagged or approved.get("allow_flagged_pairs", False)
        ):
            raise CohortPromoteError(
                f"approved pair {approved['album_a_id']} <-> {approved['album_b_id']} has "
                f"warnings ({pair['warnings']}) and was not explicitly allowed via "
                "allow_flagged_pairs -- set it (cohort-wide or per-pair) to confirm you've "
                "reviewed this connection"
            )

        promoted_pairs.append(
            {
                "album_a_id": pair["album_a_id"],
                "album_b_id": pair["album_b_id"],
                "artist_a_id": pair["artist_a_id"],
                "artist_b_id": pair["artist_b_id"],
                "difficulty": pair["difficulty"],
                "hop_count": pair["hop_count"],
                "hops": pair["hops"],
                "warnings": pair["warnings"],
            }
        )
        referenced_album_ids.add(pair["album_a_id"])
        referenced_album_ids.add(pair["album_b_id"])

    if not promoted_pairs:
        raise CohortPromoteError(
            "no pairs were promoted -- refusing to write an empty playable cohort"
        )

    albums: list[dict[str, Any]] = []
    for album_id in sorted(referenced_album_ids):
        resolved_album = resolved_by_album_id.get(album_id)
        if resolved_album is None:
            raise CohortPromoteError(
                f"promoted pair references album {album_id!r}, which is not in resolved.json"
            )
        albums.append(
            {
                "id": album_id,
                "artist_id": resolved_album["artist_id"],
                "artist": resolved_album["artist_name"],
                "title": resolved_album["title"],
                "year": resolved_album["year"],
            }
        )

    artifact = {
        "schema_version": PLAYABLE_COHORT_SCHEMA_VERSION,
        "cohort_id": cohort_id,
        "attribution_label": resolved.get("source", {}).get("page_title", ""),
        "source_url": resolved_source_url,
        "generated_from_scorer_version": connectivity.get("scorer_version"),
        "reviewed_at": selection.get("reviewed_at"),
        "review_note": selection.get("review_note"),
        "albums": albums,
        "pairs": promoted_pairs,
    }
    validate_playable_cohort(artifact)  # defense in depth, matching sibling modules
    return artifact


def write_playable_cohort(artifact: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")


def validate_playable_cohort(artifact: dict[str, Any]) -> None:
    failures: list[str] = []

    if set(artifact.keys()) != _TOP_LEVEL_KEYS:
        failures.append(f"unexpected top-level keys: {sorted(artifact.keys())}")
    if artifact.get("schema_version") != PLAYABLE_COHORT_SCHEMA_VERSION:
        failures.append(f"schema_version must be {PLAYABLE_COHORT_SCHEMA_VERSION}")

    album_ids: set[Any] = set()
    for album in artifact.get("albums", []):
        if set(album.keys()) != _ALBUM_KEYS:
            failures.append(f"album {album.get('id')} has unexpected keys: {sorted(album.keys())}")
            continue
        album_ids.add(album.get("id"))

    for pair in artifact.get("pairs", []):
        if set(pair.keys()) != _PAIR_KEYS:
            failures.append(f"pair has unexpected keys: {sorted(pair.keys())}")
            continue
        if pair.get("album_a_id") not in album_ids or pair.get("album_b_id") not in album_ids:
            failures.append(
                f"pair {pair.get('album_a_id')} <-> {pair.get('album_b_id')} references an "
                "unpublished album"
            )
        if pair.get("difficulty") not in _DIFFICULTIES:
            failures.append(f"invalid difficulty: {pair.get('difficulty')!r}")
        for hop in pair.get("hops", []):
            if set(hop.keys()) != _HOP_KEYS:
                failures.append(f"hop has unexpected keys: {sorted(hop.keys())}")
                continue
            strength_flags = [f for f in hop["quality_flags"] if f in _STRENGTH_FLAGS]
            if len(strength_flags) != 1:
                failures.append(
                    f"hop on release {hop.get('release_id')} must have exactly one strength "
                    f"flag, got {strength_flags}"
                )

    if failures:
        raise CohortPromoteError("; ".join(failures))

    serialized = json.dumps(artifact)
    for forbidden in _FORBIDDEN_SUBSTRINGS:
        if forbidden in serialized:
            raise CohortPromoteError(f"artifact contains forbidden substring: {forbidden!r}")

    lowered = serialized.lower()
    for phrase in _FORBIDDEN_PHRASES:
        if phrase in lowered:
            raise CohortPromoteError(f"artifact contains forbidden phrase: {phrase!r}")
