# Pathfinding graph contract (pathfinding-graph-v1)

The public pathfinding graph
(`apps/web/public/data/pathfinding/graph.v1.json`), produced by
`networked-players-catalog build-pathfinding-graph` and validated by
`validate-pathfinding-graph` /
`networked_players_contracts.pathfinding_graph::pathfinding_graph_failures`
(ADR 0050/0051).

> **Bounded scope, not the full one-hop corpus.** This graph is a 1-hop ego
> network around the canonical catalog's primary artists — not the entire
> one-hop working set. ADR 0050's real measurement found the full corpus (and
> even a 2-hop expansion from a few hundred seed artists) too large for a
> browser-downloadable payload; this artifact's scope is the one ADR 0050's
> evidence supports.

## Top-level shape

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | int | Always `1`. |
| `catalog_version` | string | The canonical `catalog/albums.v1.json` version this graph belongs to. |
| `snapshot_date` | string | The Discogs snapshot the underlying one-hop dataset was built from. |
| `generated_at` | string | Explicit operator-supplied ISO datetime. |
| `source` / `license` | string | Provenance; see `docs/DATA_AND_RIGHTS.md`. |
| `node_ids` | array of int | Sorted, deduplicated Discogs artist ids — node index `i` is this array's `i`-th entry. |
| `names` | array of string | Parallel to `node_ids`: `names[i]` is `node_ids[i]`'s display name. |
| `offsets` | array of int | CSR row offsets, length `len(node_ids) + 1`. `neighbors[offsets[i]:offsets[i+1]]` are node index `i`'s neighbors. |
| `neighbors` | array of int | Neighbor node *index* (not artist_id) for every directed adjacency slot. |
| `evidence_release_ids` | array of int | Parallel to `neighbors`: the release id evidencing that slot's edge. |
| `edge_role_a` / `edge_role_b` | array of string | Parallel to `neighbors`: verbatim role text for the slot's own node (`role_a`) and its neighbor (`role_b`). |
| `pathfinding_graph_version` | string | `pathfinding-graph-v1-<snapshot>-<hash>` — content hash over every field above. |

**Why parallel arrays, not `{key: value}` objects per edge/node**: measured
during Slice F's build — an equivalent array-of-objects shape (one `{
artist_a_id, artist_b_id, release_id, role_a, role_b}` object per edge, one
`{artist_id: name}` map for names) gzipped roughly 15x larger than this
shape at this graph's real size (~61K edges / ~37K nodes), because JSON
object-key repetition compresses far worse than repeated short values in a
flat array. This mirrors `compact_graph_bench.py`'s own typed-array CSR
design, extended to the evidence fields.

**Real measured size** (this artifact, generated 2026-08-03): 36,819 nodes,
60,696 edges, ~10.4 MB raw JSON, ~1.8 MB gzip-compressed. Larger than the
previous largest shipped artifact (`routes/rounds.v1.json`, ~130 KB gzip) —
an honest correction to ADR 0050's initial estimate, which measured only the
bare CSR topology without role-text/name evidence. Brotli was not measured;
likely smaller than gzip. Fetched only on `/play/connect/` (Slice F), never
on the homepage or any other page load.

**Re-measured** (Phase 4 Slice 4, generated 2026-08-08, ADR 0058): fixing a
real per-edge role-text defect (`_representative_role` kept only the first
of an artist's distinct roles on a release, truncated to 60 characters,
silently discarding the rest) to instead join every distinct role, bounded
to 200 characters, changed real size to ~14 MB raw / **~2.26 MB gzip**
(same 36,819 nodes / 60,696 edges — a content change, not a structural
one). This is the current real number; the 2026-08-03 figures above are
historical.

## Validation

`pathfinding_graph_failures(graph, catalog)` checks: exact top-level key
set, `schema_version == 1`, `catalog_version` agreement with the canonical
catalog, `node_ids` sorted/deduplicated, `names` the same length as
`node_ids`, `offsets` monotonic non-decreasing starting at 0 and of the
correct length, every `neighbors[]` entry a valid node index,
`evidence_release_ids`/`edge_role_a`/`edge_role_b` all the same length as
`neighbors`, and `pathfinding_graph_version` recomputation.

## Revisit trigger

If Brotli compression or a future exploration tier (ADR 0049) changes the
size calculus, or if real usage shows the ~1.8 MB gzip fetch is too heavy
for the intended UX, revisit the scope (a smaller seed set, per-node fan-out
capping) before assuming a different serialization format would help more
than the parallel-array shape already provides.
