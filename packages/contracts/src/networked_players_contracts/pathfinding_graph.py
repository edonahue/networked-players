"""Canonical, dependency-free validation for the public pathfinding graph.

The pathfinding graph (`apps/web/public/data/pathfinding/graph.v1.json`,
`data/contracts/pathfinding-graph-v1.md`, ADR 0050/0051) is a compact CSR
adjacency scoped to a bounded 1-hop ego network around the canonical
catalog's primary artists -- not the full one-hop corpus (ADR 0050's
measured scope decision). Every per-node/per-edge field is a PARALLEL ARRAY
aligned with the CSR arrays (`names[i]` describes `node_ids[i]`;
`edge_role_a[slot]`/`edge_role_b[slot]` describe the same directed slot as
`neighbors[slot]`/`evidence_release_ids[slot]`) -- measured during Slice F to
gzip roughly 15x smaller than an equivalent array-of-objects shape at this
graph's real size. It belongs to exactly one catalog generation, the same
rule every other catalog-derived artifact enforces.

Pure Python (no lxml/pyarrow/duckdb), safe for the Pi fleet and the web build
to independently verify an already-generated graph against the canonical
catalog it claims to belong to.
"""

from __future__ import annotations

import re
from typing import Any

from .canonical import content_hash

PATHFINDING_GRAPH_SCHEMA_VERSION = 1

_VERSION_PATTERN = re.compile(r"^pathfinding-graph-v1-[0-9A-Za-z]+-[0-9a-f]{12}$")

_TOP_LEVEL_KEYS = frozenset(
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


def pathfinding_graph_version(payload: dict[str, Any], snapshot_date: str) -> str:
    """Recomputation mirror of the generation-time function in
    `networked_players_graph_core.pathfinding_graph` -- duplicated here
    deliberately (this package stays dependency-free of graph-core)."""
    identity = {
        "node_ids": payload.get("node_ids"),
        "names": payload.get("names"),
        "offsets": payload.get("offsets"),
        "neighbors": payload.get("neighbors"),
        "evidence_release_ids": payload.get("evidence_release_ids"),
        "edge_role_a": payload.get("edge_role_a"),
        "edge_role_b": payload.get("edge_role_b"),
    }
    return f"pathfinding-graph-v1-{snapshot_date}-{content_hash(identity, length=12)}"


def pathfinding_graph_failures(graph: Any, catalog: Any) -> list[str]:
    """Every contract failure in a pathfinding graph, validated against the
    canonical catalog it claims to belong to and its own internal CSR
    invariants (offsets monotonic, neighbor indices in range, every parallel
    array the correct length)."""
    failures: list[str] = []
    if not isinstance(graph, dict):
        return ["pathfinding graph must be an object"]
    if not isinstance(catalog, dict):
        return ["catalog must be an object"]

    if set(graph.keys()) != _TOP_LEVEL_KEYS:
        failures.append(f"graph has unexpected top-level keys: {sorted(graph.keys())}")
    if graph.get("schema_version") != PATHFINDING_GRAPH_SCHEMA_VERSION:
        failures.append(f"schema_version must be {PATHFINDING_GRAPH_SCHEMA_VERSION}")
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
    if isinstance(version, str) and not _VERSION_PATTERN.match(version):
        failures.append(f"pathfinding_graph_version {version!r} is not well-formed")
    if isinstance(version, str) and isinstance(snapshot_date, str):
        expected = pathfinding_graph_version(graph, snapshot_date)
        if version != expected:
            failures.append(
                f"pathfinding_graph_version {version!r} does not match recomputed content "
                f"(expected {expected!r})"
            )

    return failures
