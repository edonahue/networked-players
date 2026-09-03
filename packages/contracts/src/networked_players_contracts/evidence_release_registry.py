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

#: The schema version new builds emit. Older payloads still validate --
#: see `EVIDENCE_RELEASE_REGISTRY_SCHEMA_VERSIONS`.
EVIDENCE_RELEASE_REGISTRY_SCHEMA_VERSION = 2
EVIDENCE_RELEASE_REGISTRY_SCHEMA_VERSIONS = frozenset({1, 2})

_VERSION_PATTERN_BY_SCHEMA = {
    1: re.compile(r"^evidence-release-registry-v1-[0-9A-Za-z]+-[0-9a-f]{12}$"),
    2: re.compile(r"^evidence-release-registry-v2-[0-9A-Za-z]+-[0-9a-f]{12}$"),
}
_APPROVED_COVER_HOST = "i.discogs.com"

#: Format-descriptor caveat flags, v2. Each entry is `(flag_name,
#: descriptors)`: the flag is set when the release carries ANY of those
#: literal `release_formats.descriptions` values.
#:
#: These say what a release IS TAGGED AS, never what it is. Discogs format
#: descriptors are reliable for EXCLUSION and not for confirmation --
#: `docs/RELEASE_FORMAT_RESEARCH.md` measured 94.7% of a known
#: false-positive population carrying only a bare `Album` descriptor -- so
#: there is deliberately no `studio_album` flag and no positive quality
#: enum. The absence of every flag means "nothing here warrants a caveat",
#: which is a much weaker and much more defensible claim.
#:
#: Order is the BIT ORDER and is therefore load-bearing: `flags & 1` is
#: always `compilation`. Append only; never reorder or remove.
#:
#: `single`/`ep` (graph-expansion Phase 0 slice 0-B, ADR 0069) added at the
#: end for exactly this reason -- an evidence release tagged with either
#: descriptor is a real release, just not a studio album in its own right,
#: so it is presentable with an honest kind caveat rather than silently
#: treated as clean full-album evidence. `live_title_signal` (also part of
#: the plan's registry-kinds list) is deliberately NOT added here: it is a
#: title-text heuristic (`catalog_audit.py`'s `_TITLE_SIGNAL_PATTERN`), not
#: a `release_formats.descriptions` value, so it needs a different code path
#: than this descriptor-matching mechanism -- left for a follow-up rather
#: than forced into a mechanism that doesn't fit it.
CAVEAT_FLAG_DESCRIPTORS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("compilation", ("Compilation",)),
    ("mixed", ("Mixed",)),
    ("promo", ("Promo",)),
    ("reissue", ("Reissue", "Repress")),
    ("sampler", ("Sampler",)),
    ("unofficial", ("Unofficial Release",)),
    ("single", ("Single", "Maxi-Single")),
    ("ep", ("EP", "Mini-Album")),
)
CAVEAT_FLAG_NAMES: tuple[str, ...] = tuple(name for name, _ in CAVEAT_FLAG_DESCRIPTORS)
#: Every bit that can legitimately be set -- anything outside this is a
#: malformed payload, not an unknown-but-tolerable future flag, because the
#: registry publishes its own `caveat_flag_names` legend alongside.
CAVEAT_FLAGS_MASK = (1 << len(CAVEAT_FLAG_DESCRIPTORS)) - 1


def caveat_flags_for_descriptors(descriptors: frozenset[str] | set[str]) -> int:
    """The v2 bitmask for one release's unioned format descriptors.

    An empty descriptor set yields 0, which reads as "no caveat" -- correct
    for a release genuinely tagged with nothing notable, and also what a
    dataset generation with no `release_formats` table produces. That
    ambiguity is why the flags are only ever used to de-prefer and to
    caveat, never to promote.
    """
    flags = 0
    for bit, (_, values) in enumerate(CAVEAT_FLAG_DESCRIPTORS):
        if any(value in descriptors for value in values):
            flags |= 1 << bit
    return flags


_BASE_TOP_LEVEL_KEYS = frozenset(
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
_V2_ONLY_KEYS = frozenset({"caveat_flags", "caveat_flag_names"})

_BASE_FIELD_ARRAYS = (
    "release_ids",
    "titles",
    "years",
    "countries",
    "master_ids",
    "source_urls",
    "cover_uri150s",
    "relation_to_catalog_album_ids",
)
_V2_FIELD_ARRAYS = (*_BASE_FIELD_ARRAYS, "caveat_flags")


def _field_arrays(schema_version: Any) -> tuple[str, ...]:
    return _V2_FIELD_ARRAYS if schema_version == 2 else _BASE_FIELD_ARRAYS


def evidence_release_registry_version(registry: dict[str, Any], snapshot_date: str) -> str:
    """Recomputation mirror of the generation-time function in
    `networked_players_graph_core.evidence_release_registry` -- which
    imports THIS one, so the two cannot drift.

    The identity pool is schema-aware: a v2 payload folds `caveat_flags`
    in, so adding the field necessarily changes the version string rather
    than leaving a v1 hash describing content it never saw.
    """
    schema_version = registry.get("schema_version")
    identity = {field: registry.get(field) for field in _field_arrays(schema_version)}
    label = "v2" if schema_version == 2 else "v1"
    digest = content_hash(identity, length=12)
    return f"evidence-release-registry-{label}-{snapshot_date}-{digest}"


def evidence_release_registry_failures(registry: Any, catalog: Any) -> list[str]:
    """Every contract failure in an evidence-release registry, validated
    against the canonical catalog it claims to belong to."""
    failures: list[str] = []
    if not isinstance(registry, dict):
        return ["evidence-release-registry must be an object"]
    if not isinstance(catalog, dict):
        return ["catalog must be an object"]

    schema_version = registry.get("schema_version")
    if schema_version not in EVIDENCE_RELEASE_REGISTRY_SCHEMA_VERSIONS:
        failures.append(
            f"schema_version must be one of {sorted(EVIDENCE_RELEASE_REGISTRY_SCHEMA_VERSIONS)}"
        )
    expected_keys = _BASE_TOP_LEVEL_KEYS | (_V2_ONLY_KEYS if schema_version == 2 else frozenset())
    if set(registry.keys()) != expected_keys:
        failures.append(
            f"evidence-release-registry has unexpected top-level keys: {sorted(registry.keys())}"
        )
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

    for field in _field_arrays(schema_version)[1:]:
        values = registry.get(field)
        if not isinstance(values, list):
            failures.append(f"{field} must be an array")
        elif len(values) != len(release_ids):
            failures.append(
                f"{field} has length {len(values)}, expected {len(release_ids)} "
                "(must be parallel to release_ids)"
            )

    version = registry.get("evidence_release_registry_version")
    pattern = (
        _VERSION_PATTERN_BY_SCHEMA.get(schema_version)
        if isinstance(schema_version, int) and not isinstance(schema_version, bool)
        else None
    )
    if pattern is not None and isinstance(version, str) and not pattern.match(version):
        failures.append(
            f"evidence_release_registry_version {version!r} is not a well-formed "
            f"evidence-release-registry-v{schema_version} version"
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

    if schema_version == 2:
        flag_names = registry.get("caveat_flag_names")
        if flag_names != list(CAVEAT_FLAG_NAMES):
            # Not merely "some list of strings": the legend is the bit
            # order, so a payload whose legend disagrees with this contract
            # is one whose `caveat_flags` integers mean something else.
            failures.append(
                f"caveat_flag_names must be exactly {list(CAVEAT_FLAG_NAMES)} "
                f"(the published bit order), got {flag_names!r}"
            )
        flags = registry.get("caveat_flags")
        if isinstance(flags, list):
            for i, value in enumerate(flags):
                if not isinstance(value, int) or isinstance(value, bool):
                    failures.append(f"caveat_flags[{i}] must be an integer")
                elif value < 0 or value & ~CAVEAT_FLAGS_MASK:
                    failures.append(
                        f"caveat_flags[{i}] {value!r} sets bits outside the published "
                        f"legend (mask {CAVEAT_FLAGS_MASK})"
                    )

    return failures
