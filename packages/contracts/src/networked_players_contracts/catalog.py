"""Canonical, dependency-free public-album-catalog validation.

Validates `apps/web/public/data/catalog/albums.v1.json` (ADR 0043) -- every
real public surface (album browser, Connection Guesser, Record Routes)
derives its album set from this file, so a malformed or unversioned catalog
would silently break every downstream consumer's ability to prove which
catalog it consumed.

A 1:1 port of `networked_players_graph_core.analysis::validate_album_catalog`
and its `_catalog_version` helper -- same checks, same failure wording where
practical, raise replaced by a returned failures list (mirrors every sibling
in this package). `_catalog_version` is reimplemented byte-for-byte: it is a
bespoke pipe-joined-string SHA-256 fingerprint, NOT `canonical.content_hash`
(which hashes canonical JSON of a value tree) -- using the wrong primitive
would silently produce a different digest and every catalog would fail its
own version check. If this module and `analysis.py`'s original ever
disagree on that formula, that is a real bug to fix, not a difference to
paper over.

What this module deliberately does NOT check: that any `main_release_id`/
`artist_id`/`master_id`/`year`/`title` is actually correct or resolvable
against the live Discogs dataset. That resolution is `analysis.py`'s
duckdb-backed job (`assemble_album_catalog`, the thing that *built* this
catalog in the first place). This module only proves the artifact is
internally well-formed and self-consistent since it was written (unique
ids, required fields present, well-typed `main_release_id`, `catalog_version`
matching the array's own recomputed content) -- "was this file corrupted or
hand-edited," not "is this file factually correct about Discogs."

Mirrors the other siblings' structure: pure-Python, no lxml/pyarrow/duckdb,
safe to run on the Pi fleet and in the web build.
"""

from __future__ import annotations

import hashlib
from typing import Any

_FORBIDDEN_SUBSTRINGS = ("/home/", "data/private", "local/", "DISCOGS_TOKEN", ".ssh")
_FORBIDDEN_PHRASES = ("worked with", "collaborated with", "influenced")

_REQUIRED_ALBUM_FIELDS = ("artist_id", "artist", "main_release_id", "title", "year")

# graph-expansion Phase 0 slice 0-B (ADR 0069): catalog schema v2 adds
# per-album `selection_source`/`featured`/`expansion_round`, gated behind a
# top-level `catalog_schema_version` -- absent (v1) requires none of this;
# present and 2 requires all of it. Must agree byte-for-byte with
# `networked_players_graph_core.analysis`'s own `CATALOG_SCHEMA_VERSION_V2`/
# `VALID_SELECTION_SOURCES`.
CATALOG_SCHEMA_VERSION_V2 = 2
VALID_SELECTION_SOURCES = frozenset(
    {"editorial", "already_published", "graph_rich", "coverage_gap", "generic_candidate"}
)


def _catalog_version(albums: list[dict[str, Any]], snapshot_date: str | None) -> str:
    """Must agree byte-for-byte with
    `networked_players_graph_core.analysis::_catalog_version`."""
    fingerprint = "|".join(
        sorted(
            f"{a.get('artist_id')}:{a.get('main_release_id')}:{a.get('master_id')}:{a.get('year')}"
            for a in albums
        )
    )
    digest = hashlib.sha256(fingerprint.encode()).hexdigest()[:12]
    prefix = f"catalog-v1-{snapshot_date}" if snapshot_date else "catalog-v1"
    return f"{prefix}-{digest}"


def _catalog_presentation_version(albums: list[dict[str, Any]], snapshot_date: str | None) -> str:
    """Must agree byte-for-byte with
    `networked_players_graph_core.analysis::_catalog_presentation_version`."""
    fingerprint = "|".join(
        sorted(f"{a.get('id')}:{a.get('featured')}:{a.get('selection_source')}" for a in albums)
    )
    digest = hashlib.sha256(fingerprint.encode()).hexdigest()[:12]
    prefix = (
        f"catalog-presentation-v1-{snapshot_date}" if snapshot_date else "catalog-presentation-v1"
    )
    return f"{prefix}-{digest}"


def public_album_catalog_failures(catalog: Any) -> list[str]:
    """Return every contract failure in the canonical public album catalog."""
    if not isinstance(catalog, dict):
        return ["catalog artifact must be an object"]

    failures: list[str] = []
    if not catalog.get("catalog_version"):
        failures.append("catalog_version is required")
    if not catalog.get("snapshot_date"):
        failures.append("snapshot_date is required")
    if not catalog.get("generated_by"):
        failures.append("generated_by is required")

    albums = catalog.get("albums", [])
    if not isinstance(albums, list) or not albums:
        failures.append("albums must not be empty")
        albums = []

    seen_ids: set[Any] = set()
    for album in albums:
        if not isinstance(album, dict):
            failures.append(f"album must be an object, got {album!r}")
            continue
        album_id = album.get("id")
        if not album_id:
            failures.append(f"album missing id: {album!r}")
            continue
        if album_id in seen_ids:
            failures.append(f"duplicate album id: {album_id}")
        seen_ids.add(album_id)
        for field_name in _REQUIRED_ALBUM_FIELDS:
            if field_name not in album:
                failures.append(f"album {album_id} missing required field {field_name!r}")
        if not isinstance(album.get("main_release_id"), int) or album["main_release_id"] <= 0:
            failures.append(f"album {album_id} has an invalid main_release_id")

    schema_version = catalog.get("catalog_schema_version")
    if schema_version is not None:
        if schema_version != CATALOG_SCHEMA_VERSION_V2:
            failures.append(f"unsupported catalog_schema_version: {schema_version!r}")
        else:
            for album in albums:
                if not isinstance(album, dict):
                    continue
                album_id = album.get("id", "<unknown>")
                selection_source = album.get("selection_source")
                if selection_source not in VALID_SELECTION_SOURCES:
                    failures.append(
                        f"album {album_id} has an invalid selection_source: {selection_source!r}"
                    )
                if not isinstance(album.get("featured"), bool):
                    failures.append(f"album {album_id} missing/invalid boolean 'featured'")
                expansion_round = album.get("expansion_round")
                if (
                    not isinstance(expansion_round, int)
                    or isinstance(expansion_round, bool)
                    or expansion_round < 0
                ):
                    failures.append(
                        f"album {album_id} missing/invalid non-negative 'expansion_round'"
                    )
            expected_presentation_version = _catalog_presentation_version(
                [a for a in albums if isinstance(a, dict)], catalog.get("snapshot_date")
            )
            if catalog.get("catalog_presentation_version") != expected_presentation_version:
                failures.append(
                    "catalog_presentation_version "
                    f"{catalog.get('catalog_presentation_version')!r} does not match its own "
                    f"content (expected {expected_presentation_version!r})"
                )

    expected_version = _catalog_version(
        [a for a in albums if isinstance(a, dict)], catalog.get("snapshot_date")
    )
    if catalog.get("catalog_version") != expected_version:
        failures.append(
            f"catalog_version {catalog.get('catalog_version')!r} does not match its own "
            f"content (expected {expected_version!r}) -- the file was hand-edited or corrupted"
        )

    serialized = str(catalog)
    for forbidden in _FORBIDDEN_SUBSTRINGS:
        if forbidden in serialized:
            failures.append(f"catalog contains forbidden substring: {forbidden!r}")
    lowered = serialized.lower()
    for phrase in _FORBIDDEN_PHRASES:
        if phrase in lowered:
            failures.append(f"catalog contains forbidden phrase: {phrase!r}")

    return failures
