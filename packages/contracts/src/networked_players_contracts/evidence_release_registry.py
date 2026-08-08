"""Canonical, dependency-free validation for the public evidence-release
registry.

The evidence-release registry
(`apps/web/public/data/evidence/release-registry.v1.json`,
`data/contracts/evidence-release-registry-v1.md`, ADR 0058) is a
deduplicated, addressable lookup of every release id that can appear as
evidence anywhere in the product. Shipped as parallel arrays, not an array
of per-release objects -- the same compactness principle
`pathfinding_graph.py` already documents.

Pure Python (no lxml/pyarrow/duckdb), safe for the Pi fleet and the web
build to independently verify an already-generated registry against the
canonical catalog it claims to belong to.
"""

from __future__ import annotations

import re
from typing import Any

from .canonical import content_hash

EVIDENCE_RELEASE_REGISTRY_SCHEMA_VERSION = 1

_VERSION_PATTERN = re.compile(r"^evidence-release-registry-v1-[0-9A-Za-z]+-[0-9a-f]{12}$")
_APPROVED_COVER_HOST = "i.discogs.com"

_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "catalog_version",
        "evidence_release_registry_version",
        "generated_at",
        "source",
        "license",
        "release_ids",
        "titles",
        "years",
        "countries",
        "master_ids",
        "source_urls",
        "cover_uri150s",
        "relation_to_catalog_album_ids",
    }
)
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


def evidence_release_registry_version(registry: dict[str, Any], snapshot_date: str) -> str:
    """Recomputation mirror of the generation-time function in
    `networked_players_graph_core.evidence_release_registry` -- duplicated
    here deliberately (this package stays dependency-free of graph-core)."""
    identity = {field: registry.get(field) for field in _FIELD_ARRAYS}
    return f"evidence-release-registry-v1-{snapshot_date}-{content_hash(identity, length=12)}"


def evidence_release_registry_failures(registry: Any, catalog: Any) -> list[str]:
    """Every contract failure in an evidence-release registry, validated
    against the canonical catalog it claims to belong to."""
    failures: list[str] = []
    if not isinstance(registry, dict):
        return ["evidence-release-registry must be an object"]
    if not isinstance(catalog, dict):
        return ["catalog must be an object"]

    if set(registry.keys()) != _TOP_LEVEL_KEYS:
        failures.append(
            f"evidence-release-registry has unexpected top-level keys: {sorted(registry.keys())}"
        )
    if registry.get("schema_version") != EVIDENCE_RELEASE_REGISTRY_SCHEMA_VERSION:
        failures.append(f"schema_version must be {EVIDENCE_RELEASE_REGISTRY_SCHEMA_VERSION}")
    for field_name in (
        "catalog_version",
        "evidence_release_registry_version",
        "generated_at",
        "source",
        "license",
    ):
        if not registry.get(field_name):
            failures.append(f"{field_name} is required and must be non-empty")

    catalog_version = catalog.get("catalog_version")
    if registry.get("catalog_version") != catalog_version:
        failures.append(
            f"evidence-release-registry catalog_version {registry.get('catalog_version')!r} "
            f"does not match the canonical catalog's catalog_version {catalog_version!r}"
        )

    catalog_album_ids = {a.get("id") for a in catalog.get("albums", []) if isinstance(a, dict)}

    release_ids = registry.get("release_ids")
    if not isinstance(release_ids, list):
        failures.append("release_ids must be an array")
        release_ids = []
    else:
        if any(not isinstance(rid, int) or isinstance(rid, bool) for rid in release_ids):
            failures.append("release_ids must contain only integers")
        elif release_ids != sorted(set(release_ids)):
            failures.append("release_ids must be sorted and deduplicated")

    for field in _FIELD_ARRAYS[1:]:
        values = registry.get(field)
        if not isinstance(values, list):
            failures.append(f"{field} must be an array")
        elif len(values) != len(release_ids):
            failures.append(
                f"{field} has length {len(values)}, expected {len(release_ids)} "
                "(must be parallel to release_ids)"
            )

    version = registry.get("evidence_release_registry_version")
    if isinstance(version, str) and not _VERSION_PATTERN.match(version):
        failures.append(
            f"evidence_release_registry_version {version!r} is not a well-formed "
            f"evidence-release-registry-v1 version"
        )
    snapshot_date = catalog.get("snapshot_date")
    if isinstance(snapshot_date, str) and isinstance(version, str):
        expected = evidence_release_registry_version(registry, snapshot_date)
        if version != expected:
            failures.append(
                f"evidence_release_registry_version {version!r} does not match the registry's "
                f"own recomputed content (expected {expected!r})"
            )

    titles = registry.get("titles")
    if not isinstance(titles, list):
        titles = []
    for i, title in enumerate(titles):
        if not isinstance(title, str) or not title:
            failures.append(f"titles[{i}] must be a non-empty string")

    years = registry.get("years")
    if not isinstance(years, list):
        years = []
    for i, year in enumerate(years):
        if year is not None and (not isinstance(year, int) or isinstance(year, bool)):
            failures.append(f"years[{i}] must be an integer or null")
        elif isinstance(year, int) and not (1900 <= year <= 2100):
            failures.append(f"years[{i}] {year!r} is outside a plausible release-year range")

    source_urls = registry.get("source_urls")
    if not isinstance(source_urls, list):
        source_urls = []
    for i, url in enumerate(source_urls):
        if not isinstance(url, str) or not url.startswith("https://"):
            failures.append(f"source_urls[{i}] must be a non-empty https:// URL")

    cover_uri150s = registry.get("cover_uri150s")
    if not isinstance(cover_uri150s, list):
        cover_uri150s = []
    for i, uri in enumerate(cover_uri150s):
        if uri is not None and (
            not isinstance(uri, str) or f"://{_APPROVED_COVER_HOST}/" not in uri
        ):
            failures.append(
                f"cover_uri150s[{i}] must be null or hotlink {_APPROVED_COVER_HOST} "
                "-- cover art is never rehosted"
            )

    relations = registry.get("relation_to_catalog_album_ids")
    if not isinstance(relations, list):
        relations = []
    for i, album_id in enumerate(relations):
        if album_id is not None and album_id not in catalog_album_ids:
            failures.append(
                f"relation_to_catalog_album_ids[{i}] {album_id!r} is not in the canonical catalog"
            )

    return failures
