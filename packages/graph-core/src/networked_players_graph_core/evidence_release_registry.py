"""Build the public evidence-release registry (ADR 0058): a deduplicated,
addressable lookup of every release id that can appear as evidence anywhere
in the product -- the union of `challenge.v2.json`'s releases,
`routes/rounds.v1.json`'s releases, and every distinct `evidence_release_id`
in the pathfinding graph. The pathfinding graph's broader ego network
reaches far more releases than the other two artifacts describe on their
own (measured: over 17,000 release ids reachable only through it) -- this
registry is what lets any of those hops render a real evidence card
(title/year/cover/source) instead of a bare release id.

Release-level metadata for ids already covered by `challenge.v2.json`/
`routes/rounds.v1.json` comes straight from there. Metadata for the
remaining ids comes from `CreditGraph.releases_for_ids`, one batched query
covering every missing id -- not one query per id, which would dominate
build time at this scale.

Shipped as PARALLEL ARRAYS, not an array of `{key: value, ...}` objects --
the same compactness principle `pathfinding_graph.py` already documents
(measured ~15x smaller gzip at CSR-graph scale); this registry is two
orders of magnitude past `contributor-index`/`album-art`'s object-array
scale and closer to the CSR graph's own scale.
"""

from __future__ import annotations

import re
from typing import Any

from networked_players_contracts.canonical import content_hash

from .graph import CreditGraph

_YEAR_PATTERN = re.compile(r"(\d{4})")

_FIELD_ARRAYS = (
    "release_ids",
    "titles",
    "years",
    "countries",
    "master_ids",
    "source_urls",
    "cover_uri150s",
    "relation_to_catalog_album_ids",
)


def _extract_year(released: Any) -> int | None:
    """`released` is free-text on the underlying Discogs data (`"1989-06-06"`,
    `"1995"`, or null) -- pull the leading 4-digit year, discarding anything
    implausible rather than trusting it blindly."""
    if not released:
        return None
    match = _YEAR_PATTERN.match(str(released))
    if not match:
        return None
    year = int(match.group(1))
    return year if 1900 <= year <= 2100 else None


def evidence_release_registry_version(payload: dict[str, Any], snapshot_date: str) -> str:
    """Content hash over every published field -- a fingerprinted content
    pool, like `pathfinding_graph_version`, not an order-insensitive lookup
    index (release_ids are always sorted, so this is still deterministic
    regardless)."""
    identity = {field: payload[field] for field in _FIELD_ARRAYS}
    digest = content_hash(identity, length=12)
    return f"evidence-release-registry-v1-{snapshot_date}-{digest}"


def build_evidence_release_registry(
    graph: CreditGraph | None,
    *,
    challenge: dict[str, Any],
    routes_rounds: dict[str, Any],
    pathfinding_graph: dict[str, Any],
    album_art: dict[str, Any],
    catalog: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    """Deterministic given the same four already-published artifacts plus
    the one-hop dataset `graph` is opened against. `graph` may be `None`
    only when every release id the union needs is already covered by
    `challenge`/`routes_rounds` (real production builds always need a real
    graph -- the pathfinding graph's ego network always reaches releases
    neither of those cover). Raises `ValueError` if a release id can't be
    resolved anywhere -- a real data-integrity problem (the pathfinding
    graph referencing a release absent from this same one-hop dataset),
    never silently papered over with a placeholder."""
    catalog_version = catalog["catalog_version"]
    snapshot_date = catalog["snapshot_date"]

    metadata_by_id: dict[int, dict[str, Any]] = {}
    for release in (*challenge.get("releases", []), *routes_rounds.get("releases", [])):
        metadata_by_id.setdefault(int(release["release_id"]), release)

    pathfinding_ids = {int(rid) for rid in pathfinding_graph.get("evidence_release_ids", [])}
    all_ids = set(metadata_by_id) | pathfinding_ids

    missing_ids = sorted(all_ids - set(metadata_by_id))
    if missing_ids:
        if graph is None:
            raise ValueError(
                f"{len(missing_ids)} release id(s) are only reachable via the pathfinding "
                "graph and need a real CreditGraph to resolve; graph was None"
            )
        fetched = graph.releases_for_ids(missing_ids)
        unresolved = [rid for rid in missing_ids if rid not in fetched]
        if unresolved:
            raise ValueError(
                f"{len(unresolved)} release id(s) referenced by the pathfinding graph were "
                f"not found in the one-hop dataset's releases table: {unresolved[:5]}"
                f"{'...' if len(unresolved) > 5 else ''}"
            )
        metadata_by_id.update(fetched)

    catalog_album_by_release: dict[int, str] = {
        int(a["main_release_id"]): str(a["id"]) for a in catalog.get("albums", [])
    }
    cover_by_release: dict[int, str] = {
        int(a["main_release_id"]): str(a["uri150"]) for a in album_art.get("albums", [])
    }

    release_ids = sorted(all_ids)
    titles: list[str] = []
    years: list[int | None] = []
    countries: list[str | None] = []
    master_ids: list[int | None] = []
    source_urls: list[str] = []
    cover_uri150s: list[str | None] = []
    relation_to_catalog_album_ids: list[str | None] = []

    for release_id in release_ids:
        meta = metadata_by_id[release_id]
        titles.append(str(meta["title"]))
        years.append(_extract_year(meta.get("released")))
        countries.append(meta.get("country"))
        master_id = meta.get("master_id")
        master_ids.append(int(master_id) if master_id is not None else None)
        source_urls.append(str(meta["source_url"]))
        cover_uri150s.append(cover_by_release.get(release_id))
        relation_to_catalog_album_ids.append(catalog_album_by_release.get(release_id))

    payload: dict[str, Any] = {
        "schema_version": 1,
        "catalog_version": catalog_version,
        "generated_at": generated_at,
        "source": (
            "Union of apps/web/public/data/challenge.v2.json, routes/rounds.v1.json, and "
            "every evidence_release_id in pathfinding/graph.v2.json -- release-level metadata "
            "for ids not already covered by the first two comes from the one-hop dataset. "
            "See docs/DATA_AND_RIGHTS.md."
        ),
        "license": (
            "Derived from the Discogs monthly CC0 data dumps. Cover art (where present) is "
            "hotlinked from Discogs' own CDN, never rehosted. See docs/DATA_AND_RIGHTS.md."
        ),
        "release_ids": release_ids,
        "titles": titles,
        "years": years,
        "countries": countries,
        "master_ids": master_ids,
        "source_urls": source_urls,
        "cover_uri150s": cover_uri150s,
        "relation_to_catalog_album_ids": relation_to_catalog_album_ids,
    }
    payload["evidence_release_registry_version"] = evidence_release_registry_version(
        payload, snapshot_date
    )
    return payload
