"""Canonical, dependency-free validation for the public album-art registry.

The album-art registry (`apps/web/public/data/catalog/album-art.v1.json`,
`data/contracts/album-art-v1.md`, ADR 0045) is a **presentation-only**,
separately versioned lookup of hotlinked Discogs cover-art URLs keyed by
canonical album id. It is deliberately NOT part of any frozen, fingerprinted
game content: the Connection Guesser rounds and the daily manifest never
embed a cover-art URL, so enriching or refreshing art can never change a
round fingerprint or the daily manifest's compatibility (ADR 0044/0045). Cover
art is never evidence (see docs/DATA_AND_RIGHTS.md); a registry with every
album absent is still valid -- the frontend simply renders placeholders.

Pure Python (no lxml/pyarrow/duckdb), safe for the Pi fleet and the web build
to independently verify an already-generated registry against the canonical
catalog it claims to belong to.
"""

from __future__ import annotations

import re
from typing import Any

from .canonical import content_hash

ALBUM_ART_SCHEMA_VERSION = 1
ALBUM_ART_APPROVED_IMAGE_HOSTS = ("i.discogs.com",)

_ART_VERSION_PATTERN = re.compile(r"^album-art-v1-[0-9A-Za-z]+-[0-9a-f]{12}$")
_HTTPS_URL_PATTERN = re.compile(r"^https://([^/]+)/", re.IGNORECASE)
_FORBIDDEN_SUBSTRINGS = (
    "/" + "home/",
    "data/" + "private",
    "local" + "/",
    "DISCOGS" + "_TOKEN",
    "." + "ssh",
    "token=",
)
_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "catalog_version",
        "art_version",
        "generated_at",
        "source",
        "license",
        "albums",
    }
)
_ENTRY_KEYS = frozenset({"album_id", "main_release_id", "uri150", "uri", "width", "height"})


def album_art_version(entries: list[dict[str, Any]], snapshot_date: str) -> str:
    """The registry's `art_version`. Order-INSENSITIVE (unlike a rounds
    artifact_version): the registry is a lookup map, so its entries are hashed
    sorted by album_id. Only the load-bearing identity (album_id + the two
    hotlink URLs) is hashed, so cosmetic width/height changes do not move the
    version, but a real URL change does."""
    identity = sorted(
        (
            {
                "album_id": e.get("album_id"),
                "uri150": e.get("uri150"),
                "uri": e.get("uri"),
            }
            for e in entries
            if isinstance(e, dict)
        ),
        key=lambda e: str(e["album_id"]),
    )
    return f"album-art-v1-{snapshot_date}-{content_hash(identity, length=12)}"


def _approved_https_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    match = _HTTPS_URL_PATTERN.match(value)
    if not match:
        return False
    host = match.group(1).split(":")[0].lower()
    return host in ALBUM_ART_APPROVED_IMAGE_HOSTS


def album_art_failures(registry: Any, catalog: Any) -> list[str]:
    """Every contract failure in an album-art registry, validated against the
    canonical catalog it claims to belong to. An empty `albums` list is valid
    (all placeholders). `catalog` is the parsed
    `apps/web/public/data/catalog/albums.v1.json`."""
    failures: list[str] = []
    if not isinstance(registry, dict):
        return ["album-art registry must be an object"]
    if not isinstance(catalog, dict):
        return ["catalog must be an object"]

    if set(registry.keys()) != _TOP_LEVEL_KEYS:
        failures.append(f"registry has unexpected top-level keys: {sorted(registry.keys())}")
    if registry.get("schema_version") != ALBUM_ART_SCHEMA_VERSION:
        failures.append(f"schema_version must be {ALBUM_ART_SCHEMA_VERSION}")
    for field_name in ("catalog_version", "art_version", "generated_at", "source", "license"):
        if not registry.get(field_name):
            failures.append(f"{field_name} is required and must be non-empty")

    catalog_version = catalog.get("catalog_version")
    if registry.get("catalog_version") != catalog_version:
        failures.append(
            f"registry catalog_version {registry.get('catalog_version')!r} does not match the "
            f"canonical catalog's catalog_version {catalog_version!r} -- a registry belongs to "
            f"exactly one catalog generation"
        )

    catalog_album_ids = {a.get("id") for a in catalog.get("albums", []) if isinstance(a, dict)}

    entries = registry.get("albums")
    if not isinstance(entries, list):
        failures.append("albums must be an array")
        entries = []

    art_version = registry.get("art_version")
    if isinstance(art_version, str) and not _ART_VERSION_PATTERN.match(art_version):
        failures.append(f"art_version {art_version!r} is not a well-formed album-art-v1 version")
    snapshot_date = catalog.get("snapshot_date")
    if isinstance(snapshot_date, str) and isinstance(art_version, str):
        expected = album_art_version(entries, snapshot_date)
        if art_version != expected:
            failures.append(
                f"art_version {art_version!r} does not match the registry's own recomputed "
                f"content (expected {expected!r})"
            )

    seen_album_ids: set[Any] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            failures.append(f"albums[{index}] must be an object")
            continue
        if set(entry.keys()) - {"width", "height"} != _ENTRY_KEYS - {"width", "height"}:
            failures.append(f"albums[{index}] has unexpected keys: {sorted(entry.keys())}")
        album_id = entry.get("album_id")
        if album_id in seen_album_ids:
            failures.append(f"albums[{index}] duplicate album_id {album_id!r}")
        seen_album_ids.add(album_id)
        if album_id not in catalog_album_ids:
            failures.append(
                f"albums[{index}] album_id {album_id!r} is not in the canonical catalog"
            )
        if not isinstance(entry.get("main_release_id"), int):
            failures.append(f"albums[{index}] main_release_id must be an integer")
        for url_field in ("uri150", "uri"):
            if not _approved_https_url(entry.get(url_field)):
                failures.append(
                    f"albums[{index}] {url_field} must be an https URL on an approved host "
                    f"{ALBUM_ART_APPROVED_IMAGE_HOSTS}"
                )
        for dim in ("width", "height"):
            if dim in entry and not isinstance(entry[dim], int):
                failures.append(f"albums[{index}] {dim} must be an integer when present")

    serialized = str(registry)
    for forbidden in _FORBIDDEN_SUBSTRINGS:
        if forbidden in serialized:
            failures.append(f"registry contains forbidden substring: {forbidden!r}")

    return failures
