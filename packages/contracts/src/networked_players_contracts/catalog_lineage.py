"""Cross-artifact checks that tie derived public artifacts back to the catalog.

Before this module, `validate-public-artifacts` validated the Connection
Guesser and Record Routes pools without the catalog, compared the challenge's
`catalog_version` only when it was not `None`, and never checked the evidence
release registry against the releases the product actually cites. Regenerating
the catalog and forgetting to rebuild a pool therefore stayed green (ADR 0072
section 1; the trap is recorded in `docs/EXPANSION_PIPELINE.md`).

Each invariant below was chosen by measuring the real committed artifacts and
reading the builders that produce them, not assumed:

- **`catalog_version` equality** (Connection Guesser, Record Routes,
  challenge): every builder stamps the catalog version it consumed into
  `provenance.catalog_version`, and a catalog rebuild changes it. Equality is
  therefore the staleness detector. The builders accept `catalog_version=None`
  for hand-written album lists, but the live, catalog-derived artifacts never
  legitimately lack it, so a missing version is a failure here.
- **Album set is a SUBSET of the catalog, never "equal"** (all three):
  `build-connection-rounds` and `build-record-routes` apply their own
  eligibility (an album needs enough credited contributors / a documented
  path), and `build_challenge_v2_from_matched` only emits albums the graph
  matched (the rest go to the build report's `missed`). ADR 0067 likewise says
  the album shelf shows the whole catalog, not just challenge-connected
  albums. Subset still catches an album that was removed from the catalog.
- **Title and artist agreement** for every album present in both: a retitle
  deliberately does not change `catalog_version`, so version equality alone
  cannot see it. Compared exactly; the builders copy these strings from the
  catalog verbatim.
- **Registry coverage**: `build_evidence_release_registry` is the union of
  `challenge.v3.json`'s releases, `routes/rounds.v1.json`'s releases and every
  `evidence_release_id` in `pathfinding/graph.v4.json`. The registry must
  contain every one of those ids (superset, so extra entries are tolerated).

The frozen daily generations and the daily manifest are bound to older catalog
versions by design (ADR 0041, ADR 0066) and are not touched here.

Pure Python and dependency-free (runs on 1 GB Raspberry Pi workers). Nothing
builds a structure larger than one set of ids per artifact.
"""

from __future__ import annotations

from typing import Any


def _catalog_albums_by_id(catalog: Any) -> dict[Any, dict[str, Any]]:
    if not isinstance(catalog, dict):
        return {}
    albums = catalog.get("albums")
    if not isinstance(albums, list):
        return {}
    return {a.get("id"): a for a in albums if isinstance(a, dict)}


def _version_failures(label: str, provenance: Any, catalog: dict[str, Any]) -> list[str]:
    version = provenance.get("catalog_version") if isinstance(provenance, dict) else None
    expected = catalog.get("catalog_version")
    if not isinstance(version, str) or not version:
        return [
            f"{label} provenance.catalog_version is missing; the live artifact must record "
            f"the catalog it was built from (catalog is {expected!r})"
        ]
    if version != expected:
        return [
            f"{label} provenance.catalog_version {version!r} does not match the catalog's "
            f"{expected!r} -- the catalog was regenerated after this artifact was built; "
            "rebuild it"
        ]
    return []


def _album_failures(
    label: str,
    albums: Any,
    catalog_by_id: dict[Any, dict[str, Any]],
    *,
    artist_key: str,
) -> list[str]:
    """Every album must exist in the catalog (subset), and its title and artist
    name must equal the catalog's."""
    if not isinstance(albums, list):
        return []
    failures: list[str] = []
    for album in albums:
        if not isinstance(album, dict):
            continue
        album_id = album.get("id")
        catalog_album = catalog_by_id.get(album_id)
        if catalog_album is None:
            failures.append(f"{label} album {album_id!r} is not in the canonical catalog")
            continue
        if album.get("title") != catalog_album.get("title"):
            failures.append(
                f"{label} album {album_id!r} title {album.get('title')!r} does not match the "
                f"catalog's {catalog_album.get('title')!r}"
            )
        if album.get(artist_key) != catalog_album.get("artist"):
            failures.append(
                f"{label} album {album_id!r} artist {album.get(artist_key)!r} does not match "
                f"the catalog's {catalog_album.get('artist')!r}"
            )
    return failures


def connection_catalog_failures(universe: Any, catalog: Any) -> list[str]:
    """Connection Guesser universe vs the catalog (the rounds artifact's
    provenance must equal the universe's, which `connection_rounds_failures`
    already enforces)."""
    if not isinstance(universe, dict) or not isinstance(catalog, dict):
        return []
    return _version_failures(
        "connection universe", universe.get("provenance"), catalog
    ) + _album_failures(
        "connection universe",
        universe.get("albums"),
        _catalog_albums_by_id(catalog),
        artist_key="act",
    )


def routes_catalog_failures(universe: Any, catalog: Any) -> list[str]:
    """Record Routes universe vs the catalog."""
    if not isinstance(universe, dict) or not isinstance(catalog, dict):
        return []
    return _version_failures(
        "routes universe", universe.get("provenance"), catalog
    ) + _album_failures(
        "routes universe",
        universe.get("albums"),
        _catalog_albums_by_id(catalog),
        artist_key="artist",
    )


def challenge_catalog_failures(challenge: Any, catalog: Any) -> list[str]:
    """Challenge vs the catalog. `challenge_failures` itself still tolerates a
    `None` catalog_version (hand-written query lists); the live challenge.v3
    does not."""
    if not isinstance(challenge, dict) or not isinstance(catalog, dict):
        return []
    return _version_failures("challenge", challenge.get("provenance"), catalog) + _album_failures(
        "challenge",
        challenge.get("albums"),
        _catalog_albums_by_id(catalog),
        artist_key="artist",
    )


def search_index_text_failures(search_index: Any, catalog: Any) -> list[str]:
    """Album entries' label/sublabel must equal the catalog's title/artist."""
    if not isinstance(search_index, dict):
        return []
    catalog_by_id = _catalog_albums_by_id(catalog)
    entries = search_index.get("entries")
    if not isinstance(entries, list):
        return []
    failures: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("kind") != "album":
            continue
        catalog_album = catalog_by_id.get(entry.get("id"))
        if catalog_album is None:
            continue  # reported by search_index_failures itself
        if entry.get("label") != catalog_album.get("title"):
            failures.append(
                f"album {entry.get('id')!r} label {entry.get('label')!r} does not match the "
                f"catalog's title {catalog_album.get('title')!r}"
            )
        if entry.get("sublabel") != catalog_album.get("artist"):
            failures.append(
                f"album {entry.get('id')!r} sublabel {entry.get('sublabel')!r} does not match "
                f"the catalog's artist {catalog_album.get('artist')!r}"
            )
    return failures


def _hop_and_release_ids(artifact: Any, hop_containers_key: str) -> set[Any]:
    """Every release id an artifact cites: its `releases[]` entries plus each
    hop's `release_id` (hops live under `paths[]` or `rounds[]`)."""
    ids: set[Any] = set()
    if not isinstance(artifact, dict):
        return ids
    for release in artifact.get("releases", []) or []:
        if isinstance(release, dict):
            ids.add(release.get("release_id"))
    for container in artifact.get(hop_containers_key, []) or []:
        if not isinstance(container, dict):
            continue
        for hop in container.get("hops", []) or []:
            if isinstance(hop, dict):
                ids.add(hop.get("release_id"))
    return ids


def registry_citation_failures(
    registry: Any, *, challenge: Any, routes_rounds: Any, pathfinding_graph: Any
) -> list[str]:
    """The evidence release registry must contain every release id cited by
    the challenge, the routes rounds and the pathfinding graph."""
    if not isinstance(registry, dict):
        return []
    registered = {r for r in registry.get("release_ids", []) or []}
    graph_ids: set[Any] = (
        set(pathfinding_graph.get("evidence_release_ids", []) or [])
        if isinstance(pathfinding_graph, dict)
        else set()
    )
    cited = (
        ("challenge.v3.json", _hop_and_release_ids(challenge, "paths")),
        ("routes/rounds.v1.json", _hop_and_release_ids(routes_rounds, "rounds")),
        ("pathfinding graph", graph_ids),
    )
    failures: list[str] = []
    for label, ids in cited:
        missing = sorted((i for i in ids - registered if i is not None), key=repr)
        if missing:
            shown = missing[:10]
            suffix = f" (and {len(missing) - len(shown)} more)" if len(missing) > len(shown) else ""
            failures.append(
                f"registry is missing {len(missing)} release id(s) cited by {label}: "
                f"{shown}{suffix} -- rebuild the evidence release registry"
            )
    return failures
