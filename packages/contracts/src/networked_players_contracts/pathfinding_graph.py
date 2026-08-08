"""Canonical, dependency-free validation for the public pathfinding graph.

The pathfinding graph (`apps/web/public/data/pathfinding/graph.v1.json` /
`graph.v2.json`, `data/contracts/pathfinding-graph-v1.md` /
`pathfinding-graph-v2.md`, ADR 0050/0051/0058) is a compact CSR adjacency
scoped to a bounded 1-hop ego network around the canonical catalog's
primary artists -- not the full one-hop corpus (ADR 0050's measured scope
decision). Every per-node/per-edge field is a PARALLEL ARRAY aligned with
the CSR arrays (`names[i]` describes `node_ids[i]`; `edge_role_a[slot]`/
`edge_role_b[slot]` describe the same directed slot as
`neighbors[slot]`/`evidence_release_ids[slot]`) -- measured during Slice F
to gzip roughly 15x smaller than an equivalent array-of-objects shape at
this graph's real size. It belongs to exactly one catalog generation, the
same rule every other catalog-derived artifact enforces.

v2 (ADR 0058) adds `album_virtual_nodes`: one synthetic node per catalog
album, connected to its real credited contributors, letting a
record-to-record search anchor on real album personnel instead of one
primary artist. This module accepts both schema versions -- v1 stays live
(unedited) until Connect Two Records cuts over to v2; only the builder
(`networked_players_graph_core.pathfinding_graph`) has moved to
v2-only output.

Pure Python (no lxml/pyarrow/duckdb), safe for the Pi fleet and the web build
to independently verify an already-generated graph against the canonical
catalog it claims to belong to.
"""

from __future__ import annotations

import re
from typing import Any

from .canonical import content_hash

PATHFINDING_GRAPH_SCHEMA_VERSIONS = frozenset({1, 2})

# Dependency-free duplicate of graph-core's own
# `pathfinding_graph.ALBUM_ANCHOR_SENTINEL` -- this package stays
# dependency-free of graph-core, the same split every other contract/
# builder pair in this project already uses.
_ALBUM_ANCHOR_SENTINEL = "__np_album_anchor__"

_VERSION_PATTERN_BY_SCHEMA = {
    1: re.compile(r"^pathfinding-graph-v1-[0-9A-Za-z]+-[0-9a-f]{12}$"),
    2: re.compile(r"^pathfinding-graph-v2-[0-9A-Za-z]+-[0-9a-f]{12}$"),
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
_ALBUM_VIRTUAL_NODE_KEYS = frozenset({"album_id", "virtual_artist_id", "main_release_id"})


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
    if schema_version == 2:
        identity["album_virtual_nodes"] = payload.get("album_virtual_nodes")
    digest = content_hash(identity, length=12)
    return f"pathfinding-graph-v{schema_version}-{snapshot_date}-{digest}"


def pathfinding_graph_failures(graph: Any, catalog: Any) -> list[str]:
    """Every contract failure in a pathfinding graph, validated against the
    canonical catalog it claims to belong to and its own internal CSR
    invariants (offsets monotonic, neighbor indices in range, every parallel
    array the correct length). For a v2 graph, also validates
    `album_virtual_nodes` (negative ids disjoint from real ones, every
    album_id resolving to the canonical catalog, no duplicates) and that
    the album-anchor sentinel role appears on a slot's virtual side and
    only there."""
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

    expected_keys = _BASE_TOP_LEVEL_KEYS | (_V2_ONLY_KEYS if schema_version == 2 else frozenset())
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
        if not graph.get(field_name):
            failures.append(f"{field_name} is required and must be non-empty")

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
    if node_ids != sorted(node_ids):
        failures.append("node_ids must be sorted")
    if len(set(node_ids)) != len(node_ids):
        failures.append("node_ids must not contain duplicates")

    if not isinstance(names, list) or len(names) != len(node_ids):
        failures.append("names must be an array the same length as node_ids")

    if not isinstance(offsets, list) or len(offsets) != len(node_ids) + 1:
        failures.append("offsets must be an array of length len(node_ids) + 1")
        offsets = []
    elif offsets != sorted(offsets) or offsets[0] != 0:
        failures.append("offsets must be non-decreasing and start at 0")

    if not isinstance(neighbors, list):
        failures.append("neighbors must be an array")
        neighbors = []
    if not isinstance(evidence_release_ids, list):
        failures.append("evidence_release_ids must be an array")
        evidence_release_ids = []
    if not isinstance(edge_role_a, list):
        failures.append("edge_role_a must be an array")
        edge_role_a = []
    if not isinstance(edge_role_b, list):
        failures.append("edge_role_b must be an array")
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
        if not isinstance(neighbor_index, int) or not (0 <= neighbor_index < node_count):
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

    if schema_version != 2:
        return failures

    # --- v2-only: album_virtual_nodes and sentinel-role placement ----------
    album_virtual_nodes = graph.get("album_virtual_nodes")
    if not isinstance(album_virtual_nodes, list):
        failures.append("album_virtual_nodes must be an array")
        album_virtual_nodes = []

    catalog_album_ids = {a.get("id") for a in catalog.get("albums", []) if isinstance(a, dict)}
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
        if not isinstance(virtual_id, int) or isinstance(virtual_id, bool) or virtual_id >= 0:
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
        if not isinstance(main_release_id, int) or isinstance(main_release_id, bool):
            failures.append(f"album_virtual_nodes[{i}] main_release_id must be an integer")

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
