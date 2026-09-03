"""Build the pathfinding graph's prominence sidecar (graph-expansion Phase 1,
plan section 8): precomputed, explainable, node-aligned signals for ranking
Explore's neighbor ordering and label visibility. Replaces the contributor
index's `connection_count` ranking (which only covers indexed contributors --
~445 of them, real-corpus measured -- and most graph neighbors tie at 0
there, since most performers never appear in a challenge/routes path at all).

Never a fresh full-corpus query: built entirely from two already-published
artifacts, the pathfinding graph (`pathfinding/graph.v4.json`, any
schema_version >= 2 since `album_virtual_nodes` exists from v2 on -- this
module works from the in-memory payload, not a specific file, so it is
itself schema-version-agnostic) and `evidence/release-registry.v1.json`
(for each node's own evidence releases' real years). A separate file, not a
field on the pathfinding graph itself, pinned to that graph's own
`pathfinding_graph_version` -- so a ranking-formula tweak alone never forces
a graph rebuild, and a stale sidecar against a regenerated graph is a
detectable mismatch, not a silent drift.

Fields (plan section 8's table), one entry per pathfinding-graph node,
aligned index-for-index with that graph's own `node_ids` (same length, same
order, including virtual album-anchor nodes -- an anchor is never itself
RANKED as a neighbor, but its own `degree` is still a real, meaningful CSR
fact, "this album has N real credited contributors", computed for every
node regardless of kind; every OTHER field below is a zero/null placeholder
on an anchor's own row, since none of them were ever computed for one):

- `degree`: the node's own CSR row length (real neighbor count, anchor
  edges included) -- "connected to N performers".
- `albums_1hop`: count of directly-connected virtual album-anchor
  neighbors -- "plays on N catalog albums".
- `albums_2hop`: count of DISTINCT album anchors reachable via exactly one
  real intermediate neighbor, EXCLUDING anchors already counted at 1 hop --
  "one step from N albums" (plan's own UI phrasing): who this performer's
  collaborators reach that this performer does not reach directly. Computed
  cheaply as the union of each real neighbor's own (small) `albums_1hop`
  set, never a brute-force degree^2 two-hop walk -- this graph is
  heavy-tailed enough (a handful of 500+-degree hub nodes, real-corpus
  measured) that a naive walk would be genuinely expensive for those nodes;
  a real person's own direct album count is small and bounded regardless of
  their degree, so summing small sets across up to `degree` neighbors stays
  cheap even for a hub.
- `evidence_releases`: count of distinct `evidence_release_ids` across the
  node's own row -- "documented on N releases".
- `role_diversity`: count of distinct `RoleCategory` classifications across
  the node's own row's role text (its OWN role on each edge, i.e.
  `edge_role_a` for that row -- see `pathfinding_graph.py`'s own comment on
  why `edge_role_a[slot]` is always the row-owning node's role, never the
  neighbor's), excluding the album-anchor sentinel (a structural marker,
  never a real role) -- "sings and plays". Shown, never weighted into
  `rank` (plan section 8: rank rewards STRUCTURAL reach, not versatility).
- `first_year`/`last_year`: min/max real release year across the node's own
  evidence releases (via the registry), `null` when no evidence release has
  a known year -- "active 1968-2004".
- `rank`: a documented, monotone weighted combination -- `albums_2hop` and
  `decade_span` (`last_year - first_year`, 0 when years are unknown)
  weighted highest (the plan's own discovery-goal decision: "bridges
  between scenes/eras" and "band lineups and their orbits" -- a performer
  reaching many anchors across decades is a bridge), then `albums_1hop`,
  then `degree` (a within-neighborhood signal, deliberately NOT the
  dominant term -- a raw-degree-led ranking is exactly the hub trap the
  plan's own §2 finding warns against), then `evidence_releases`. This is
  an honestly-labeled APPROXIMATION via weighted sum, not a strict
  lexicographic guarantee against every possible extreme combination of
  inputs -- the plan itself frames `rank` as "tuned to the owner's stated
  discovery goals", implying iteration against real Explore usage is
  expected, not a single perfect formula on the first attempt.
"""

from __future__ import annotations

from typing import Any

from networked_players_contracts.canonical import content_hash

from .role_taxonomy import classify_role

# Dependency-free duplicate of `pathfinding_graph.ALBUM_ANCHOR_SENTINEL` --
# this module stays dependency-free of that one (mirrors the same split
# `contracts/pathfinding_graph.py` already uses for its own copy).
_ALBUM_ANCHOR_SENTINEL = "__np_album_anchor__"

# See the module docstring's `rank` section for the reasoning behind this
# relative ordering; the exact magnitudes are a starting point, not a tuned
# constant -- revisit against real Explore usage, not by inspection alone.
_WEIGHT_ALBUMS_2HOP = 50
_WEIGHT_DECADE_SPAN = 50
_WEIGHT_ALBUMS_1HOP = 10
_WEIGHT_DEGREE = 1
_WEIGHT_EVIDENCE_RELEASES = 1


def prominence_version(payload: dict[str, Any], snapshot_date: str) -> str:
    """Content hash over every field a client actually reads -- `source`/
    `license`/`generated_at` excluded, the same "provenance text is not
    content" discipline `pathfinding_graph_version` and every other
    artifact version here already applies."""
    identity = {
        "pathfinding_graph_version": payload["pathfinding_graph_version"],
        "node_ids": payload["node_ids"],
        "degree": payload["degree"],
        "albums_1hop": payload["albums_1hop"],
        "albums_2hop": payload["albums_2hop"],
        "evidence_releases": payload["evidence_releases"],
        "role_diversity": payload["role_diversity"],
        "first_year": payload["first_year"],
        "last_year": payload["last_year"],
        "rank": payload["rank"],
    }
    digest = content_hash(identity, length=12)
    return f"prominence-v1-{snapshot_date}-{digest}"


def build_prominence(
    *,
    pathfinding_graph: dict[str, Any],
    evidence_release_registry: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    """Deterministic given the same two already-published artifacts. Raises
    `ValueError` on a `catalog_version` mismatch between them -- a
    prominence sidecar belongs to exactly one catalog generation, the same
    rule every other catalog-derived artifact enforces."""
    catalog_version = pathfinding_graph["catalog_version"]
    registry_catalog_version = evidence_release_registry.get("catalog_version")
    if registry_catalog_version != catalog_version:
        raise ValueError(
            f"evidence_release_registry's catalog_version {registry_catalog_version!r} "
            f"does not match the pathfinding graph's catalog_version {catalog_version!r}"
        )

    node_ids: list[int] = pathfinding_graph["node_ids"]
    offsets: list[int] = pathfinding_graph["offsets"]
    neighbors: list[int] = pathfinding_graph["neighbors"]
    evidence_release_ids: list[int] = pathfinding_graph["evidence_release_ids"]
    schema_version = int(pathfinding_graph["schema_version"])

    # v4 dictionary-encodes role text as indices into `roles` -- decode once
    # here so the rest of this function never special-cases schema_version
    # beyond this one spot (the same decode-once precedent
    # `pathfindingGraph.ts`'s validator and `route_quality.load_published_graph`
    # both already apply).
    if schema_version >= 4:
        roles: list[str] = pathfinding_graph["roles"]
        edge_role_a: list[str] = [roles[i] for i in pathfinding_graph["edge_role_a"]]
    else:
        edge_role_a = pathfinding_graph["edge_role_a"]

    node_count = len(node_ids)
    release_years: dict[int, int | None] = dict(
        zip(
            evidence_release_registry.get("release_ids", []),
            evidence_release_registry.get("years", []),
            strict=True,
        )
    )

    degree = [offsets[i + 1] - offsets[i] for i in range(node_count)]

    # Pass 1: each node's own direct (1-hop) signals -- one linear scan over
    # every CSR slot, each node's own small per-row sets.
    albums_1hop_sets: list[set[int]] = [set() for _ in range(node_count)]
    evidence_release_sets: list[set[int]] = [set() for _ in range(node_count)]
    role_category_sets: list[set[str]] = [set() for _ in range(node_count)]
    for i in range(node_count):
        start, end = offsets[i], offsets[i + 1]
        for slot in range(start, end):
            neighbor_index = neighbors[slot]
            if node_ids[neighbor_index] < 0:
                albums_1hop_sets[i].add(neighbor_index)
            evidence_release_sets[i].add(evidence_release_ids[slot])
            role_text = edge_role_a[slot]
            if role_text != _ALBUM_ANCHOR_SENTINEL:
                for category in classify_role(role_text):
                    role_category_sets[i].add(category.value)

    # Pass 2: albums_2hop -- see the module docstring for why this is a
    # union of small per-neighbor sets, never a brute-force two-hop walk.
    albums_2hop = [0] * node_count
    for i in range(node_count):
        if node_ids[i] < 0:
            continue  # a virtual album anchor is never itself ranked
        start, end = offsets[i], offsets[i + 1]
        reached: set[int] = set()
        for slot in range(start, end):
            neighbor_index = neighbors[slot]
            if node_ids[neighbor_index] < 0:
                continue  # a direct anchor edge, not a real intermediate hop
            reached |= albums_1hop_sets[neighbor_index]
        albums_2hop[i] = len(reached - albums_1hop_sets[i])

    albums_1hop = [0] * node_count
    evidence_releases = [0] * node_count
    role_diversity = [0] * node_count
    first_year: list[int | None] = [None] * node_count
    last_year: list[int | None] = [None] * node_count
    rank = [0] * node_count

    for i in range(node_count):
        if node_ids[i] < 0:
            continue  # virtual anchors keep every field at its zero/null default
        albums_1hop[i] = len(albums_1hop_sets[i])
        evidence_releases[i] = len(evidence_release_sets[i])
        role_diversity[i] = len(role_category_sets[i])
        years: list[int] = [
            year for rid in evidence_release_sets[i] if (year := release_years.get(rid)) is not None
        ]
        decade_span = 0
        if years:
            node_first_year = min(years)
            node_last_year = max(years)
            first_year[i] = node_first_year
            last_year[i] = node_last_year
            decade_span = node_last_year - node_first_year
        rank[i] = (
            _WEIGHT_ALBUMS_2HOP * albums_2hop[i]
            + _WEIGHT_DECADE_SPAN * decade_span
            + _WEIGHT_ALBUMS_1HOP * albums_1hop[i]
            + _WEIGHT_DEGREE * degree[i]
            + _WEIGHT_EVIDENCE_RELEASES * evidence_releases[i]
        )

    payload: dict[str, Any] = {
        "schema_version": 1,
        "catalog_version": catalog_version,
        "pathfinding_graph_version": pathfinding_graph["pathfinding_graph_version"],
        "generated_at": generated_at,
        "source": (
            "Derived from apps/web/public/data/pathfinding/graph.v4.json and "
            "apps/web/public/data/evidence/release-registry.v1.json (years only) -- "
            "no fresh full-corpus query. See docs/DATA_AND_RIGHTS.md."
        ),
        "license": (
            "Derived from the Discogs monthly CC0 data dumps via the two published "
            "artifacts above. See docs/DATA_AND_RIGHTS.md."
        ),
        "node_ids": node_ids,
        "degree": degree,
        "albums_1hop": albums_1hop,
        "albums_2hop": albums_2hop,
        "evidence_releases": evidence_releases,
        "role_diversity": role_diversity,
        "first_year": first_year,
        "last_year": last_year,
        "rank": rank,
    }
    payload["prominence_version"] = prominence_version(payload, pathfinding_graph["snapshot_date"])
    return payload
