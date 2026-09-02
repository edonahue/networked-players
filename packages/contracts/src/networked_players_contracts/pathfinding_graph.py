"""Canonical, dependency-free validation for the public pathfinding graph.

The pathfinding graph (`apps/web/public/data/pathfinding/graph.v3.json`,
`data/contracts/pathfinding-graph-v3.md`, ADR 0050/0051/0058/0068) is a
compact CSR adjacency scoped to a bounded 1-hop ego network around the
canonical catalog's primary artists -- not the full one-hop corpus (ADR
0050's measured scope decision). Every per-node/per-edge field is a PARALLEL
ARRAY aligned with the CSR arrays (`names[i]` describes `node_ids[i]`;
`edge_role_a[slot]`/`edge_role_b[slot]` describe the same directed slot as
`neighbors[slot]`/`evidence_release_ids[slot]`) -- measured during Slice F
to gzip roughly 15x smaller than an equivalent array-of-objects shape at
this graph's real size. It belongs to exactly one catalog generation, the
same rule every other catalog-derived artifact enforces.

v2 (ADR 0058) adds `album_virtual_nodes`: one synthetic node per catalog
album, connected to its real credited contributors, letting a
record-to-record search anchor on real album personnel instead of one
primary artist. v3 (ADR 0068) keeps that same shape and adds
`graph_policy_version`: the edges themselves are now performer-gated (a
`track_credit`/`release_credit` credit must pass `is_performer_role`;
`track_artist`/`release_artist` billing stays always-eligible), a policy
change with no shape change, so this field is what lets a validator or a
stale cached client tell a policy-only regeneration apart from an old
payload with the identical CSR shape. This module still accepts v1- and
v2-shaped payloads (`data/contracts/pathfinding-graph-v1.md`/`-v2.md`, kept
as historical record) for whatever legacy export might need re-validating.
`graph.v3.json` is now the only published pathfinding graph, registered as
`pathfinding_graph`: v2 stayed live and registered alongside it until every
real consumer had cut over, then was retired as an explicit, separate step
(ADR 0058's own real precedent for the v1 retirement). The validator itself
never narrowed -- only the published artifact set did.

Pure Python (no lxml/pyarrow/duckdb), safe for the Pi fleet and the web build
to independently verify an already-generated graph against the canonical
catalog it claims to belong to.
"""

from __future__ import annotations

import re
from typing import Any, TypeGuard

from .canonical import content_hash

PATHFINDING_GRAPH_SCHEMA_VERSIONS = frozenset({1, 2, 3})

# Dependency-free duplicate of graph-core's own
# `pathfinding_graph.ALBUM_ANCHOR_SENTINEL` -- this package stays
# dependency-free of graph-core, the same split every other contract/
# builder pair in this project already uses.
_ALBUM_ANCHOR_SENTINEL = "__np_album_anchor__"

_VERSION_PATTERN_BY_SCHEMA = {
    1: re.compile(r"^pathfinding-graph-v1-[0-9A-Za-z]+-[0-9a-f]{12}$"),
    2: re.compile(r"^pathfinding-graph-v2-[0-9A-Za-z]+-[0-9a-f]{12}$"),
    3: re.compile(r"^pathfinding-graph-v3-[0-9A-Za-z]+-[0-9a-f]{12}$"),
}

_BASE_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "catalog_version",
        "snapshot_date",
        "generated_at",
        "source",
        "license",
        "node_ids",
        "names",
        "offsets",
        "neighbors",
        "evidence_release_ids",
        "edge_role_a",
        "edge_role_b",
        "pathfinding_graph_version",
    }
)
_V2_ONLY_KEYS = frozenset({"album_virtual_nodes"})
# v3 (ADR 0068): keeps every v2 key (album_virtual_nodes included -- the CSR/
# parallel-array SHAPE is unchanged, only which edges exist changed) and adds
# `graph_policy_version`, recording which `graph.py.GRAPH_POLICY_VERSION`
# produced this graph's edges.
_V3_ONLY_KEYS = frozenset({"graph_policy_version"})
_ALBUM_VIRTUAL_NODE_KEYS = frozenset({"album_id", "virtual_artist_id", "main_release_id"})


def _is_int_not_bool(value: Any) -> TypeGuard[int]:
    """`bool` is a subtype of `int` in Python (`isinstance(True, int)` is
    `True`), so every integer-required field needs this, not a bare
    `isinstance(x, int)` -- otherwise a JSON `true`/`false` silently passes
    as a valid id/index/offset."""
    return isinstance(value, int) and not isinstance(value, bool)


def pathfinding_graph_version(payload: dict[str, Any], snapshot_date: str) -> str:
    """Recomputation mirror of the generation-time function in
    `networked_players_graph_core.pathfinding_graph` -- duplicated here
    deliberately (this package stays dependency-free of graph-core)."""
    identity: dict[str, Any] = {
        "node_ids": payload.get("node_ids"),
        "names": payload.get("names"),
        "offsets": payload.get("offsets"),
        "neighbors": payload.get("neighbors"),
        "evidence_release_ids": payload.get("evidence_release_ids"),
        "edge_role_a": payload.get("edge_role_a"),
        "edge_role_b": payload.get("edge_role_b"),
    }
    schema_version = payload.get("schema_version")
    if schema_version in (2, 3):
        identity["album_virtual_nodes"] = payload.get("album_virtual_nodes")
    if schema_version == 3:
        identity["graph_policy_version"] = payload.get("graph_policy_version")
    digest = content_hash(identity, length=12)
    return f"pathfinding-graph-v{schema_version}-{snapshot_date}-{digest}"


def pathfinding_graph_failures(graph: Any, catalog: Any) -> list[str]:
    """Every contract failure in a pathfinding graph, validated against the
    canonical catalog it claims to belong to and its own internal CSR
    invariants (offsets monotonic, neighbor indices in range, every parallel
    array the correct length). For a v2 or v3 graph, also validates
    `album_virtual_nodes` (negative ids disjoint from real ones, every
    album_id resolving to the canonical catalog, no duplicates, EVERY
    catalog album -- including one with zero in-scope credited
    contributors -- has its own entry, and each entry's main_release_id
    VALUE agrees with the catalog's own main_release_id for that album, not
    merely its type) and that the album-anchor sentinel role appears on a
    slot's virtual side and only there. The catalog-coverage and
    main_release_id-agreement checks are necessarily Python-only:
    `validatePathfindingGraph` (apps/web/src/game/pathfindingGraph.ts) never
    receives the catalog, so it can only ever prove internal
    self-consistency, not agreement with an external source of truth."""
    failures: list[str] = []
    if not isinstance(graph, dict):
        return ["pathfinding graph must be an object"]
    if not isinstance(catalog, dict):
        return ["catalog must be an object"]

    schema_version = graph.get("schema_version")
    if schema_version not in PATHFINDING_GRAPH_SCHEMA_VERSIONS:
        failures.append(
            f"schema_version must be one of {sorted(PATHFINDING_GRAPH_SCHEMA_VERSIONS)}"
        )

    expected_keys = _BASE_TOP_LEVEL_KEYS
    if schema_version in (2, 3):
        expected_keys = expected_keys | _V2_ONLY_KEYS
    if schema_version == 3:
        expected_keys = expected_keys | _V3_ONLY_KEYS
    if set(graph.keys()) != expected_keys:
        failures.append(f"graph has unexpected top-level keys: {sorted(graph.keys())}")

    for field_name in (
        "catalog_version",
        "snapshot_date",
        "generated_at",
        "source",
        "license",
        "pathfinding_graph_version",
    ):
        # String-typed, not just truthy: a truthy non-string (e.g.
        # generated_at: 1) used to pass this check even though
        # validatePathfindingGraph's matching check requires a real string --
        # letting a malformed artifact clear `validate-public-artifacts` (the
        # committed-artifact CI gate) while still failing at runtime in the
        # browser. These fields are excluded from the content hash, so
        # nothing else in this function would have caught it.
        value = graph.get(field_name)
        if not isinstance(value, str) or not value:
            failures.append(f"{field_name} is required and must be a non-empty string")

    catalog_version = catalog.get("catalog_version")
    if graph.get("catalog_version") != catalog_version:
        failures.append(
            f"graph catalog_version {graph.get('catalog_version')!r} does not match the "
            f"canonical catalog's catalog_version {catalog_version!r}"
        )

    node_ids = graph.get("node_ids")
    names = graph.get("names")
    offsets = graph.get("offsets")
    neighbors = graph.get("neighbors")
    evidence_release_ids = graph.get("evidence_release_ids")
    edge_role_a = graph.get("edge_role_a")
    edge_role_b = graph.get("edge_role_b")

    if not isinstance(node_ids, list) or not node_ids:
        failures.append("node_ids must be a non-empty array")
        node_ids = []
    elif not all(_is_int_not_bool(n) for n in node_ids):
        # sorted()/set() below would raise on a mixed-type or unhashable
        # element (e.g. a str alongside an int, or a nested list) -- fail
        # closed instead of letting a malformed-but-JSON-shaped payload
        # crash the validator.
        failures.append("node_ids must contain only integers")
        node_ids = []
    else:
        if node_ids != sorted(node_ids):
            failures.append("node_ids must be sorted")
        if len(set(node_ids)) != len(node_ids):
            failures.append("node_ids must not contain duplicates")

    if (
        not isinstance(names, list)
        or len(names) != len(node_ids)
        or not all(isinstance(n, str) for n in names)
    ):
        failures.append("names must be an array of strings the same length as node_ids")

    if not isinstance(offsets, list) or len(offsets) != len(node_ids) + 1:
        failures.append("offsets must be an array of length len(node_ids) + 1")
        offsets = []
    elif not all(_is_int_not_bool(x) for x in offsets):
        # sorted()/range() below would raise on a float or bool element.
        failures.append("offsets must contain only integers")
        offsets = []
    elif offsets != sorted(offsets) or offsets[0] != 0:
        failures.append("offsets must be non-decreasing and start at 0")

    if not isinstance(neighbors, list) or not all(_is_int_not_bool(n) for n in neighbors):
        failures.append("neighbors must be an array of integers")
        neighbors = []
    if not isinstance(evidence_release_ids, list) or not all(
        _is_int_not_bool(x) for x in evidence_release_ids
    ):
        failures.append("evidence_release_ids must be an array of integers")
        evidence_release_ids = []
    if not isinstance(edge_role_a, list) or not all(isinstance(x, str) for x in edge_role_a):
        failures.append("edge_role_a must be an array of strings")
        edge_role_a = []
    if not isinstance(edge_role_b, list) or not all(isinstance(x, str) for x in edge_role_b):
        failures.append("edge_role_b must be an array of strings")
        edge_role_b = []

    slot_count = len(neighbors)
    for name, array in (
        ("evidence_release_ids", evidence_release_ids),
        ("edge_role_a", edge_role_a),
        ("edge_role_b", edge_role_b),
    ):
        if len(array) != slot_count:
            failures.append(f"{name} must be the same length as neighbors ({slot_count})")

    if offsets and neighbors and offsets[-1] != len(neighbors):
        failures.append("offsets[-1] must equal len(neighbors)")

    node_count = len(node_ids)
    for index, neighbor_index in enumerate(neighbors):
        if not (0 <= neighbor_index < node_count):
            failures.append(f"neighbors[{index}] {neighbor_index!r} is not a valid node index")
            break  # one report is enough; a systemic index error would spam this otherwise

    version = graph.get("pathfinding_graph_version")
    snapshot_date = graph.get("snapshot_date")
    if isinstance(version, str) and isinstance(schema_version, int):
        pattern = _VERSION_PATTERN_BY_SCHEMA.get(schema_version)
        if pattern is not None and not pattern.match(version):
            failures.append(f"pathfinding_graph_version {version!r} is not well-formed")
    if isinstance(version, str) and isinstance(snapshot_date, str):
        expected = pathfinding_graph_version(graph, snapshot_date)
        if version != expected:
            failures.append(
                f"pathfinding_graph_version {version!r} does not match recomputed content "
                f"(expected {expected!r})"
            )

    if schema_version == 3:
        graph_policy_version = graph.get("graph_policy_version")
        if not _is_int_not_bool(graph_policy_version) or graph_policy_version < 1:
            failures.append("graph_policy_version must be a positive integer")

    if schema_version not in (2, 3):
        return failures

    # --- v2+: album_virtual_nodes and sentinel-role placement ---------------
    album_virtual_nodes = graph.get("album_virtual_nodes")
    if not isinstance(album_virtual_nodes, list):
        failures.append("album_virtual_nodes must be an array")
        album_virtual_nodes = []

    # Validated before iterating, not assumed: this validator takes an
    # arbitrary JSON-compatible catalog and must stay total. `albums: null`
    # and `albums: 5` both raised TypeError from the comprehensions below
    # before this check -- and a raise is strictly worse than a failure
    # string here, since every caller (validate-public-artifacts, the CLI,
    # the Pi-fleet artifact.validate workload) reports failures but crashes
    # on an exception. Reset to [] on a structural failure, the same
    # convention the graph-side arrays above already use.
    catalog_albums = catalog.get("albums")
    if not isinstance(catalog_albums, list):
        failures.append("catalog albums must be an array")
        catalog_albums = []

    catalog_album_ids = {a.get("id") for a in catalog_albums if isinstance(a, dict)}
    catalog_main_release_id_by_album = {
        a.get("id"): a.get("main_release_id") for a in catalog_albums if isinstance(a, dict)
    }
    real_node_ids = {n for n in node_ids if isinstance(n, int) and n > 0}
    node_id_set = set(node_ids)

    seen_album_ids: set[Any] = set()
    seen_virtual_ids: set[Any] = set()
    for i, vn in enumerate(album_virtual_nodes):
        if not isinstance(vn, dict) or set(vn.keys()) != _ALBUM_VIRTUAL_NODE_KEYS:
            failures.append(
                f"album_virtual_nodes[{i}] must have keys {sorted(_ALBUM_VIRTUAL_NODE_KEYS)}"
            )
            continue

        album_id = vn.get("album_id")
        if album_id not in catalog_album_ids:
            failures.append(
                f"album_virtual_nodes[{i}] album_id {album_id!r} is not in the canonical catalog"
            )
        elif album_id in seen_album_ids:
            failures.append(f"album_virtual_nodes[{i}] duplicate album_id {album_id!r}")
        else:
            seen_album_ids.add(album_id)

        virtual_id = vn.get("virtual_artist_id")
        if not _is_int_not_bool(virtual_id) or virtual_id >= 0:
            failures.append(
                f"album_virtual_nodes[{i}] virtual_artist_id {virtual_id!r} must be a "
                "negative integer, disjoint from every real (positive) node id"
            )
        else:
            if virtual_id in real_node_ids:
                failures.append(
                    f"album_virtual_nodes[{i}] virtual_artist_id {virtual_id!r} collides with "
                    "a real node id"
                )
            if virtual_id in seen_virtual_ids:
                failures.append(
                    f"album_virtual_nodes[{i}] duplicate virtual_artist_id {virtual_id!r}"
                )
            seen_virtual_ids.add(virtual_id)
            if virtual_id not in node_id_set:
                failures.append(
                    f"album_virtual_nodes[{i}] virtual_artist_id {virtual_id!r} is not present "
                    "in node_ids"
                )

        main_release_id = vn.get("main_release_id")
        if not _is_int_not_bool(main_release_id):
            failures.append(f"album_virtual_nodes[{i}] main_release_id must be an integer")
        elif (
            album_id in catalog_main_release_id_by_album
            and main_release_id != catalog_main_release_id_by_album[album_id]
        ):
            failures.append(
                f"album_virtual_nodes[{i}] main_release_id {main_release_id!r} does not match "
                f"the canonical catalog's main_release_id "
                f"{catalog_main_release_id_by_album[album_id]!r} for album_id {album_id!r}"
            )

    # Every catalog album -- including one with zero in-scope credited
    # contributors -- must still get its own virtual node (contract: "never
    # silently dropped"). seen_album_ids only ever gains an id once its
    # entry has passed the per-entry checks above, so this also catches an
    # album whose only entry was malformed (missing/duplicate/wrong keys)
    # just as validly as one with no entry at all.
    for missing_album_id in sorted(catalog_album_ids - seen_album_ids, key=str):
        failures.append(
            f"album_virtual_nodes is missing a virtual node for catalog album {missing_album_id!r}"
        )

    if offsets and neighbors and edge_role_a and edge_role_b:
        for node_index in range(min(node_count, len(offsets) - 1)):
            artist_a_id = node_ids[node_index]
            start, end = offsets[node_index], offsets[node_index + 1]
            for slot in range(start, min(end, len(neighbors))):
                neighbor_index = neighbors[slot]
                if not (0 <= neighbor_index < node_count) or slot >= len(edge_role_a):
                    continue  # already reported above
                artist_b_id = node_ids[neighbor_index]
                role_a, role_b = edge_role_a[slot], edge_role_b[slot]
                if (role_a == _ALBUM_ANCHOR_SENTINEL) != (artist_a_id < 0):
                    failures.append(
                        f"edge_role_a[{slot}] sentinel placement disagrees with whether node "
                        f"{artist_a_id} is virtual"
                    )
                    break
                if (role_b == _ALBUM_ANCHOR_SENTINEL) != (artist_b_id < 0):
                    failures.append(
                        f"edge_role_b[{slot}] sentinel placement disagrees with whether node "
                        f"{artist_b_id} is virtual"
                    )
                    break
            else:
                continue
            break  # one report is enough; a systemic sentinel error would spam this otherwise

    return failures
