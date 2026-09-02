"""Canonical, dependency-free validation for the public contributor index.

The contributor index (`apps/web/public/data/contributors/index.v1.json`,
`data/contracts/contributor-index-v1.md`, ADR 0048) is a small, deterministic
lookup built entirely from two already-published artifacts (`challenge.v3.json`
and `routes/{universe,rounds}.v1.json`) -- never a fresh full-corpus graph
query. It belongs to exactly one catalog generation, the same rule
`album_art_failures` enforces for the album-art registry.

Pure Python (no lxml/pyarrow/duckdb), safe for the Pi fleet and the web build
to independently verify an already-generated index against the canonical
catalog it claims to belong to.
"""

from __future__ import annotations

import re
from typing import Any

from .canonical import content_hash

CONTRIBUTOR_INDEX_SCHEMA_VERSION = 1

_INDEX_VERSION_PATTERN = re.compile(r"^contributor-index-v1-[0-9A-Za-z]+-[0-9a-f]{12}$")

_VALID_ROLE_CATEGORIES = frozenset(
    {
        "vocals",
        "strings",
        "percussion_keys",
        "brass_woodwind",
        "production",
        "engineering",
        "arrangement",
        "composition",
        "rework",
        "packaging_business",
        # Added 2026-08-27 (Phase 7 preflight) alongside
        # `role_taxonomy.RoleCategory.AUDIOVISUAL_PRODUCTION`. Purely additive:
        # every value an already-published index carries stays valid, so this
        # accepts both the current artifact and the next regeneration.
        "audiovisual_production",
        # Added 2026-09-01 (ADR 0068) alongside `role_taxonomy.RoleCategory.
        # PERFORMANCE` -- same purely-additive discipline as above.
        "performance",
        "unknown",
    }
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
        "contributor_index_version",
        "generated_at",
        "source",
        "license",
        "contributors",
    }
)
_CONTRIBUTOR_KEYS = frozenset(
    {
        "artist_id",
        "name",
        "role_categories",
        "role_text_examples",
        "albums",
        "decade_activity",
        "connection_count",
        "neighboring_contributor_ids",
        "evidence",
        "interesting_next_step",
    }
)
_EVIDENCE_KEYS = frozenset({"release_id", "role_text"})
_INTERESTING_NEXT_STEP_KEYS = frozenset({"artist_id", "reason"})


def contributor_index_version(contributors: list[dict[str, Any]], snapshot_date: str) -> str:
    """Recomputation mirror of the generation-time function in
    `networked_players_graph_core.contributor_index` -- duplicated here
    deliberately (this package stays dependency-free of graph-core, the same
    split every other contract/builder pair in this project already uses)."""
    identity = sorted(
        (
            {
                "artist_id": c.get("artist_id"),
                "name": c.get("name"),
                "role_categories": c.get("role_categories"),
                "albums": c.get("albums"),
                "evidence": c.get("evidence"),
            }
            for c in contributors
            if isinstance(c, dict)
        ),
        key=lambda c: (c["artist_id"] is None, c["artist_id"]),
    )
    return f"contributor-index-v1-{snapshot_date}-{content_hash(identity, length=12)}"


def contributor_index_failures(index: Any, catalog: Any) -> list[str]:
    """Every contract failure in a contributor index, validated against the
    canonical catalog and the album ids it claims to reference. An empty
    `contributors` list is valid (an empty index)."""
    failures: list[str] = []
    if not isinstance(index, dict):
        return ["contributor index must be an object"]
    if not isinstance(catalog, dict):
        return ["catalog must be an object"]

    if set(index.keys()) != _TOP_LEVEL_KEYS:
        failures.append(f"index has unexpected top-level keys: {sorted(index.keys())}")
    if index.get("schema_version") != CONTRIBUTOR_INDEX_SCHEMA_VERSION:
        failures.append(f"schema_version must be {CONTRIBUTOR_INDEX_SCHEMA_VERSION}")
    for field_name in (
        "catalog_version",
        "contributor_index_version",
        "generated_at",
        "source",
        "license",
    ):
        if not index.get(field_name):
            failures.append(f"{field_name} is required and must be non-empty")

    catalog_version = catalog.get("catalog_version")
    if index.get("catalog_version") != catalog_version:
        failures.append(
            f"index catalog_version {index.get('catalog_version')!r} does not match the "
            f"canonical catalog's catalog_version {catalog_version!r} -- a contributor index "
            f"belongs to exactly one catalog generation"
        )

    catalog_album_ids = {a.get("id") for a in catalog.get("albums", []) if isinstance(a, dict)}

    contributors = index.get("contributors")
    if not isinstance(contributors, list):
        failures.append("contributors must be an array")
        contributors = []

    index_version = index.get("contributor_index_version")
    if isinstance(index_version, str) and not _INDEX_VERSION_PATTERN.match(index_version):
        failures.append(
            f"contributor_index_version {index_version!r} is not a well-formed "
            f"contributor-index-v1 version"
        )
    snapshot_date = catalog.get("snapshot_date")
    if isinstance(snapshot_date, str) and isinstance(index_version, str):
        expected = contributor_index_version(contributors, snapshot_date)
        if index_version != expected:
            failures.append(
                f"contributor_index_version {index_version!r} does not match the index's own "
                f"recomputed content (expected {expected!r})"
            )

    seen_artist_ids: set[Any] = set()
    all_artist_ids = {
        c.get("artist_id") for c in contributors if isinstance(c, dict) and "artist_id" in c
    }

    for i, contributor in enumerate(contributors):
        if not isinstance(contributor, dict):
            failures.append(f"contributors[{i}] must be an object")
            continue
        if set(contributor.keys()) != _CONTRIBUTOR_KEYS:
            failures.append(f"contributors[{i}] has unexpected keys: {sorted(contributor.keys())}")

        artist_id = contributor.get("artist_id")
        if not isinstance(artist_id, int) or isinstance(artist_id, bool):
            failures.append(f"contributors[{i}] artist_id must be an integer")
        elif artist_id in seen_artist_ids:
            failures.append(f"contributors[{i}] duplicate artist_id {artist_id!r}")
        seen_artist_ids.add(artist_id)

        if not isinstance(contributor.get("name"), str) or not contributor.get("name"):
            failures.append(f"contributors[{i}] name must be a non-empty string")

        categories = contributor.get("role_categories")
        if not isinstance(categories, list) or not categories:
            failures.append(f"contributors[{i}] role_categories must be a non-empty array")
        else:
            for category in categories:
                if category not in _VALID_ROLE_CATEGORIES:
                    failures.append(
                        f"contributors[{i}] role_categories contains an unknown category "
                        f"{category!r}"
                    )
            if categories != sorted(set(categories)):
                failures.append(f"contributors[{i}] role_categories must be sorted and deduped")

        role_examples = contributor.get("role_text_examples")
        if not isinstance(role_examples, list):
            failures.append(f"contributors[{i}] role_text_examples must be an array")

        albums = contributor.get("albums")
        if not isinstance(albums, list) or not albums:
            failures.append(f"contributors[{i}] albums must be a non-empty array")
        else:
            for album_id in albums:
                if album_id not in catalog_album_ids:
                    failures.append(
                        f"contributors[{i}] album {album_id!r} is not in the canonical catalog"
                    )
            if albums != sorted(albums):
                failures.append(f"contributors[{i}] albums must be sorted")

        decades = contributor.get("decade_activity")
        if not isinstance(decades, list):
            failures.append(f"contributors[{i}] decade_activity must be an array")
        elif decades != sorted(decades):
            failures.append(f"contributors[{i}] decade_activity must be sorted")

        connection_count = contributor.get("connection_count")
        if not isinstance(connection_count, int) or isinstance(connection_count, bool):
            failures.append(f"contributors[{i}] connection_count must be an integer")
        elif connection_count < 0:
            failures.append(f"contributors[{i}] connection_count must not be negative")

        neighbors = contributor.get("neighboring_contributor_ids")
        if not isinstance(neighbors, list):
            failures.append(f"contributors[{i}] neighboring_contributor_ids must be an array")
        else:
            for neighbor_id in neighbors:
                if neighbor_id not in all_artist_ids:
                    failures.append(
                        f"contributors[{i}] neighboring_contributor_id {neighbor_id!r} is not "
                        f"a published contributor in this index"
                    )

        evidence = contributor.get("evidence")
        if not isinstance(evidence, list):
            failures.append(f"contributors[{i}] evidence must be an array")
        else:
            for j, entry in enumerate(evidence):
                if not isinstance(entry, dict) or set(entry.keys()) != _EVIDENCE_KEYS:
                    failures.append(
                        f"contributors[{i}] evidence[{j}] must have keys {_EVIDENCE_KEYS}"
                    )

        # ADR 0060: null is a real, valid outcome (no role-disjoint neighbor
        # exists) -- never coerced into a fabricated pick just to fill the
        # field.
        next_step = contributor.get("interesting_next_step", "MISSING")
        if next_step == "MISSING":
            failures.append(f"contributors[{i}] is missing interesting_next_step")
        elif next_step is not None:
            if not isinstance(next_step, dict) or set(next_step.keys()) != (
                _INTERESTING_NEXT_STEP_KEYS
            ):
                failures.append(
                    f"contributors[{i}] interesting_next_step must be null or have keys "
                    f"{_INTERESTING_NEXT_STEP_KEYS}"
                )
            else:
                next_id = next_step.get("artist_id")
                if next_id not in all_artist_ids:
                    failures.append(
                        f"contributors[{i}] interesting_next_step artist_id {next_id!r} is not "
                        f"a published contributor in this index"
                    )
                elif isinstance(neighbors, list) and next_id not in neighbors:
                    failures.append(
                        f"contributors[{i}] interesting_next_step artist_id {next_id!r} is not "
                        f"one of this contributor's own neighboring_contributor_ids"
                    )
                if not isinstance(next_step.get("reason"), str) or not next_step.get("reason"):
                    failures.append(
                        f"contributors[{i}] interesting_next_step reason must be a non-empty string"
                    )

    serialized = str(index)
    for forbidden in _FORBIDDEN_SUBSTRINGS:
        if forbidden in serialized:
            failures.append(f"index contains forbidden substring: {forbidden!r}")
    lowered = serialized.lower()
    for phrase in _FORBIDDEN_PHRASES:
        if phrase in lowered:
            failures.append(f"index contains forbidden inference-implying phrase: {phrase!r}")

    return failures
