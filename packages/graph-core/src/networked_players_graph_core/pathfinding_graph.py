"""Build the public pathfinding graph -- a compact, browser-downloadable CSR
adjacency (see `compact_graph_bench.py`) scoped to a bounded 1-hop
neighborhood around a seed album catalog's primary artists, per ADR 0050's
measured conclusion that browser-local search is viable only at this scope,
not the full one-hop corpus.

Every per-edge/per-node field is a PARALLEL ARRAY aligned with the CSR
arrays (`names[i]` is `node_ids[i]`'s display name; `edge_role_a[slot]`/
`edge_role_b[slot]` describe the same directed slot as `neighbors[slot]`/
`evidence_release_ids[slot]`) -- never an array of `{key: value, ...}`
objects. A real measurement during Slice F found that shape gzips roughly
15x larger than this one at this graph's real size (~61K edges): JSON
object-key repetition (`"artist_a_id"`, `"role_a"`, ...) compresses far
worse than repeated short values in a flat array. This is the same
compactness principle `compact_graph_bench.py`'s typed-array CSR arrays
already apply, extended to the evidence fields.

This is an OPERATOR-run build (like `build-album-art-registry`): it needs
the real one-hop working set on disk (`CreditGraph.open`, `build_edges=True`)
and is never run as part of `make check` or CI. The resulting artifact is
small enough to commit and fetch client-side.
"""

from __future__ import annotations

from typing import Any

from networked_players_contracts.canonical import content_hash

from .compact_graph_bench import build_csr_adjacency
from .graph import CreditGraph

_MAX_JOINED_ROLE_LEN = 200


def _joined_roles(rows: list[dict[str, Any]]) -> str:
    """Every distinct non-null role_text among an artist's credit rows on
    one release, joined in the order first seen -- not just the first role
    found (that was real, silent data loss: a producer/engineer/performer
    on the same release previously lost every role but one, truncated to
    60 characters besides). A generic fallback covers a bare release-artist
    billing (edge-eligible per `credit_edges_sql`, but with no descriptive
    role text).

    The joined string itself is still bounded (`_MAX_JOINED_ROLE_LEN`): a
    real measurement against the full corpus found a rare but genuine long
    tail -- an artist credited with dozens of near-duplicate role
    combinations across a large multi-track release joined to a 2,639-
    character string. Truncating the final joined text (never a single
    role's own text) keeps the common case fully intact while bounding
    that tail, rather than reintroducing per-role truncation."""
    seen: dict[str, None] = {}
    for row in rows:
        role_text = row.get("role_text")
        if role_text:
            seen.setdefault(str(role_text), None)
    if not seen:
        return "Credited artist"
    joined = "; ".join(seen)
    if len(joined) <= _MAX_JOINED_ROLE_LEN:
        return joined
    return joined[:_MAX_JOINED_ROLE_LEN].rsplit("; ", 1)[0] + "…"


def pathfinding_graph_version(payload: dict[str, Any], snapshot_date: str) -> str:
    """Content hash over everything player-visible: node ids/names and the
    full CSR adjacency plus per-slot evidence -- changes on any published-
    field change, not just membership (mirrors
    `record_routes_artifact_version`'s "hash everything actually published"
    rule, ADR 0046's slice-9 addendum)."""
    identity = {
        "node_ids": payload["node_ids"],
        "names": payload["names"],
        "offsets": payload["offsets"],
        "neighbors": payload["neighbors"],
        "evidence_release_ids": payload["evidence_release_ids"],
        "edge_role_a": payload["edge_role_a"],
        "edge_role_b": payload["edge_role_b"],
    }
    digest = content_hash(identity, length=12)
    return f"pathfinding-graph-v1-{snapshot_date}-{digest}"


def build_pathfinding_graph(
    graph: CreditGraph,
    catalog: dict[str, Any],
    *,
    snapshot_date: str,
    generated_at: str,
) -> dict[str, Any]:
    """Deterministic given the same real one-hop dataset and catalog: a
    1-hop ego network around `catalog["albums"][].artist_id`, serialized as
    a CSR adjacency plus parallel-array names/edge-role evidence (so the
    frontend never needs a second fetch to render evidence for a found
    path)."""
    seed_artist_ids = sorted({int(a["artist_id"]) for a in catalog["albums"]})
    if not seed_artist_ids:
        raise ValueError("catalog has no albums to seed the pathfinding graph from")

    ids_sql = ", ".join(str(i) for i in seed_artist_ids)
    rows = graph._connection.execute(
        f"SELECT artist_a_id, artist_b_id, release_id FROM credit_edges "
        f"WHERE artist_a_id IN ({ids_sql}) OR artist_b_id IN ({ids_sql})"
    ).fetchall()

    seen_pairs: set[tuple[int, int, int]] = set()
    for a, b, release_id in rows:
        a, b = int(a), int(b)
        key = (min(a, b), max(a, b), int(release_id))
        seen_pairs.add(key)
    edges = sorted(seen_pairs)
    if not edges:
        raise ValueError("no edges found for this catalog's seed artists in the one-hop dataset")

    compact = build_csr_adjacency(edges)

    release_ids = sorted({release_id for _a, _b, release_id in edges})
    credit_rows_by_release = graph.credit_rows_for_release_batch(release_ids)
    role_cache: dict[tuple[int, int], str] = {}

    def role_for(artist_id: int, release_id: int) -> str:
        key = (artist_id, release_id)
        cached = role_cache.get(key)
        if cached is not None:
            return cached
        rows_for_artist = [
            r for r in credit_rows_by_release.get(release_id, []) if r["artist_id"] == artist_id
        ]
        role = _joined_roles(rows_for_artist)
        role_cache[key] = role
        return role

    edge_role_a: list[str] = []
    edge_role_b: list[str] = []
    # One pass over nodes/slots in CSR row order -- offsets/neighbors are
    # already structured this way, so each slot's owning node is known
    # without a per-slot search.
    for node_index in range(len(compact.node_ids)):
        artist_a_id = compact.node_ids[node_index]
        start, end = compact.offsets[node_index], compact.offsets[node_index + 1]
        for slot in range(start, end):
            neighbor_index = compact.neighbors[slot]
            artist_b_id = compact.node_ids[neighbor_index]
            release_id = compact.evidence_release_ids[slot]
            edge_role_a.append(role_for(artist_a_id, release_id))
            edge_role_b.append(role_for(artist_b_id, release_id))

    name_rows = graph._connection.execute(
        "SELECT DISTINCT artist_id, name FROM linked_credits "
        f"WHERE artist_id IN ({', '.join(str(i) for i in compact.node_ids)})"
    ).fetchall()
    name_by_id: dict[int, str] = {}
    for artist_id, name in name_rows:
        name_by_id.setdefault(int(artist_id), str(name))
    names = [name_by_id.get(node_id, f"Artist {node_id}") for node_id in compact.node_ids]

    payload: dict[str, Any] = {
        "schema_version": 1,
        "catalog_version": catalog["catalog_version"],
        "snapshot_date": snapshot_date,
        "generated_at": generated_at,
        "source": (
            "Discogs monthly data dump (CC0), one-hop working set, scoped to a "
            "1-hop ego network around the canonical catalog's primary artists "
            "(ADR 0050). See docs/DATA_AND_RIGHTS.md."
        ),
        "license": "Derived from the Discogs monthly CC0 data dumps. See docs/DATA_AND_RIGHTS.md.",
        "node_ids": compact.node_ids,
        "names": names,
        "offsets": compact.offsets,
        "neighbors": compact.neighbors,
        "evidence_release_ids": compact.evidence_release_ids,
        "edge_role_a": edge_role_a,
        "edge_role_b": edge_role_b,
    }
    payload["pathfinding_graph_version"] = pathfinding_graph_version(payload, snapshot_date)
    return payload
