"""Canonical, dependency-free validation for the public site-search index.

`search-index-v1` (`apps/web/public/data/search/index.v1.json`,
`data/contracts/search-index-v1.md`, graph-expansion Phase 1, plan
section 7) is a flat list of searchable destinations -- albums and
contributors, each carrying `kind`, `id`, `label`, `sublabel`, and `state`.
Validated against the canonical catalog and the contributor index it's
built from, the same cross-artifact pattern `album_hop_distances.py` and
`contributor_index.py`'s own validator already use.

Pure Python (no lxml/pyarrow/duckdb), safe for the Pi fleet and the web
build to independently verify an already-generated index against the two
artifacts it claims to be built from.
"""

from __future__ import annotations

import re
from typing import Any

from .canonical import content_hash

SEARCH_INDEX_SCHEMA_VERSION = 1

_VERSION_PATTERN = re.compile(r"^search-index-v1-[0-9A-Za-z]+-[0-9a-f]{12}$")

_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "catalog_version",
        "contributor_index_version",
        "search_index_version",
        "generated_at",
        "source",
        "license",
        "entries",
    }
)
_ENTRY_KEYS = frozenset({"kind", "id", "label", "sublabel", "state"})
_VALID_KINDS = frozenset({"album", "contributor"})
_VALID_STATES = frozenset({"present", "candidate"})


def search_index_version(entries: list[dict[str, Any]], snapshot_date: str) -> str:
    """Recomputation mirror of the generation-time function in
    `networked_players_graph_core.search_index` -- duplicated here
    deliberately (this package stays dependency-free of graph-core, the
    same split every other contract/builder pair in this project already
    uses)."""
    identity = sorted(
        (
            {
                "kind": e.get("kind"),
                "id": e.get("id"),
                "label": e.get("label"),
                "sublabel": e.get("sublabel"),
                "state": e.get("state"),
            }
            for e in entries
            if isinstance(e, dict)
        ),
        key=lambda e: (str(e["kind"]), str(e["id"])),
    )
    digest = content_hash(identity, length=12)
    return f"search-index-v1-{snapshot_date}-{digest}"


def search_index_failures(artifact: Any, catalog: Any, contributor_index: Any) -> list[str]:
    """Every contract failure in a search index, validated against the
    canonical catalog and contributor index it's a companion to."""
    failures: list[str] = []
    if not isinstance(artifact, dict):
        return ["search index artifact must be an object"]
    if not isinstance(catalog, dict):
        return ["catalog must be an object"]
    if not isinstance(contributor_index, dict):
        return ["contributor_index must be an object"]

    if set(artifact.keys()) != _TOP_LEVEL_KEYS:
        failures.append(f"artifact has unexpected top-level keys: {sorted(artifact.keys())}")
    if artifact.get("schema_version") != SEARCH_INDEX_SCHEMA_VERSION:
        failures.append(f"schema_version must be {SEARCH_INDEX_SCHEMA_VERSION}")

    for field_name in (
        "catalog_version",
        "contributor_index_version",
        "search_index_version",
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
    contributor_index_version = contributor_index.get("contributor_index_version")
    if artifact.get("contributor_index_version") != contributor_index_version:
        failures.append(
            f"artifact contributor_index_version {artifact.get('contributor_index_version')!r} "
            f"does not match the contributor index's own "
            f"contributor_index_version {contributor_index_version!r}"
        )

    catalog_album_ids = {a.get("id") for a in catalog.get("albums", []) if isinstance(a, dict)}
    contributor_artist_ids = {
        c.get("artist_id") for c in contributor_index.get("contributors", []) if isinstance(c, dict)
    }

    entries = artifact.get("entries")
    if not isinstance(entries, list):
        failures.append("entries must be an array")
        entries = []

    version = artifact.get("search_index_version")
    if isinstance(version, str) and not _VERSION_PATTERN.match(version):
        failures.append(
            f"search_index_version {version!r} is not a well-formed search-index-v1 version"
        )
    snapshot_date = catalog.get("snapshot_date")
    if isinstance(version, str) and isinstance(snapshot_date, str):
        expected = search_index_version(entries, snapshot_date)
        if version != expected:
            failures.append(
                f"search_index_version {version!r} does not match the artifact's own "
                f"recomputed content (expected {expected!r})"
            )

    seen_pairs: set[tuple[str, str]] = set()
    duplicate_found = False
    album_count = 0
    contributor_count = 0

    for i, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry.keys()) != _ENTRY_KEYS:
            failures.append(f"entries[{i}] must have keys {_ENTRY_KEYS}")
            continue

        kind = entry.get("kind")
        if kind not in _VALID_KINDS:
            failures.append(f"entries[{i}] kind must be one of {sorted(_VALID_KINDS)}")
            continue

        raw_id = entry.get("id")
        if not isinstance(raw_id, str) or not raw_id:
            failures.append(f"entries[{i}] id must be a non-empty string")
            continue

        if not isinstance(entry.get("label"), str) or not entry["label"]:
            failures.append(f"entries[{i}] label must be a non-empty string")

        sublabel = entry.get("sublabel")
        if sublabel is not None and not isinstance(sublabel, str):
            failures.append(f"entries[{i}] sublabel must be a string or null")

        state = entry.get("state")
        if state not in _VALID_STATES:
            failures.append(f"entries[{i}] state must be one of {sorted(_VALID_STATES)}")

        pair = (kind, raw_id)
        if pair in seen_pairs:
            duplicate_found = True
        seen_pairs.add(pair)

        if kind == "album":
            album_count += 1
            if raw_id not in catalog_album_ids:
                failures.append(f"entries[{i}] album {raw_id!r} is not in the canonical catalog")
        elif kind == "contributor":
            contributor_count += 1
            try:
                artist_id: int | None = int(raw_id)
            except ValueError:
                artist_id = None
            if artist_id not in contributor_artist_ids:
                failures.append(
                    f"entries[{i}] contributor {raw_id!r} is not a published contributor "
                    f"in the contributor index"
                )

    if duplicate_found:
        failures.append("entries must not repeat the same (kind, id) pair")
    if album_count != len(catalog_album_ids):
        failures.append(
            f"entries has {album_count} album entries but the catalog has "
            f"{len(catalog_album_ids)} albums -- every catalog album must be indexed"
        )
    if contributor_count != len(contributor_artist_ids):
        failures.append(
            f"entries has {contributor_count} contributor entries but the contributor index "
            f"has {len(contributor_artist_ids)} contributors -- every contributor must be indexed"
        )

    return failures
