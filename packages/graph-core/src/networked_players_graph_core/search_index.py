"""Build the public site-search index (graph-expansion Phase 1, plan
section 7): a small, flat list of searchable destinations, built entirely
from two already-published artifacts (the catalog, the contributor index)
-- never a fresh corpus query, the same discipline `contributor_index.py`'s
own module docstring establishes for that artifact.

Deliberately scoped to Phase 1's own boundary: every entry's `state` is
`"present"` here -- `"candidate"` (known-but-unpublished albums, plan
section 4/7) needs `catalog/candidates.v1.json`, a Phase 3 deliverable this
module has no dependency on. The field is included now, always
`"present"`, so Phase 3 can add `"candidate"` entries later without a
schema-version bump.

Tokenization/normalization (lowercasing, diacritic folding, prefix
matching) is deliberately NOT done here -- `entries` stores only
`label`/`sublabel` text, and `apps/web/src/game/siteSearch.ts` normalizes
both the query and every entry's text at query time. Precomputing and
storing token arrays here would duplicate that logic in two languages and
bloat the artifact for a search space this small (a few hundred entries);
one normalization implementation, applied at query time, is the same
"one truth per fact" principle every other artifact in this project
already follows.
"""

from __future__ import annotations

from typing import Any, Literal

from networked_players_contracts.canonical import content_hash

EntryKind = Literal["album", "contributor"]


def search_index_version(entries: list[dict[str, Any]], snapshot_date: str) -> str:
    """Order-insensitive content hash (a lookup index, like
    `contributor_index_version`, not a fingerprinted content pool): only
    the load-bearing identity fields move the version, not incidental list
    ordering."""
    identity = sorted(
        (
            {
                "kind": e["kind"],
                "id": e["id"],
                "label": e["label"],
                "sublabel": e["sublabel"],
                "state": e["state"],
            }
            for e in entries
        ),
        key=lambda e: (e["kind"], e["id"]),
    )
    digest = content_hash(identity, length=12)
    return f"search-index-v1-{snapshot_date}-{digest}"


def build_search_index(
    *,
    catalog: dict[str, Any],
    contributor_index: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    """Deterministic given the same two already-published artifacts. Raises
    `ValueError` on a `catalog_version` mismatch -- a search index belongs
    to exactly one catalog generation, the same rule every other catalog-
    derived artifact enforces."""
    catalog_version = catalog["catalog_version"]
    snapshot_date = catalog["snapshot_date"]
    contributor_catalog_version = contributor_index.get("catalog_version")
    if contributor_catalog_version != catalog_version:
        raise ValueError(
            f"contributor_index's catalog_version {contributor_catalog_version!r} "
            f"does not match the catalog's catalog_version {catalog_version!r}"
        )

    entries: list[dict[str, Any]] = []
    for album in catalog.get("albums", []):
        entries.append(
            {
                "kind": "album",
                "id": str(album["id"]),
                "label": str(album["title"]),
                "sublabel": str(album["artist"]),
                "state": "present",
            }
        )
    for contributor in contributor_index.get("contributors", []):
        entries.append(
            {
                "kind": "contributor",
                "id": str(contributor["artist_id"]),
                "label": str(contributor["name"]),
                "sublabel": None,
                "state": "present",
            }
        )

    # Deterministic build order: albums first (catalog's own order),
    # contributors second (contributor index's own order) -- ranking at
    # QUERY time is siteSearch.ts's job, not this artifact's; this is only
    # about making a byte-identical rebuild from the same inputs
    # reproducible, not a claim about display order.
    payload: dict[str, Any] = {
        "schema_version": 1,
        "catalog_version": catalog_version,
        "contributor_index_version": contributor_index.get("contributor_index_version"),
        "generated_at": generated_at,
        "source": (
            "Derived from apps/web/public/data/catalog/albums.v1.json and "
            "apps/web/public/data/contributors/index.v1.json -- no fresh "
            "full-corpus query. See docs/DATA_AND_RIGHTS.md."
        ),
        "license": (
            "Derived from the Discogs monthly CC0 data dumps via the two published "
            "artifacts above. See docs/DATA_AND_RIGHTS.md."
        ),
        "entries": entries,
    }
    payload["search_index_version"] = search_index_version(entries, snapshot_date)
    return payload
