"""Build the canonical album-credit-membership artifact (ADR 0058): for each
catalog album, the definitive list of contributors credited on that album's
own `main_release_id` -- the same release `assemble_album_catalog` already
chose, never re-derived here.

This exists because "who's credited on album X" was previously answered
three different, disagreeing ways across `challenge.v2.json` (denylist
only), Connection Guesser/Record Routes (denylist + performer allowlist),
and the pathfinding graph (denylist only, scoped to an artist ego network,
not any specific album's release). This module fixes the album-membership
question specifically -- it does not replace or re-implement either the
traversal denylist (`graph.py`) or the game-round allowlist
(`eligibility.py`); both keep governing what they already govern.

Uses `CreditGraph.credit_rows_for_releases`, the same linked-only,
playable-identity, non-placeholder query `connection_rounds.py` and
`role_mode_candidates.py` already use for equivalent "who's credited across
these releases" questions -- one batched query across every album's
`main_release_id`, not one query per album.
"""

from __future__ import annotations

from typing import Any

from networked_players_contracts.canonical import content_hash

from .graph import CreditGraph

_CREDIT_FIELDS = (
    "artist_id",
    "name",
    "anv",
    "role_text",
    "credit_scope",
    "track_position",
    "track_title",
)


def album_credit_membership_version(albums: list[dict[str, Any]], snapshot_date: str) -> str:
    """Content hash over every album's `main_release_id` and full credit
    list -- order-sensitive within an album's `credits[]` (a fingerprinted
    content pool, like `pathfinding_graph_version`, not an order-insensitive
    lookup index like `contributor_index_version`)."""
    identity = [
        {
            "album_id": a["album_id"],
            "main_release_id": a["main_release_id"],
            "credits": a["credits"],
        }
        for a in albums
    ]
    digest = content_hash(identity, length=12)
    return f"album-credit-membership-v1-{snapshot_date}-{digest}"


def build_album_credit_membership(
    graph: CreditGraph,
    catalog: dict[str, Any],
    *,
    generated_at: str,
) -> dict[str, Any]:
    """Deterministic given a fixed graph snapshot and catalog. Raises
    `ValueError` if the catalog has no albums -- there is nothing to build.
    An album whose `main_release_id` has zero eligible credit rows still
    appears in the output with an empty `credits` list (never dropped
    silently); that is real, honest evidence the release's credits are
    thin, not a bug in this builder."""
    catalog_albums = catalog.get("albums", [])
    if not catalog_albums:
        raise ValueError("catalog has no albums to build album-credit-membership from")

    release_ids = sorted({int(a["main_release_id"]) for a in catalog_albums})
    rows_by_release = graph.credit_rows_for_releases(release_ids)

    albums: list[dict[str, Any]] = []
    for album in catalog_albums:
        album_id = str(album["id"])
        main_release_id = int(album["main_release_id"])
        rows = rows_by_release.get(main_release_id, [])
        credits = sorted(
            ({field: row[field] for field in _CREDIT_FIELDS} for row in rows),
            key=lambda c: (
                int(c["artist_id"]),
                c["track_position"] or "",
                c["role_text"] or "",
            ),
        )
        albums.append(
            {
                "album_id": album_id,
                "main_release_id": main_release_id,
                "credits": credits,
            }
        )

    albums.sort(key=lambda a: a["album_id"])
    catalog_version = catalog["catalog_version"]
    snapshot_date = catalog["snapshot_date"]
    version = album_credit_membership_version(albums, snapshot_date)

    return {
        "schema_version": 1,
        "catalog_version": catalog_version,
        "album_credit_membership_version": version,
        "generated_at": generated_at,
        "source": (
            "Derived directly from the credited personnel of each catalog album's own "
            "main_release_id (playable, linked, non-placeholder credits only). See "
            "docs/DATA_AND_RIGHTS.md."
        ),
        "license": (
            "Derived from the Discogs monthly CC0 data dumps. See docs/DATA_AND_RIGHTS.md."
        ),
        "albums": albums,
    }
