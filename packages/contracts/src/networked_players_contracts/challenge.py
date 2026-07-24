"""Canonical, dependency-free validation for the challenge.v2 artifact.

challenge.v2 (`apps/web/public/data/challenge.v2.json`) is the album-centered,
evidence-preserving static challenge: an album -> artist -> album documented
credit path over a bounded one-hop working set (ADR 0012). Generation-time
validation lives in
`packages/graph-core/.../challenge.py::validate_challenge`, which delegates
to `challenge_failures` here so the two can never drift -- same pattern as
`record_routes.py`'s `validate_record_routes_artifact` ->
`record_routes_failures` (ADR 0046). `CHALLENGE_SCHEMA_VERSION` here must
agree with graph-core's own constant of the same name (each layer keeps its
own copy, same convention as every other artifact pair in this package).

Reuses `.rounds`'s `_seed_key_paths`/`_privacy_failures` for the no-leaked-
`seed`-key and forbidden-substring/phrase scan, rather than a second copy --
the same protection every other real artifact in this package already gets.

Pure Python (no lxml/pyarrow/duckdb), safe for the Pi fleet and the web build.
"""

from __future__ import annotations

from typing import Any

from .rounds import _privacy_failures, _seed_key_paths

CHALLENGE_SCHEMA_VERSION = 2

_TOP_LEVEL_KEYS = frozenset(
    {"schema_version", "provenance", "albums", "artists", "paths", "releases"}
)
# Per data/contracts/challenge-v2.md (RELEASE_SCHEMA minus `images`) plus the
# `credits` evidence array the builder adds. Must agree with graph-core's own
# `_RELEASE_KEYS` of the same name.
_RELEASE_KEYS = frozenset(
    {
        "snapshot_date",
        "release_id",
        "status",
        "title",
        "country",
        "released",
        "master_id",
        "master_is_main_release",
        "data_quality",
        "source_url",
        "credits",
    }
)
_PROVENANCE_REQUIRED = ("source", "license", "snapshot_date", "generated_by", "graph_core_version")


def challenge_failures(artifact: Any, catalog: Any | None = None) -> list[str]:
    """Return every contract failure in a challenge.v2 artifact.

    If `catalog` is given and the artifact's own `provenance.catalog_version`
    is not `None`, it must agree with `catalog["catalog_version"]`. A
    hand-written `{artist,title}` query list legitimately has no catalog to
    agree with (its own provenance note documents this) -- a `None`
    `catalog_version` is never itself a failure, with or without a `catalog`
    argument."""
    if not isinstance(artifact, dict):
        return ["challenge artifact must be an object"]

    failures: list[str] = []
    if set(artifact) != _TOP_LEVEL_KEYS:
        failures.append(f"unexpected top-level keys: {sorted(artifact)}")
    if artifact.get("schema_version") != CHALLENGE_SCHEMA_VERSION:
        failures.append(f"schema_version must be {CHALLENGE_SCHEMA_VERSION}")

    provenance = artifact.get("provenance")
    if not isinstance(provenance, dict):
        failures.append("provenance must be an object")
        provenance = {}
    else:
        for field_name in _PROVENANCE_REQUIRED:
            if not provenance.get(field_name):
                failures.append(f"provenance.{field_name} is required")

    if isinstance(catalog, dict):
        catalog_version = provenance.get("catalog_version")
        if catalog_version is not None and catalog_version != catalog.get("catalog_version"):
            failures.append(
                f"provenance.catalog_version {catalog_version!r} does not match the canonical "
                f"catalog's own {catalog.get('catalog_version')!r}"
            )

    releases = artifact.get("releases", [])
    if not isinstance(releases, list):
        failures.append("releases must be an array")
        releases = []
    release_ids: set[Any] = set()
    for release in releases:
        if not isinstance(release, dict):
            failures.append("release entry must be an object")
            continue
        if set(release) != _RELEASE_KEYS:
            failures.append(
                f"release {release.get('release_id')} has unexpected keys: {sorted(release)}"
            )
            continue
        release_ids.add(release.get("release_id"))

    artists = artifact.get("artists", [])
    if not isinstance(artists, list):
        failures.append("artists must be an array")
        artists = []
    artist_ids = {a.get("artist_id") for a in artists if isinstance(a, dict)}

    albums = artifact.get("albums", [])
    if not isinstance(albums, list):
        failures.append("albums must be an array")
        albums = []
    for album in albums:
        if not isinstance(album, dict):
            failures.append("album entry must be an object")
            continue
        main_release_id = album.get("main_release_id")
        if not isinstance(main_release_id, int) or main_release_id <= 0:
            failures.append(f"album {album.get('id')} has an invalid main_release_id")

    paths = artifact.get("paths", [])
    if not isinstance(paths, list):
        failures.append("paths must be an array")
        paths = []
    for path in paths:
        if not isinstance(path, dict):
            failures.append("path entry must be an object")
            continue
        for hop in path.get("hops", []):
            if not isinstance(hop, dict):
                failures.append(f"path {path.get('id')} hop must be an object")
                continue
            if hop.get("release_id") not in release_ids:
                failures.append(f"path {path.get('id')} references an unpublished release")
            if hop.get("artist_a_id") not in artist_ids or hop.get("artist_b_id") not in artist_ids:
                failures.append(f"path {path.get('id')} references an unpublished artist")

    failures.extend(f"artifact must not have a 'seed' key ({p})" for p in _seed_key_paths(artifact))
    failures.extend(_privacy_failures(artifact, name="artifact"))

    return failures
