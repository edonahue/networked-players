"""Canonical, dependency-free validation for the public album-credit-
membership artifact.

The album-credit-membership artifact
(`apps/web/public/data/albums/credit-membership.v1.json`,
`data/contracts/album-credit-membership-v1.md`, ADR 0058) is the single
canonical answer to "who's credited on album X" for the 140-album catalog
-- replacing the pre-existing 3-way inconsistency across `challenge.v2.json`,
Connection Guesser/Record Routes, and the pathfinding graph. Every album's
`main_release_id` must agree exactly with the canonical catalog's own
choice; this artifact never invents its own release selection.

Pure Python (no lxml/pyarrow/duckdb), safe for the Pi fleet and the web
build to independently verify an already-generated artifact against the
canonical catalog it claims to belong to.
"""

from __future__ import annotations

import re
from typing import Any

from .canonical import content_hash

ALBUM_CREDIT_MEMBERSHIP_SCHEMA_VERSION = 1

_VERSION_PATTERN = re.compile(r"^album-credit-membership-v1-[0-9A-Za-z]+-[0-9a-f]{12}$")

_VALID_CREDIT_SCOPES = frozenset(
    {"release_artist", "release_credit", "track_artist", "track_credit"}
)

# Mirrors catalog.py's constants -- kept as a separate copy deliberately (this
# module must stay dependency-free of catalog.py, the same posture every
# other contract module in this package already takes).
_FORBIDDEN_SUBSTRINGS = ("/home/", "data/private", "local/", "DISCOGS_TOKEN", ".ssh")
_FORBIDDEN_PHRASES = ("worked with", "collaborated with", "influenced")

_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "catalog_version",
        "album_credit_membership_version",
        "generated_at",
        "source",
        "license",
        "albums",
    }
)
_ALBUM_KEYS = frozenset({"album_id", "main_release_id", "credits"})
_CREDIT_KEYS = frozenset(
    {"artist_id", "name", "anv", "role_text", "credit_scope", "track_position", "track_title"}
)


def album_credit_membership_version(albums: list[dict[str, Any]], snapshot_date: str) -> str:
    """Recomputation mirror of the generation-time function in
    `networked_players_graph_core.album_credit_membership` -- duplicated here
    deliberately (this package stays dependency-free of graph-core, the same
    split every other contract/builder pair in this project already uses)."""
    identity = [
        {
            "album_id": a.get("album_id"),
            "main_release_id": a.get("main_release_id"),
            "credits": a.get("credits"),
        }
        for a in albums
        if isinstance(a, dict)
    ]
    return f"album-credit-membership-v1-{snapshot_date}-{content_hash(identity, length=12)}"


def album_credit_membership_failures(membership: Any, catalog: Any) -> list[str]:
    """Every contract failure in an album-credit-membership artifact,
    validated against the canonical catalog and the albums/main_release_ids
    it claims to reference. An empty `credits` list on an album is valid
    (honest evidence the release's credits are thin), but every catalog
    album must appear exactly once."""
    failures: list[str] = []
    if not isinstance(membership, dict):
        return ["album-credit-membership must be an object"]
    if not isinstance(catalog, dict):
        return ["catalog must be an object"]

    if set(membership.keys()) != _TOP_LEVEL_KEYS:
        failures.append(
            f"album-credit-membership has unexpected top-level keys: {sorted(membership.keys())}"
        )
    if membership.get("schema_version") != ALBUM_CREDIT_MEMBERSHIP_SCHEMA_VERSION:
        failures.append(f"schema_version must be {ALBUM_CREDIT_MEMBERSHIP_SCHEMA_VERSION}")
    for field_name in (
        "catalog_version",
        "album_credit_membership_version",
        "generated_at",
        "source",
        "license",
    ):
        if not membership.get(field_name):
            failures.append(f"{field_name} is required and must be non-empty")

    catalog_version = catalog.get("catalog_version")
    if membership.get("catalog_version") != catalog_version:
        failures.append(
            f"album-credit-membership catalog_version {membership.get('catalog_version')!r} "
            f"does not match the canonical catalog's catalog_version {catalog_version!r}"
        )

    catalog_albums = {
        a.get("id"): a.get("main_release_id")
        for a in catalog.get("albums", [])
        if isinstance(a, dict)
    }

    albums = membership.get("albums")
    if not isinstance(albums, list):
        failures.append("albums must be an array")
        albums = []

    version = membership.get("album_credit_membership_version")
    if isinstance(version, str) and not _VERSION_PATTERN.match(version):
        failures.append(
            f"album_credit_membership_version {version!r} is not a well-formed "
            f"album-credit-membership-v1 version"
        )
    snapshot_date = catalog.get("snapshot_date")
    if isinstance(snapshot_date, str) and isinstance(version, str):
        expected = album_credit_membership_version(albums, snapshot_date)
        if version != expected:
            failures.append(
                f"album_credit_membership_version {version!r} does not match the artifact's "
                f"own recomputed content (expected {expected!r})"
            )

    seen_album_ids: set[Any] = set()
    for i, album in enumerate(albums):
        if not isinstance(album, dict):
            failures.append(f"albums[{i}] must be an object")
            continue
        if set(album.keys()) != _ALBUM_KEYS:
            failures.append(f"albums[{i}] has unexpected keys: {sorted(album.keys())}")

        album_id = album.get("album_id")
        if album_id not in catalog_albums:
            failures.append(f"albums[{i}] album_id {album_id!r} is not in the canonical catalog")
        elif album_id in seen_album_ids:
            failures.append(f"albums[{i}] duplicate album_id {album_id!r}")
        else:
            seen_album_ids.add(album_id)
            expected_release = catalog_albums.get(album_id)
            if album.get("main_release_id") != expected_release:
                failures.append(
                    f"albums[{i}] main_release_id {album.get('main_release_id')!r} does not "
                    f"match the catalog's own choice {expected_release!r} for album "
                    f"{album_id!r} -- this artifact must never re-derive it"
                )

        credits = album.get("credits")
        if not isinstance(credits, list):
            failures.append(f"albums[{i}] credits must be an array")
            continue
        for j, credit in enumerate(credits):
            if not isinstance(credit, dict) or set(credit.keys()) != _CREDIT_KEYS:
                failures.append(f"albums[{i}] credits[{j}] must have keys {sorted(_CREDIT_KEYS)}")
                continue
            artist_id = credit.get("artist_id")
            if not isinstance(artist_id, int) or isinstance(artist_id, bool):
                failures.append(f"albums[{i}] credits[{j}] artist_id must be an integer")
            if not isinstance(credit.get("name"), str) or not credit.get("name"):
                failures.append(f"albums[{i}] credits[{j}] name must be a non-empty string")
            if credit.get("credit_scope") not in _VALID_CREDIT_SCOPES:
                failures.append(
                    f"albums[{i}] credits[{j}] credit_scope {credit.get('credit_scope')!r} "
                    f"is not one of {sorted(_VALID_CREDIT_SCOPES)}"
                )

    missing_albums = set(catalog_albums) - seen_album_ids
    if missing_albums:
        shown = sorted(missing_albums, key=str)[:5]
        failures.append(
            f"album-credit-membership is missing {len(missing_albums)} catalog album(s): "
            f"{shown}{'...' if len(missing_albums) > 5 else ''}"
        )

    serialized = str(membership)
    for forbidden in _FORBIDDEN_SUBSTRINGS:
        if forbidden in serialized:
            failures.append(f"album-credit-membership contains forbidden substring: {forbidden!r}")
    lowered = serialized.lower()
    for phrase in _FORBIDDEN_PHRASES:
        if phrase in lowered:
            failures.append(
                f"album-credit-membership contains forbidden inference-implying phrase: {phrase!r}"
            )

    return failures
