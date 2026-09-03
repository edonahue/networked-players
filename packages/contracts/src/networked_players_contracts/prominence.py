"""Canonical, dependency-free validation for the public prominence sidecar.

`prominence-v1` (`apps/web/public/data/pathfinding/prominence.v1.json`,
`data/contracts/prominence-v1.md`, graph-expansion Phase 1, plan section 8)
is a node-aligned companion to the pathfinding graph: parallel int arrays
(`degree`, `albums_1hop`, `albums_2hop`, `evidence_releases`,
`role_diversity`, `first_year`, `last_year`, `rank`), same length and order
as the pathfinding graph's own `node_ids` -- so a client already holding a
node's CSR row index can read its prominence row with the identical index,
no separate lookup. A separate file, not a field grafted onto the
pathfinding graph, pinned to that graph's own `pathfinding_graph_version` --
a ranking-formula tweak alone never forces a graph rebuild, and this
validator's `pathfinding_graph_version`/`node_ids` cross-check catches a
stale sidecar paired with a since-regenerated graph.

Pure Python (no lxml/pyarrow/duckdb), safe for the Pi fleet and the web
build to independently verify an already-generated sidecar against the
canonical pathfinding graph it claims to belong to.
"""

from __future__ import annotations

import re
from typing import Any

from .canonical import content_hash

PROMINENCE_SCHEMA_VERSION = 1

_VERSION_PATTERN = re.compile(r"^prominence-v1-[0-9A-Za-z]+-[0-9a-f]{12}$")

_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "catalog_version",
        "pathfinding_graph_version",
        "prominence_version",
        "generated_at",
        "source",
        "license",
        "node_ids",
        "degree",
        "albums_1hop",
        "albums_2hop",
        "evidence_releases",
        "role_diversity",
        "first_year",
        "last_year",
        "rank",
    }
)

# Every parallel array that must be int-valued, non-negative, and the same
# length as `node_ids`. `first_year`/`last_year` are validated separately
# (int-or-null, and a first<=last relationship), and `rank` may legitimately
# be 0 for a node with no signal at all, so it stays in this non-negative
# group rather than needing its own separate check.
_NON_NEGATIVE_INT_ARRAY_FIELDS = (
    "degree",
    "albums_1hop",
    "albums_2hop",
    "evidence_releases",
    "role_diversity",
    "rank",
)


def prominence_version(payload: dict[str, Any], snapshot_date: str) -> str:
    """Recomputation mirror of the generation-time function in
    `networked_players_graph_core.prominence` -- duplicated here
    deliberately (this package stays dependency-free of graph-core, the
    same split every other contract/builder pair in this project already
    uses)."""
    identity = {
        "pathfinding_graph_version": payload.get("pathfinding_graph_version"),
        "node_ids": payload.get("node_ids"),
        "degree": payload.get("degree"),
        "albums_1hop": payload.get("albums_1hop"),
        "albums_2hop": payload.get("albums_2hop"),
        "evidence_releases": payload.get("evidence_releases"),
        "role_diversity": payload.get("role_diversity"),
        "first_year": payload.get("first_year"),
        "last_year": payload.get("last_year"),
        "rank": payload.get("rank"),
    }
    digest = content_hash(identity, length=12)
    return f"prominence-v1-{snapshot_date}-{digest}"


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def prominence_failures(artifact: Any, pathfinding_graph: Any) -> list[str]:
    """Every contract failure in a prominence sidecar, validated against the
    canonical pathfinding graph it's a companion to."""
    failures: list[str] = []
    if not isinstance(artifact, dict):
        return ["prominence artifact must be an object"]
    if not isinstance(pathfinding_graph, dict):
        return ["pathfinding_graph must be an object"]

    actual_keys = set(artifact.keys())
    if actual_keys != _TOP_LEVEL_KEYS:
        failures.append(f"artifact has unexpected top-level keys: {sorted(actual_keys)}")

    if artifact.get("schema_version") != PROMINENCE_SCHEMA_VERSION:
        failures.append(f"schema_version must be {PROMINENCE_SCHEMA_VERSION}")

    for field_name in (
        "catalog_version",
        "pathfinding_graph_version",
        "prominence_version",
        "generated_at",
        "source",
        "license",
    ):
        if not artifact.get(field_name):
            failures.append(f"{field_name} is required and must be non-empty")

    graph_catalog_version = pathfinding_graph.get("catalog_version")
    if artifact.get("catalog_version") != graph_catalog_version:
        failures.append(
            f"artifact catalog_version {artifact.get('catalog_version')!r} does not match "
            f"the pathfinding graph's catalog_version {graph_catalog_version!r}"
        )

    graph_pgv = pathfinding_graph.get("pathfinding_graph_version")
    if artifact.get("pathfinding_graph_version") != graph_pgv:
        failures.append(
            f"artifact pathfinding_graph_version {artifact.get('pathfinding_graph_version')!r} "
            f"does not match the pathfinding graph's own "
            f"pathfinding_graph_version {graph_pgv!r} -- a stale sidecar paired with a "
            f"since-regenerated graph"
        )

    node_ids = artifact.get("node_ids")
    graph_node_ids = pathfinding_graph.get("node_ids")
    if not isinstance(node_ids, list):
        failures.append("node_ids must be an array")
        node_ids = []
    elif isinstance(graph_node_ids, list) and node_ids != graph_node_ids:
        failures.append(
            "node_ids must be identical (same order) to the pathfinding graph's own node_ids"
        )
    node_count = len(node_ids)

    for field_name in _NON_NEGATIVE_INT_ARRAY_FIELDS:
        values = artifact.get(field_name)
        if not isinstance(values, list) or len(values) != node_count:
            failures.append(f"{field_name} must be an array of length {node_count}")
            continue
        if any(not _is_int(v) or v < 0 for v in values):
            failures.append(f"{field_name} must contain only non-negative integers")

    first_year = artifact.get("first_year")
    last_year = artifact.get("last_year")
    for field_name, values in (("first_year", first_year), ("last_year", last_year)):
        if not isinstance(values, list) or len(values) != node_count:
            failures.append(f"{field_name} must be an array of length {node_count}")
    if (
        isinstance(first_year, list)
        and isinstance(last_year, list)
        and len(first_year) == node_count
        and len(last_year) == node_count
    ):
        for i in range(node_count):
            fy, ly = first_year[i], last_year[i]
            if fy is not None and not _is_int(fy):
                failures.append(f"first_year[{i}] must be an integer or null")
                continue
            if ly is not None and not _is_int(ly):
                failures.append(f"last_year[{i}] must be an integer or null")
                continue
            if (fy is None) != (ly is None):
                failures.append(f"first_year[{i}]/last_year[{i}] must be both null or both set")
            elif fy is not None and ly is not None and fy > ly:
                failures.append(f"first_year[{i}] must be <= last_year[{i}]")

    version = artifact.get("prominence_version")
    if isinstance(version, str) and not _VERSION_PATTERN.match(version):
        failures.append(
            f"prominence_version {version!r} is not a well-formed prominence-v1 version"
        )
    snapshot_date = pathfinding_graph.get("snapshot_date")
    if isinstance(version, str) and isinstance(snapshot_date, str):
        expected = prominence_version(artifact, snapshot_date)
        if version != expected:
            failures.append(
                f"prominence_version {version!r} does not match the artifact's own "
                f"recomputed content (expected {expected!r})"
            )

    return failures
