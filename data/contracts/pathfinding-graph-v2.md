# Pathfinding graph contract (pathfinding-graph-v2)

The public pathfinding graph
(`apps/web/public/data/pathfinding/graph.v2.json`), produced by
`networked-players-catalog build-pathfinding-graph` and validated by
`validate-pathfinding-graph` /
`networked_players_contracts.pathfinding_graph::pathfinding_graph_failures`
(ADR 0050/0051/0058).

> **v2 adds virtual album-anchor nodes.** Everything `pathfinding-graph-v1.md`
> says about the real 1-hop ego network (bounded scope, parallel-array
> shape, real measured size) still holds — v2 is the same graph plus one
> synthetic node per catalog album, bidirectionally connected to that
> album's real credited contributors (`album-credit-membership.v1.json`,
> ADR 0058). This is what lets a record-to-record search anchor its two
> endpoints on real album personnel instead of one primary artist_id
> (ADR 0051's original, narrower mechanism).

## What changed from v1

Every v1 field keeps its exact same meaning. v2 adds:

| Field | Type | Meaning |
| --- | --- | --- |
| `album_virtual_nodes` | array of object | One entry per catalog album — see below. |

Each `node_ids[i]` may now be **negative** — a virtual album-anchor id,
disjoint by construction from every real (positive) Discogs artist id.
`names[i]` for a virtual node is `"<album title> (album anchor)"`, never
rendered directly (a UI must recognize the anchor via `album_virtual_nodes`
or the sign of the id, not by parsing this string).

Every CSR slot touching a virtual node uses a reserved sentinel role text,
`__np_album_anchor__`, on the virtual side only — never rendered, and
asserted absent from the DOM by `apps/web/tests/game-connect-endpoints.spec.ts`
(Slice 7). The *real* side of that same slot carries the real credited
contributor's actual role on that album, copied directly from
`album-credit-membership.v1.json` — never a fresh graph lookup, so it can
never drift from the single canonical membership answer.

## `album_virtual_nodes[]` entry shape

| Field | Type | Meaning |
| --- | --- | --- |
| `album_id` | string | Canonical catalog album id. Must exist in `catalog/albums.v1.json`. Unique across the array. |
| `virtual_artist_id` | int | Negative, unique, disjoint from every real node id. This is the id a client uses as `findAlbumRoute`'s search endpoint for this album. |
| `main_release_id` | int | Must equal the catalog's own `main_release_id` for this album — the same release `album-credit-membership.v1.json` used. |

An album with zero in-scope credited contributors (all of its personnel
fall outside the bounded ego network, or it has no membership entry) still
gets a real, isolated virtual node — present in `node_ids` with zero
neighbors, never silently dropped. A search against it is a confirmed
`no-path`, never a crash or a false `unknown-album`.

## Validation

`pathfinding_graph_failures(graph, catalog)` runs every v1 check
(structural CSR invariants, `catalog_version` agreement, version
recomputation) plus, when `schema_version == 2`: every `album_virtual_nodes`
entry resolves against the canonical catalog with no duplicate `album_id`
or `virtual_artist_id`, every `virtual_artist_id` is a negative integer
disjoint from real node ids and present in `node_ids`, and every CSR
slot's sentinel-role placement agrees with whether its owning/neighbor
node is virtual (the sentinel appears exactly on the virtual side of a
slot, never elsewhere).

## Revisit trigger

If a future change needs virtual nodes to carry more than a single
bidirectional zero-cost edge per credited contributor (e.g. weighting by
credit prominence), that is a real, separate design decision — extend
this contract explicitly, or add a clearly-named `v3`.

**Addendum (2026-09-01): a v3 exists, for a different reason.**
`pathfinding-graph-v3.md` adds `graph_policy_version` (ADR 0068's performer
gate) — not the credit-prominence-weighting trigger this section
anticipated, which has not happened. `graph.v2.json` remains this
document's live, unedited artifact; v3 is a new, additive, dual-live file,
not a replacement, until a later cutover PR retires v2 the same way this
file's own v1 retirement addendum describes.

**Addendum (2026-08-09): v1 retirement completed.** The original plan
above (retire once Connect Two Records cuts over) undercounted the real
consumer set — Network Explorer also fetched `graph.v1.json` and wasn't
migrated when Connect cut over in Slice 7. `graph.v1.json` is now deleted
and its `pathfinding_graph` (v1) group dropped from
`validate-public-artifacts`/`PUBLIC_ARTIFACT_GROUPS` only after Explorer's
own migration (`buildView` in `networkExplorer.ts` now excludes v2's
virtual album-anchor nodes from its neighbor walk, since Explorer centers
on real people, never a synthetic album anchor). See
`pathfinding-graph-v1.md`'s own updated retirement note.
