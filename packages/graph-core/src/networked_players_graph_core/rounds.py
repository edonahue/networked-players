"""Build a rounds.v1/universe.v1 artifact pair: the flagship game's static,
performer-only evidence pool derived from a real one-hop credit graph.

Mirrors `challenge.py`'s album-centered, evidence-preserving shape and its
leak-scanning posture, but adds one further gate `challenge.py` does not
apply: every hop must independently satisfy `eligibility.py::is_performer_role`
-- an explicit, displayable instrument/vocal role text on both sides, not
just any collaborative credit. A path that is valid evidence for the album
browser (`challenge.v2.json`) may still be rejected here if its only
connecting credit is non-performer (e.g. a shared producer).

This module builds evidence for a *single* round from an already-found
`EvidencePath` (see `graph.py::CreditGraph.find_path`); candidate discovery,
scoring, and diversified pool selection across many candidate pairs is the
game-rounds generator's job (`build-rounds-from-dump`), not this module's.
"""

from __future__ import annotations

import json
from typing import Any

from .cohort_connectivity import classify_hop_quality
from .eligibility import is_performer_role
from .graph import CreditGraph, EvidencePath, Hop

ROUNDS_SCHEMA_VERSION = 1

# Duplicated from challenge.py rather than imported, matching this codebase's
# existing convention (see cohort_resolve.py) of a small, self-contained
# constant per artifact-building module rather than cross-module private
# imports between sibling (non-graph.py) modules.
_FORBIDDEN_SUBSTRINGS = ("/home/", "data/private", "local/", "DISCOGS_TOKEN", ".ssh")
_FORBIDDEN_PHRASES = ("worked with", "collaborated with", "influenced")

_DIFFICULTIES = frozenset({"easy", "medium", "hard", "very_hard"})
_HOP_KEYS = frozenset(
    {"release_id", "artist_a_id", "artist_b_id", "role_a", "role_b", "quality_flags"}
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
_DISTRACTOR_KEYS = frozenset({"album_id", "reason"})
_UNIVERSE_TOP_LEVEL_KEYS = frozenset(
    {"schema_version", "pool_version", "provenance", "counts", "albums"}
)
_ROUNDS_TOP_LEVEL_KEYS = frozenset(
    {"schema_version", "pool_version", "provenance", "rounds", "releases", "artists"}
)
# Same shape as challenge.py's `_RELEASE_KEYS`: the release-table fields per
# data/contracts/discogs-release-v2.md (minus `images`) plus the `credits`
# evidence array this builder adds.
_RELEASE_KEYS = frozenset(
    {
        "snapshot_date",
        "release_id",
        "status",
        "title",
        "country",
        "released",
        "master_id",
        "master_is_main_release",
        "data_quality",
        "source_url",
        "credits",
    }
)


class RoundsValidationError(RuntimeError):
    """Raised when a rounds/universe artifact pair violates its contract."""


def _find_seed_keys(obj: Any, path: str = "") -> list[str]:
    """Recursively collect dotted paths to any dict key literally named `seed`."""
    found: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            child_path = f"{path}.{key}" if path else str(key)
            if key == "seed":
                found.append(child_path)
            found.extend(_find_seed_keys(value, child_path))
    elif isinstance(obj, list):
        for index, item in enumerate(obj):
            found.extend(_find_seed_keys(item, f"{path}[{index}]"))
    return found


def _first_performer_role(rows: list[dict[str, Any]]) -> str | None:
    """The first credit row's `role_text` that satisfies `is_performer_role`,
    or None if this artist has no eligible role on this release. Rows are
    already deterministically ordered by `CreditGraph.credit_rows`."""
    for row in rows:
        role_text = row.get("role_text")
        if is_performer_role(role_text):
            return role_text
    return None


def build_round_hop(graph: CreditGraph, hop: Hop) -> dict[str, Any] | None:
    """Build one hop's game-round evidence, or None if either side lacks an
    explicit, eligible instrument/vocal role text on this release -- the
    layered allowlist gate described in the module docstring."""
    rows = graph.credit_rows(hop.release_id, {hop.artist_a_id, hop.artist_b_id})
    rows_a = [row for row in rows if row["artist_id"] == hop.artist_a_id]
    rows_b = [row for row in rows if row["artist_id"] == hop.artist_b_id]
    role_a = _first_performer_role(rows_a)
    role_b = _first_performer_role(rows_b)
    if role_a is None or role_b is None:
        return None
    quality_flags = classify_hop_quality(
        rows_a, rows_b, artist_a_id=hop.artist_a_id, artist_b_id=hop.artist_b_id
    )
    return {
        "release_id": hop.release_id,
        "artist_a_id": hop.artist_a_id,
        "artist_b_id": hop.artist_b_id,
        "role_a": role_a,
        "role_b": role_b,
        "quality_flags": quality_flags,
    }


def _difficulty_for_round(hop_count: int, hops_json: list[dict[str, Any]]) -> str:
    if hop_count == 1:
        strength = hops_json[0]["quality_flags"]
        return "easy" if "co_billed_release_artists" in strength else "medium"
    if hop_count == 2:
        return "hard"
    return "very_hard"


def build_round_from_path(
    graph: CreditGraph,
    path: EvidencePath,
    *,
    round_id: str,
    from_album_id: str,
    to_album_id: str,
    distractors: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Build a full round from an already-found path, or None if any hop
    fails the performer-eligibility gate -- the whole path is dropped for
    game purposes, even though it might remain valid album/cohort evidence."""
    if len(path.hops) not in (1, 2):
        raise ValueError(f"rounds only support 1- or 2-hop paths, got {len(path.hops)}")

    hops_json: list[dict[str, Any]] = []
    for hop in path.hops:
        built = build_round_hop(graph, hop)
        if built is None:
            return None
        hops_json.append(built)

    kind = "one_hop" if len(path.hops) == 1 else "two_hop"
    return {
        "id": round_id,
        "kind": kind,
        "difficulty": _difficulty_for_round(len(path.hops), hops_json),
        "from_album_id": from_album_id,
        "to_album_id": to_album_id,
        "from_artist_id": path.from_artist_id,
        "to_artist_id": path.to_artist_id,
        "hops": hops_json,
        "distractors": distractors or [],
    }


def validate_rounds_artifact(universe: dict[str, Any], rounds: dict[str, Any]) -> None:
    """Validate a `universe.v1.json` / `rounds.v1.json` pair together -- they
    are cross-referential (rounds reference universe's albums) and must be
    checked as one unit, mirroring `challenge.py::validate_challenge`."""
    failures: list[str] = []

    if set(universe.keys()) != _UNIVERSE_TOP_LEVEL_KEYS:
        failures.append(f"universe has unexpected top-level keys: {sorted(universe.keys())}")
    if universe.get("schema_version") != ROUNDS_SCHEMA_VERSION:
        failures.append(f"universe schema_version must be {ROUNDS_SCHEMA_VERSION}")

    if set(rounds.keys()) != _ROUNDS_TOP_LEVEL_KEYS:
        failures.append(f"rounds has unexpected top-level keys: {sorted(rounds.keys())}")
    if rounds.get("schema_version") != ROUNDS_SCHEMA_VERSION:
        failures.append(f"rounds schema_version must be {ROUNDS_SCHEMA_VERSION}")
    if universe.get("pool_version") != rounds.get("pool_version"):
        failures.append("universe and rounds pool_version must match")

    for artifact, name in ((universe, "universe"), (rounds, "rounds")):
        provenance = artifact.get("provenance")
        if not isinstance(provenance, dict):
            failures.append(f"{name}.provenance must be an object")
        else:
            for field in (
                "source",
                "license",
                "snapshot_date",
                "generated_by",
                "graph_core_version",
            ):
                if not provenance.get(field):
                    failures.append(f"{name}.provenance.{field} is required")
        for seed_key_path in _find_seed_keys(artifact):
            failures.append(f"{name} must not have a 'seed' key ({seed_key_path})")

    album_ids = {album.get("id") for album in universe.get("albums", [])}
    release_ids = {release.get("release_id") for release in rounds.get("releases", [])}
    artist_ids = {artist.get("artist_id") for artist in rounds.get("artists", [])}

    for release in rounds.get("releases", []):
        if set(release.keys()) != _RELEASE_KEYS:
            failures.append(
                f"release {release.get('release_id')} has unexpected keys: {sorted(release.keys())}"
            )

    for round_json in rounds.get("rounds", []):
        round_id = round_json.get("id")
        if set(round_json.keys()) != _ROUND_KEYS:
            failures.append(f"round {round_id} has unexpected keys: {sorted(round_json.keys())}")
            continue
        difficulty = round_json.get("difficulty")
        if difficulty not in _DIFFICULTIES:
            failures.append(f"round {round_id} has invalid difficulty: {difficulty!r}")
        hops = round_json.get("hops", [])
        expected_hop_count = 1 if round_json.get("kind") == "one_hop" else 2
        if round_json.get("kind") not in ("one_hop", "two_hop"):
            failures.append(f"round {round_id} has invalid kind: {round_json.get('kind')!r}")
        elif len(hops) != expected_hop_count:
            failures.append(
                f"round {round_id} kind={round_json.get('kind')!r} must have "
                f"{expected_hop_count} hop(s), got {len(hops)}"
            )
        for album_field in ("from_album_id", "to_album_id"):
            if round_json.get(album_field) not in album_ids:
                failures.append(f"round {round_id} {album_field} references an unpublished album")
        for distractor in round_json.get("distractors", []):
            if set(distractor.keys()) != _DISTRACTOR_KEYS:
                failures.append(
                    f"round {round_id} distractor has unexpected keys: {sorted(distractor.keys())}"
                )
            elif distractor.get("album_id") not in album_ids:
                failures.append(f"round {round_id} distractor references an unpublished album")
        for hop in hops:
            if set(hop.keys()) != _HOP_KEYS:
                failures.append(f"round {round_id} hop has unexpected keys: {sorted(hop.keys())}")
                continue
            if hop.get("release_id") not in release_ids:
                failures.append(f"round {round_id} hop references an unpublished release")
            if hop.get("artist_a_id") not in artist_ids or hop.get("artist_b_id") not in artist_ids:
                failures.append(f"round {round_id} hop references an unpublished artist")
            if not hop.get("role_a") or not hop.get("role_b"):
                failures.append(f"round {round_id} hop is missing an explicit role_a/role_b")

    if failures:
        raise RoundsValidationError("; ".join(failures))

    for artifact in (universe, rounds):
        serialized = json.dumps(artifact)
        for forbidden in _FORBIDDEN_SUBSTRINGS:
            if forbidden in serialized:
                raise RoundsValidationError(f"artifact contains forbidden substring: {forbidden!r}")
        lowered = serialized.lower()
        for phrase in _FORBIDDEN_PHRASES:
            if phrase in lowered:
                raise RoundsValidationError(f"artifact contains forbidden phrase: {phrase!r}")
