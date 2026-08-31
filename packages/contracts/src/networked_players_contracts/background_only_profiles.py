"""Canonical, dependency-free validation for the public
background-only-profiles artifact.

`background-only-profiles-v1` (`apps/web/public/data/contributors/
background-only-profiles.v1.json`, `data/contracts/
background-only-profiles-v1.md`, ADR 0048/0060 addendum) is a companion
artifact to `contributor-index-v1`, listing the `artist_id`s whose entire
observed role vocabulary is background-engineering (Mastered By/Recorded
By/Mixed By) or non-substantive. Publishing this as a wholly separate
artifact -- rather than a new required key on `contributor-index-v1` --
follows the exact reasoning `album_hop_distances.py` already documents:
that index's contract is validated as an exact top-level key set, so
widening it in place would be a real breaking change hiding behind an
unchanged `schema_version`.

It also closes a real gap `contributor-index-v1`'s own published
`role_text_examples` couldn't: that field is capped to the five most
frequent role strings, so inferring "background-only" from it alone (as
`apps/web/src/game/roleTaxonomy.ts`'s `isBackgroundOnlyRoleProfile` does,
for lack of anything better) can miss a rarer, lower-frequency substantive
credit truncated from the sample. This artifact is instead built from the
full, uncapped role-text data the generation-time builder has on hand.

Pure Python (no lxml/pyarrow/duckdb), safe for the Pi fleet and the web
build to independently verify an already-generated artifact against the
canonical catalog and contributor index it claims to belong to.
"""

from __future__ import annotations

import re
from typing import Any

from .canonical import content_hash

BACKGROUND_ONLY_PROFILES_SCHEMA_VERSION = 1

_VERSION_PATTERN = re.compile(r"^background-only-profiles-v1-[0-9A-Za-z]+-[0-9a-f]{12}$")

_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "catalog_version",
        "background_only_profiles_version",
        "generated_at",
        "source",
        "license",
        "artist_ids",
    }
)


def background_only_profiles_version(artist_ids: list[Any], snapshot_date: str) -> str:
    """Recomputation mirror of the generation-time function in
    `networked_players_graph_core.contributor_index` -- duplicated here
    deliberately (this package stays dependency-free of graph-core, the
    same split every other contract/builder pair in this project already
    uses)."""
    well_formed = sorted(a for a in artist_ids if isinstance(a, int) and not isinstance(a, bool))
    return f"background-only-profiles-v1-{snapshot_date}-{content_hash(well_formed, length=12)}"


def background_only_profiles_failures(
    artifact: Any, catalog: Any, contributor_index: Any
) -> list[str]:
    """Every contract failure in a background-only-profiles artifact,
    validated against the canonical catalog and the contributor index it's
    a companion to. An empty `artist_ids` list is valid."""
    failures: list[str] = []
    if not isinstance(artifact, dict):
        return ["background-only-profiles artifact must be an object"]
    if not isinstance(catalog, dict):
        return ["catalog must be an object"]
    if not isinstance(contributor_index, dict):
        return ["contributor_index must be an object"]

    if set(artifact.keys()) != _TOP_LEVEL_KEYS:
        failures.append(f"artifact has unexpected top-level keys: {sorted(artifact.keys())}")
    if artifact.get("schema_version") != BACKGROUND_ONLY_PROFILES_SCHEMA_VERSION:
        failures.append(f"schema_version must be {BACKGROUND_ONLY_PROFILES_SCHEMA_VERSION}")
    for field_name in (
        "catalog_version",
        "background_only_profiles_version",
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

    contributor_artist_ids = {
        c.get("artist_id") for c in contributor_index.get("contributors", []) if isinstance(c, dict)
    }

    artist_ids = artifact.get("artist_ids")
    if not isinstance(artist_ids, list):
        failures.append("artist_ids must be an array")
        artist_ids = []

    version = artifact.get("background_only_profiles_version")
    if isinstance(version, str) and not _VERSION_PATTERN.match(version):
        failures.append(
            f"background_only_profiles_version {version!r} is not a well-formed "
            f"background-only-profiles-v1 version"
        )
    snapshot_date = catalog.get("snapshot_date")
    if isinstance(snapshot_date, str) and isinstance(version, str):
        expected = background_only_profiles_version(artist_ids, snapshot_date)
        if version != expected:
            failures.append(
                f"background_only_profiles_version {version!r} does not match the artifact's "
                f"own recomputed content (expected {expected!r})"
            )

    # Tracked in the same pass so a malformed entry (non-int artist_id, e.g.
    # a list/dict from corrupt JSON) never reaches a set operation that
    # could raise instead of reporting a clean failure -- the same
    # discipline `album_hop_distances_failures` already uses.
    seen: set[int] = set()
    duplicate_found = False
    well_formed_ids: list[int] = []
    all_well_formed = True

    for i, raw_artist_id in enumerate(artist_ids):
        if not isinstance(raw_artist_id, int) or isinstance(raw_artist_id, bool):
            failures.append(f"artist_ids[{i}] must be an integer")
            all_well_formed = False
            continue
        artist_id = raw_artist_id
        if artist_id not in contributor_artist_ids:
            failures.append(
                f"artist_ids[{i}] {artist_id!r} is not a published contributor in the "
                f"contributor index"
            )
        if artist_id in seen:
            duplicate_found = True
        seen.add(artist_id)
        well_formed_ids.append(artist_id)

    if duplicate_found:
        failures.append("artist_ids must not repeat the same artist_id")
    if all_well_formed and well_formed_ids != sorted(well_formed_ids):
        failures.append("artist_ids must be sorted ascending")

    return failures
