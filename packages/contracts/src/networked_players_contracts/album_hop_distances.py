"""Canonical, dependency-free validation for the public album-hop-distances
artifact.

`album-hop-distances-v1` (`apps/web/public/data/contributors/
album-hop-distances.v1.json`, `data/contracts/album-hop-distances-v1.md`,
ADR 0048 addendum) is a companion artifact to `contributor-index-v1`,
carrying the `{artist_id, album_id, hop_distance}` data that a required new
key on `contributor-index-v1` would have broken: that index's own contract
is validated as an exact top-level key set, so widening it in place would
reject every already-published v1 file under old validator code, and be
rejected itself by any external consumer pinned to the documented v1 key
list. A separate, independently versioned artifact keeps both contracts
exactly as they were.

Pure Python (no lxml/pyarrow/duckdb), safe for the Pi fleet and the web
build to independently verify an already-generated artifact against the
canonical catalog and contributor index it claims to belong to.
"""

from __future__ import annotations

import re
from typing import Any

from .canonical import content_hash

ALBUM_HOP_DISTANCES_SCHEMA_VERSION = 1

_VERSION_PATTERN = re.compile(r"^album-hop-distances-v1-[0-9A-Za-z]+-[0-9a-f]{12}$")

_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "catalog_version",
        "album_hop_distances_version",
        "generated_at",
        "source",
        "license",
        "entries",
    }
)
_ENTRY_KEYS = frozenset({"artist_id", "album_id", "hop_distance"})


def album_hop_distances_version(entries: list[dict[str, Any]], snapshot_date: str) -> str:
    """Recomputation mirror of the generation-time function in
    `networked_players_graph_core.contributor_index` -- duplicated here
    deliberately (this package stays dependency-free of graph-core, the
    same split every other contract/builder pair in this project already
    uses)."""
    identity = sorted(
        (
            {
                "artist_id": e.get("artist_id"),
                "album_id": e.get("album_id"),
                "hop_distance": e.get("hop_distance"),
            }
            for e in entries
            if isinstance(e, dict)
        ),
        key=lambda e: (
            e["artist_id"] is None,
            e["artist_id"] if isinstance(e["artist_id"], int) else 0,
            str(e["album_id"]),
        ),
    )
    return f"album-hop-distances-v1-{snapshot_date}-{content_hash(identity, length=12)}"


def album_hop_distances_failures(artifact: Any, catalog: Any, contributor_index: Any) -> list[str]:
    """Every contract failure in an album-hop-distances artifact, validated
    against the canonical catalog and the contributor index it's a
    companion to. An empty `entries` list is valid."""
    failures: list[str] = []
    if not isinstance(artifact, dict):
        return ["album-hop-distances artifact must be an object"]
    if not isinstance(catalog, dict):
        return ["catalog must be an object"]
    if not isinstance(contributor_index, dict):
        return ["contributor_index must be an object"]

    if set(artifact.keys()) != _TOP_LEVEL_KEYS:
        failures.append(f"artifact has unexpected top-level keys: {sorted(artifact.keys())}")
    if artifact.get("schema_version") != ALBUM_HOP_DISTANCES_SCHEMA_VERSION:
        failures.append(f"schema_version must be {ALBUM_HOP_DISTANCES_SCHEMA_VERSION}")
    for field_name in (
        "catalog_version",
        "album_hop_distances_version",
        "generated_at",
        "source",
        "license",
    ):
        if not artifact.get(field_name):
            failures.append(f"{field_name} is required and must be non-empty")

    catalog_version = catalog.get("catalog_version")
    if artifact.get("catalog_version") != catalog_version:
        failures.append(
            f"artifact catalog_version {artifact.get('catalog_version')!r} does not match "
            f"the canonical catalog's catalog_version {catalog_version!r}"
        )

    catalog_album_ids = {a.get("id") for a in catalog.get("albums", []) if isinstance(a, dict)}
    contributor_artist_ids = {
        c.get("artist_id") for c in contributor_index.get("contributors", []) if isinstance(c, dict)
    }

    entries = artifact.get("entries")
    if not isinstance(entries, list):
        failures.append("entries must be an array")
        entries = []

    version = artifact.get("album_hop_distances_version")
    if isinstance(version, str) and not _VERSION_PATTERN.match(version):
        failures.append(
            f"album_hop_distances_version {version!r} is not a well-formed "
            f"album-hop-distances-v1 version"
        )
    snapshot_date = catalog.get("snapshot_date")
    if isinstance(snapshot_date, str) and isinstance(version, str):
        expected = album_hop_distances_version(entries, snapshot_date)
        if version != expected:
            failures.append(
                f"album_hop_distances_version {version!r} does not match the artifact's own "
                f"recomputed content (expected {expected!r})"
            )

    # (artist_id, album_id) pairs seen so far, and the sort key each
    # well-formed entry contributes -- tracked in the same pass so a
    # malformed entry (wrong keys, non-string album_id, etc.) never reaches
    # a set/tuple operation that could raise instead of reporting a clean
    # failure (a real bug caught in review: `album_id` from malformed JSON
    # can be a list or dict, and `set.add`/`in` on that raises TypeError
    # before validation can report anything).
    seen_pairs: set[tuple[int, str]] = set()
    duplicate_found = False
    sort_keys: list[tuple[int, int, str]] = []
    sort_keys_complete = True

    for i, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry.keys()) != _ENTRY_KEYS:
            failures.append(f"entries[{i}] must have keys {_ENTRY_KEYS}")
            sort_keys_complete = False
            continue

        raw_artist_id = entry.get("artist_id")
        artist_id: int | None = None
        if not isinstance(raw_artist_id, int) or isinstance(raw_artist_id, bool):
            failures.append(f"entries[{i}] artist_id must be an integer")
        else:
            artist_id = raw_artist_id
            if artist_id not in contributor_artist_ids:
                failures.append(
                    f"entries[{i}] artist_id {artist_id!r} is not a published contributor "
                    f"in the contributor index"
                )

        raw_album_id = entry.get("album_id")
        album_id: str | None = None
        if not isinstance(raw_album_id, str) or not raw_album_id:
            failures.append(f"entries[{i}] album_id must be a non-empty string")
        else:
            album_id = raw_album_id
            if album_id not in catalog_album_ids:
                failures.append(f"entries[{i}] album {album_id!r} is not in the canonical catalog")

        raw_hop_distance = entry.get("hop_distance")
        hop_distance: int | None = None
        if (
            not isinstance(raw_hop_distance, int)
            or isinstance(raw_hop_distance, bool)
            or raw_hop_distance < 0
        ):
            failures.append(f"entries[{i}] hop_distance must be a non-negative integer")
        else:
            hop_distance = raw_hop_distance

        if artist_id is not None and album_id is not None:
            pair = (artist_id, album_id)
            if pair in seen_pairs:
                duplicate_found = True
            seen_pairs.add(pair)

        if artist_id is not None and album_id is not None and hop_distance is not None:
            sort_keys.append((artist_id, hop_distance, album_id))
        else:
            sort_keys_complete = False

    if duplicate_found:
        failures.append("entries must not repeat the same (artist_id, album_id) pair")
    if sort_keys_complete and sort_keys != sorted(sort_keys):
        failures.append("entries must be sorted by (artist_id, hop_distance, album_id)")

    return failures
