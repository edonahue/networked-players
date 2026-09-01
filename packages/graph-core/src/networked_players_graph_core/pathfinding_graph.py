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

**v2 (ADR 0058): virtual album-anchor nodes.** For each catalog album, a
synthetic node (negative `virtual_artist_id`, disjoint from every real
positive Discogs artist id) is bidirectionally zero-cost-edge-connected to
every one of that album's real credited contributors (`album_credit_membership`,
Slice 2) already present in the bounded ego network. This turns a
record-to-record search into an ordinary single-source/single-sink BFS
between two virtual nodes -- the BFS core itself (`bfs_over_csr`/
`findPath`) needs no changes, only graph construction. An album with zero
in-scope credited contributors still gets a real, isolated virtual node
(`compact_graph_bench.build_csr_adjacency`'s `extra_node_ids`), so a search
against it is a confirmed "no-path," never a crash or a false
"unknown-album." New top-level field `album_virtual_nodes` gives the
frontend an explicit `album_id -> virtual_artist_id` map instead of
relying on the sign convention alone.

This is an OPERATOR-run build (like `build-album-art-registry`): it needs
the real one-hop working set on disk (`CreditGraph.open`, `build_edges=True`)
and is never run as part of `make check` or CI. The resulting artifact is
small enough to commit and fetch client-side.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from networked_players_contracts.canonical import content_hash

from .compact_graph_bench import build_csr_adjacency
from .eligibility import is_performer_role
from .graph import CreditGraph, edge_ineligible_role

_MAX_JOINED_ROLE_LEN = 200

# Never rendered -- apps/web/tests/game-connect-endpoints.spec.ts (Slice 7)
# asserts this string never reaches the DOM. Kept identical to the
# duplicated copy in networked_players_contracts.pathfinding_graph
# (that package stays dependency-free of graph-core, the same split every
# other contract/builder pair in this project already uses).
ALBUM_ANCHOR_SENTINEL = "__np_album_anchor__"


def _join_role_texts(texts: Iterable[str]) -> str:
    """Every distinct non-null role text, joined in the order first seen,
    bounded to `_MAX_JOINED_ROLE_LEN` total characters (a real measurement
    against the full corpus found a rare but genuine long tail -- an artist
    credited with dozens of near-duplicate role combinations across a large
    multi-track release joined to a 2,639-character string unbounded).
    Joined with ", " -- the same separator Discogs' own role_text already
    uses for multiple components within a single credit, and the exact
    separator both role-taxonomy classifiers
    (`role_taxonomy.classify_role`, `roleTaxonomy.ts`'s
    `matchesAnyComponent`) split on; a different separator is a real,
    confirmed regression (see git history on this function)."""
    seen: dict[str, None] = {}
    for text in texts:
        if text:
            seen.setdefault(str(text), None)
    if not seen:
        return "Credited artist"
    joined = ", ".join(seen)
    if len(joined) <= _MAX_JOINED_ROLE_LEN:
        return joined
    return joined[:_MAX_JOINED_ROLE_LEN].rsplit(", ", 1)[0] + "…"


def _joined_roles(rows: list[dict[str, Any]]) -> str:
    """`_join_role_texts` over a batch of raw `credit_rows_for_release_batch`
    rows for one artist on one release."""
    texts = (row.get("role_text") for row in rows)
    return _join_role_texts(text for text in texts if isinstance(text, str))


def _membership_roles_by_album(
    membership_by_album_id: dict[str, dict[str, Any]],
) -> dict[tuple[str, int], str]:
    """`(album_id, artist_id) -> joined role text`, computed directly from
    `album_credit_membership`'s own already-computed credits -- never a
    fresh graph lookup (Slice 2's artifact is the single canonical source
    for "who's credited on album X" and what role they held there)."""
    texts_by_key: dict[tuple[str, int], list[str]] = defaultdict(list)
    artist_ids_by_album: dict[str, set[int]] = defaultdict(set)
    for album_id, membership in membership_by_album_id.items():
        for credit in membership.get("credits", []):
            artist_id = int(credit["artist_id"])
            artist_ids_by_album[album_id].add(artist_id)
            role_text = credit.get("role_text")
            if role_text:
                texts_by_key[(album_id, artist_id)].append(str(role_text))
    return {
        (album_id, artist_id): _join_role_texts(texts_by_key.get((album_id, artist_id), []))
        for album_id, artist_ids in artist_ids_by_album.items()
        for artist_id in artist_ids
    }


def edge_eligible_membership_artist_ids(membership: dict[str, Any]) -> set[int]:
    """The artists on one album whose credits actually justify a traversal hop.

    `album_credit_membership` is deliberately inclusive -- it is an album's
    *credits list*, so a sleeve designer, a photographer and a lacquer-cutting
    engineer all belong in it, and the album page renders them. Turning that
    list 1:1 into album-anchor EDGES was a real traversal-policy gap: an
    album anchor must justify a hop by the same rule `credit_edges_sql` uses
    everywhere else, never a looser one just because one endpoint happens to
    be an album virtual node rather than another artist.

    So this applies `credit_edges_sql`'s own ADR 0068 performer gate --
    never a second copy of the rule -- at the right granularity: an artist
    is kept when ANY of their credits on the album qualifies, dropped only
    when EVERY one fails. Granularity is the whole fix. Evaluating the
    single joined display role instead would detach real catalog albums
    from their own billed artist (measured 2026-08-27, pre-ADR-0068: Bob
    Dylan from `Blood On The Tracks`, U2 from `The Joshua Tree`, Wu-Tang
    Clan from `36 Chambers`, ...), because the joined text for those happens
    to read `Written-By` or `Composed By`.

    A credit qualifies when its role text is not `edge_ineligible_role`
    (`credit_edges_sql`'s universal entry gate -- excludes both the
    composition/packaging-business/rework/audiovisual denylist AND
    quotation-style role text like `Performer [Sample]`/`Featuring [Samples
    From]`, which `is_performer_role` alone does not know to reject: its
    bracket-stripping normalizes `Performer [Sample]` down to `performer`,
    a real performer token, without the quotation check `edge_ineligible_role`
    applies -- round-1 Codex review finding on PR #204) AND EITHER: its
    `credit_scope` is `track_artist` or `release_artist` (billing -- always
    implicit performer-qualifying, regardless of role text, including a
    bare `NULL`-role main-artist billing -- the same rule that keeps a
    billed artist connected to their own record in `credit_edges_sql`), OR
    its `credit_scope` is `track_credit`/`release_credit` and its role text
    passes `eligibility.py`'s `is_performer_role` (ADR 0068).
    """
    credits_by_artist: dict[int, list[tuple[str | None, str]]] = defaultdict(list)
    for credit in membership.get("credits", []):
        role_text = credit.get("role_text")
        credits_by_artist[int(credit["artist_id"])].append(
            (
                str(role_text) if isinstance(role_text, str) else None,
                str(credit.get("credit_scope", "")),
            )
        )
    return {
        artist_id
        for artist_id, credits in credits_by_artist.items()
        if any(
            not edge_ineligible_role(role_text)
            and (credit_scope in ("track_artist", "release_artist") or is_performer_role(role_text))
            for role_text, credit_scope in credits
        )
    }


def pathfinding_graph_version(payload: dict[str, Any], snapshot_date: str) -> str:
    """Content hash over everything player-visible: node ids/names and the
    full CSR adjacency plus per-slot evidence -- changes on any published-
    field change, not just membership (mirrors
    `record_routes_artifact_version`'s "hash everything actually published"
    rule, ADR 0046's slice-9 addendum). v2 additionally hashes
    `album_virtual_nodes`."""
    identity: dict[str, Any] = {
        "node_ids": payload["node_ids"],
        "names": payload["names"],
        "offsets": payload["offsets"],
        "neighbors": payload["neighbors"],
        "evidence_release_ids": payload["evidence_release_ids"],
        "edge_role_a": payload["edge_role_a"],
        "edge_role_b": payload["edge_role_b"],
    }
    schema_version = int(payload.get("schema_version", 1))
    if schema_version >= 2:
        identity["album_virtual_nodes"] = payload["album_virtual_nodes"]
    digest = content_hash(identity, length=12)
    return f"pathfinding-graph-v{schema_version}-{snapshot_date}-{digest}"


def build_pathfinding_graph(
    graph: CreditGraph,
    catalog: dict[str, Any],
    album_credit_membership: dict[str, Any],
    *,
    snapshot_date: str,
    generated_at: str,
) -> dict[str, Any]:
    """Deterministic given the same real one-hop dataset, catalog, and
    album-credit-membership artifact: a 1-hop ego network around
    `catalog["albums"][].artist_id`, plus one virtual album-anchor node per
    catalog album (v2, ADR 0058), serialized as a CSR adjacency plus
    parallel-array names/edge-role evidence (so the frontend never needs a
    second fetch to render evidence for a found path)."""
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
    real_edges = sorted(seen_pairs)
    if not real_edges:
        raise ValueError("no edges found for this catalog's seed artists in the one-hop dataset")

    real_node_id_set: set[int] = set()
    for a, b, _release_id in real_edges:
        real_node_id_set.add(a)
        real_node_id_set.add(b)

    # --- virtual album-anchor nodes (ADR 0058) ------------------------------
    catalog_albums = sorted(catalog.get("albums", []), key=lambda a: str(a["id"]))
    membership_by_album_id = {
        str(m["album_id"]): m for m in album_credit_membership.get("albums", [])
    }
    membership_roles = _membership_roles_by_album(membership_by_album_id)

    album_virtual_nodes: list[dict[str, Any]] = []
    virtual_edges: list[tuple[int, int, int]] = []
    virtual_names: dict[int, str] = {}
    for index, album in enumerate(catalog_albums):
        album_id = str(album["id"])
        main_release_id = int(album["main_release_id"])
        virtual_id = -(index + 1)
        album_virtual_nodes.append(
            {
                "album_id": album_id,
                "virtual_artist_id": virtual_id,
                "main_release_id": main_release_id,
            }
        )
        virtual_names[virtual_id] = f"{album.get('title', album_id)} (album anchor)"
        membership = membership_by_album_id.get(album_id)
        if membership is None:
            continue  # no membership entry -- isolated virtual node, real edge case
        credited_artist_ids = edge_eligible_membership_artist_ids(membership)
        for artist_id in sorted(credited_artist_ids):
            if artist_id in real_node_id_set:
                virtual_edges.append((virtual_id, artist_id, main_release_id))

    all_edges = sorted(set(real_edges) | set(virtual_edges))
    virtual_ids = [vn["virtual_artist_id"] for vn in album_virtual_nodes]
    compact = build_csr_adjacency(all_edges, extra_node_ids=virtual_ids)

    # --- per-slot role text --------------------------------------------------
    real_release_ids = sorted({release_id for _a, _b, release_id in real_edges})
    credit_rows_by_release = graph.credit_rows_for_release_batch(real_release_ids)
    album_id_by_main_release_id = {
        vn["main_release_id"]: vn["album_id"] for vn in album_virtual_nodes
    }
    role_cache: dict[tuple[int, int], str] = {}

    def role_for(artist_id: int, neighbor_id: int, release_id: int) -> str:
        if artist_id < 0:
            return ALBUM_ANCHOR_SENTINEL
        if neighbor_id < 0:
            album_id = album_id_by_main_release_id.get(release_id)
            if album_id is None:
                return "Credited artist"
            return membership_roles.get((album_id, artist_id), "Credited artist")
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
            edge_role_a.append(role_for(artist_a_id, artist_b_id, release_id))
            edge_role_b.append(role_for(artist_b_id, artist_a_id, release_id))

    real_ids_for_name_query = [nid for nid in compact.node_ids if nid > 0]
    name_by_id: dict[int, str] = {}
    if real_ids_for_name_query:
        # `linked_credits` holds one row per CREDIT, so an artist carries as
        # many spellings as contributors typed -- "U2", "u2", "U 2". The
        # previous `SELECT DISTINCT` + `setdefault` kept whichever row
        # DuckDB happened to emit first, which is not a choice about
        # quality; measured against the published graph it left ~550 of
        # 36,819 display names visibly broken (149 lowercase, 198 ALL-CAPS,
        # 203 half-cased). Most-credited spelling wins instead, name-broken
        # ties, which is exactly the pattern `snapshot.py` already uses for
        # its own artist names -- the two artifacts now agree by
        # construction rather than by coincidence.
        #
        # The source string is never TRANSFORMED, only selected. Generic
        # title-casing would corrupt `will.i.am`, `deadmau5`, `k.d. lang`,
        # `P!nk` and `blink-182`, and no hand-maintained correction list is
        # introduced.
        name_rows = graph._connection.execute(
            "SELECT artist_id, name FROM linked_credits "
            f"WHERE artist_id IN ({', '.join(str(i) for i in real_ids_for_name_query)}) "
            "GROUP BY artist_id, name "
            "QUALIFY row_number() OVER "
            "(PARTITION BY artist_id ORDER BY count(*) DESC, name) = 1"
        ).fetchall()
        for artist_id, name in name_rows:
            name_by_id[int(artist_id)] = str(name)
    names = [
        virtual_names[node_id] if node_id < 0 else name_by_id.get(node_id, f"Artist {node_id}")
        for node_id in compact.node_ids
    ]

    payload: dict[str, Any] = {
        "schema_version": 2,
        "catalog_version": catalog["catalog_version"],
        "snapshot_date": snapshot_date,
        "generated_at": generated_at,
        "source": (
            "Discogs monthly data dump (CC0), one-hop working set, scoped to a "
            "1-hop ego network around the canonical catalog's primary artists "
            "(ADR 0050), plus one virtual album-anchor node per catalog album "
            "(ADR 0058). See docs/DATA_AND_RIGHTS.md."
        ),
        "license": "Derived from the Discogs monthly CC0 data dumps. See docs/DATA_AND_RIGHTS.md.",
        "node_ids": compact.node_ids,
        "names": names,
        "offsets": compact.offsets,
        "neighbors": compact.neighbors,
        "evidence_release_ids": compact.evidence_release_ids,
        "edge_role_a": edge_role_a,
        "edge_role_b": edge_role_b,
        "album_virtual_nodes": album_virtual_nodes,
    }
    payload["pathfinding_graph_version"] = pathfinding_graph_version(payload, snapshot_date)
    return payload
