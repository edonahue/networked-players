"""Canonical, dependency-free validation for the Record Routes artifact pair.

Record Routes (`apps/web/public/data/routes/{universe,rounds}.v1.json`,
`data/contracts/record-routes-v1.md`, ADR 0046) is the path-guessing mode: a
round shows two albums and the player guesses the documented credit-path length
(one or two hops), then a connecting artist, then reveals the path. This is the
`from_album_id`/`to_album_id`/`hops[]` **path** contract -- distinct from the
Connection Guesser's intersection contract
(`networked_players_contracts.connection_rounds`) and from the legacy generic
`networked_players_contracts.rounds` (which this refines with an explicit
`mode`, content-derived stable `route-<hash>` ids, and deterministic
`pool_version`/`artifact_version`). It never shares an artifact path with the
Connection Guesser's `game/rounds.v1.json` or its daily manifest.

Pure Python (no lxml/pyarrow/duckdb), safe for the Pi fleet and the web build.
"""

from __future__ import annotations

import re
from typing import Any

from .canonical import content_hash, stable_id_digest
from .rounds import (
    _DIFFICULTIES,
    _DISTRACTOR_KEYS,
    _KINDS,
    _ROUND_KEYS,
    _hop_failures,
    _privacy_failures,
    _seed_key_paths,
)

RECORD_ROUTES_SCHEMA_VERSION = 1
RECORD_ROUTES_MODE = "record_routes"

_ROUTE_ID_PATTERN = re.compile(r"^route-[0-9a-f]{10}$")
_UNIVERSE_TOP_LEVEL_KEYS = frozenset(
    {"schema_version", "mode", "pool_version", "provenance", "counts", "albums"}
)
_ROUNDS_TOP_LEVEL_KEYS = frozenset(
    {"schema_version", "mode", "pool_version", "provenance", "rounds", "releases", "artists"}
)
_PROVENANCE_REQUIRED = (
    "source",
    "license",
    "snapshot_date",
    "generated_by",
    "note",
    "catalog_version",
    "artifact_version",
)


def _hop_signature(hop: dict[str, Any]) -> str:
    lo, hi = sorted((int(hop["artist_a_id"]), int(hop["artist_b_id"])))
    return f"{hop.get('release_id')}:{lo}:{hi}"


def recomputed_route_id(round_json: dict[str, Any]) -> str | None:
    """Recompute a route's stable id from its own published semantics -- must
    agree with `networked_players_graph_core.record_routes::stable_route_id`."""
    try:
        endpoints = sorted((str(round_json["from_album_id"]), str(round_json["to_album_id"])))
        hop_part = ",".join(_hop_signature(h) for h in round_json.get("hops", []))
    except (KeyError, TypeError, ValueError):
        return None
    return f"route-{stable_id_digest('rr', *endpoints, hop_part)}"


def _pool_version(round_ids: list[str], snapshot_date: str) -> str:
    return f"routes-v1-{snapshot_date}-{content_hash(sorted(round_ids), length=12)}"


def _artifact_version(rounds_json: list[Any], snapshot_date: str) -> str:
    return f"routes-artifact-v1-{snapshot_date}-{content_hash(rounds_json, length=12)}"


def record_routes_failures(universe: Any, rounds: Any) -> list[str]:
    """Return every contract failure in a Record Routes universe/rounds pair."""
    failures: list[str] = []
    if not isinstance(universe, dict):
        return ["universe artifact must be an object"]
    if not isinstance(rounds, dict):
        return ["rounds artifact must be an object"]

    if set(universe) != _UNIVERSE_TOP_LEVEL_KEYS:
        failures.append(f"universe has unexpected top-level keys: {sorted(universe)}")
    if set(rounds) != _ROUNDS_TOP_LEVEL_KEYS:
        failures.append(f"rounds has unexpected top-level keys: {sorted(rounds)}")
    for name, art in (("universe", universe), ("rounds", rounds)):
        if art.get("schema_version") != RECORD_ROUTES_SCHEMA_VERSION:
            failures.append(f"{name} schema_version must be {RECORD_ROUTES_SCHEMA_VERSION}")
        if art.get("mode") != RECORD_ROUTES_MODE:
            failures.append(f"{name} mode must be {RECORD_ROUTES_MODE!r}")
    if universe.get("pool_version") != rounds.get("pool_version"):
        failures.append("universe and rounds pool_version must match")
    if universe.get("provenance") != rounds.get("provenance"):
        failures.append("universe and rounds provenance must match exactly")

    provenance = universe.get("provenance", {})
    if not isinstance(provenance, dict):
        provenance = {}
        failures.append("provenance must be an object")
    for field_name in _PROVENANCE_REQUIRED:
        if not provenance.get(field_name):
            failures.append(f"provenance.{field_name} is required")

    album_ids = {a.get("id") for a in universe.get("albums", []) if isinstance(a, dict)}

    # Art-free: no cover-art payload may live in this artifact (ADR 0045).
    for index, album in enumerate(universe.get("albums", [])):
        if isinstance(album, dict) and ("cover_image" in album or "art" in album):
            failures.append(
                f"universe.albums[{index}] must be art-free (resolve cover art by album id "
                f"from the album-art registry, ADR 0045)"
            )

    round_entries = rounds.get("rounds")
    if not isinstance(round_entries, list):
        return [*failures, "rounds.rounds must be an array"]

    seen_ids: set[Any] = set()
    for round_json in round_entries:
        if not isinstance(round_json, dict):
            failures.append("round must be an object")
            continue
        route_id = round_json.get("id")
        if route_id in seen_ids:
            failures.append(f"duplicate route id: {route_id}")
        seen_ids.add(route_id)
        if not isinstance(route_id, str) or not _ROUTE_ID_PATTERN.match(route_id):
            failures.append(f"route id {route_id!r} is not a content-derived route id")
        else:
            recomputed = recomputed_route_id(round_json)
            if recomputed is not None and recomputed != route_id:
                failures.append(
                    f"route id {route_id} does not match its own recomputed content "
                    f"(expected {recomputed})"
                )
        if set(round_json) != _ROUND_KEYS:
            failures.append(f"route {route_id} has unexpected keys: {sorted(round_json)}")
            continue
        if round_json.get("difficulty") not in _DIFFICULTIES:
            failures.append(f"route {route_id} has invalid difficulty")
        kind = round_json.get("kind")
        if kind not in _KINDS:
            failures.append(f"route {route_id} has invalid kind: {kind!r}")
        hops = round_json.get("hops", [])
        expected_hops = 1 if kind == "one_hop" else 2
        if not isinstance(hops, list) or len(hops) != expected_hops:
            failures.append(f"route {route_id} kind {kind!r} must have {expected_hops} hop(s)")
        else:
            for hop in hops:
                failures.extend(_hop_failures(hop, round_id=route_id))
        if round_json.get("from_album_id") == round_json.get("to_album_id"):
            failures.append(f"route {route_id} endpoints must be two different albums")
        for endpoint_field in ("from_album_id", "to_album_id"):
            if round_json.get(endpoint_field) not in album_ids:
                failures.append(f"route {route_id} {endpoint_field} not in universe")
        endpoints = {round_json.get("from_album_id"), round_json.get("to_album_id")}
        for distractor in round_json.get("distractors", []):
            if not isinstance(distractor, dict) or set(distractor) != _DISTRACTOR_KEYS:
                failures.append(f"route {route_id} has a malformed distractor")
                continue
            if distractor.get("album_id") not in album_ids:
                failures.append(f"route {route_id} distractor album not in universe")
            if distractor.get("album_id") in endpoints:
                failures.append(f"route {route_id} distractor is one of its own endpoints")

    snapshot_date = provenance.get("snapshot_date")
    if isinstance(snapshot_date, str):
        route_ids = [r.get("id") for r in round_entries if isinstance(r, dict)]
        expected_pool = _pool_version([str(i) for i in route_ids], snapshot_date)
        if universe.get("pool_version") != expected_pool:
            failures.append(
                f"pool_version {universe.get('pool_version')!r} does not match the routes' own "
                f"membership (expected {expected_pool!r})"
            )
        expected_artifact = _artifact_version(round_entries, snapshot_date)
        if provenance.get("artifact_version") != expected_artifact:
            failures.append(
                f"provenance.artifact_version {provenance.get('artifact_version')!r} does not "
                f"match the rounds' own ordered content (expected {expected_artifact!r})"
            )

    source = str(provenance.get("source", "")).lower()
    generated_by = str(provenance.get("generated_by", "")).lower()
    if "discogs" not in source:
        failures.append("provenance.source does not identify a real Discogs source")
    if "synthetic" in generated_by or "ci placeholder" in generated_by:
        failures.append("provenance.generated_by marks this as a synthetic fixture")

    for name, artifact in (("universe", universe), ("rounds", rounds)):
        failures.extend(
            f"{name} must not have a 'seed' key ({p})" for p in _seed_key_paths(artifact)
        )
        failures.extend(_privacy_failures(artifact, name=name))

    return failures
