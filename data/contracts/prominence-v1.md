# Prominence sidecar contract (prominence-v1)

The public prominence sidecar
(`apps/web/public/data/pathfinding/prominence.v1.json`), produced by
`networked-players-catalog build-prominence` and validated by
`validate-prominence` /
`networked_players_contracts.prominence::prominence_failures`
(graph-expansion Phase 1, `docs/GRAPH_EXPANSION_DIRECTION.md` plan section 8).

> **A node-aligned companion to the pathfinding graph, not a field on it.**
> Every field is a parallel array, same length and order as the pathfinding
> graph's own `node_ids` -- a client already holding a node's CSR row index
> can read its prominence row with the identical index, no separate lookup.
> A separate file, pinned to that graph's own `pathfinding_graph_version`,
> so a ranking-formula tweak alone never forces a graph rebuild, and this
> artifact's own validator catches a stale sidecar paired with a
> since-regenerated graph.

## Why this exists

Explore's neighbor ordering and label visibility previously had no real
ranking signal at all -- the contributor index's `connection_count` only
covers indexed contributors (~445 of them, real-corpus measured), and most
pathfinding-graph neighbors tie at 0 there. This sidecar gives every real
performer node a precomputed, explainable set of structural signals, so
Explore can rank and page neighbors without a client-side full-graph
traversal.

## Fields

Every array below has exactly `len(node_ids)` entries, aligned index-for-
index with the pathfinding graph's own `node_ids` (virtual album-anchor
nodes included -- see the anchor row note below).

| Field | Type | Meaning |
| --- | --- | --- |
| `node_ids` | `int[]` | Identical (same order) to the pathfinding graph's own `node_ids` -- included here so a client can confirm alignment without fetching the graph first. |
| `degree` | `int[]`, >= 0 | The node's own CSR row length (real neighbor count, anchor edges included) -- "connected to N performers". A real, meaningful value for EVERY node, anchors included (an anchor's degree is its album's real credited-contributor count). |
| `albums_1hop` | `int[]`, >= 0 | Count of directly-connected virtual album-anchor neighbors -- "plays on N catalog albums". Zero on an anchor's own row (an anchor is never itself ranked). |
| `albums_2hop` | `int[]`, >= 0 | Count of distinct album anchors reachable via exactly one real intermediate neighbor, EXCLUDING anchors already counted at 1 hop -- "one step from N albums": who this performer's collaborators reach that this performer does not reach directly. Zero on an anchor's own row. |
| `evidence_releases` | `int[]`, >= 0 | Count of distinct `evidence_release_ids` across the node's own row -- "documented on N releases". Zero on an anchor's own row. |
| `role_diversity` | `int[]`, >= 0 | Count of distinct `RoleCategory` classifications across the node's own row's role text (its OWN role on each edge, never the neighbor's), excluding the album-anchor sentinel. Shown, never weighted into `rank`. Zero on an anchor's own row. |
| `first_year` / `last_year` | `int \| null` each | Min/max real release year across the node's own evidence releases (via the evidence-release registry), both `null` together when no evidence release has a known year -- "active 1968-2004". Both `null` on an anchor's own row. |
| `rank` | `int[]`, >= 0 | A documented, monotone weighted combination -- see "Rank formula" below. Zero on an anchor's own row. |

## Rank formula

```
rank = 50 * albums_2hop
     + 50 * decade_span        # last_year - first_year, 0 when years unknown
     + 10 * albums_1hop
     +  1 * degree
     +  1 * evidence_releases
```

`albums_2hop` and `decade_span` are weighted highest -- the plan's own
discovery-goal decision (bridges between scenes/eras, and band lineups and
their orbits): a performer reaching many anchors across decades is a
bridge. `albums_1hop` next, then `degree` (deliberately NOT the dominant
term -- a raw-degree-led ranking is exactly the hub trap the plan's own
measurement warned against), then `evidence_releases`. `role_diversity` is
shown, never weighted (rewards structural reach, not versatility).

This is an honestly-labeled APPROXIMATION via weighted sum, not a strict
lexicographic guarantee against every possible extreme combination of
inputs. The plan itself frames `rank` as "tuned to the owner's stated
discovery goals" -- iteration against real Explore usage is expected, not
a single perfect formula on the first attempt. A future retune only ever
changes this file's weights and regenerates the real artifact; it never
requires a pathfinding-graph rebuild (that is the whole reason this is a
separate, `pathfinding_graph_version`-pinned sidecar).

## Computing `albums_2hop` cheaply

The real corpus is heavy-tailed enough that a handful of nodes carry
500+ edges (real-corpus measured). A brute-force two-hop walk (every
neighbor's every neighbor) would be genuinely expensive for those nodes.
Instead: every node's own `albums_1hop` SET is small and bounded by how
many catalog albums that one person is actually credited on, independent
of their overall degree. `albums_2hop` for node P is then the union of
each of P's real (non-anchor) neighbors' own small `albums_1hop` set,
minus P's own set -- cost bounded by `degree(P) * (small constant)`, never
`degree(P)^2`.

## Real measured effect (2026-09-03, real committed catalog and one-hop
corpus)

Built from the real committed `graph.v4.json` (20,845 nodes) and
`evidence/release-registry.v1.json`: 1,030,416 raw bytes, 183,564 gzip
bytes. Both real byte counts of a public artifact's encoding, not hardware
performance data, so published directly here rather than routed through
`local/benchmarks/` (ADR 0018 restricts elapsed-time/throughput/memory-on-
this-hardware numbers, not artifact-size facts -- the same precedent
`pathfinding-graph-v4.md`'s own measured-effect table already sets).

## Validation

`prominence_failures(artifact, pathfinding_graph)` checks: exact top-level
key set; `schema_version == 1`; every metadata string non-empty;
`catalog_version`/`pathfinding_graph_version` agreement with the supplied
pathfinding graph; `node_ids` identical (same order) to the graph's own;
every parallel array present with length `len(node_ids)`; `degree`,
`albums_1hop`, `albums_2hop`, `evidence_releases`, `role_diversity`, `rank`
all non-negative integers; `first_year`/`last_year` both null or both set
per node, with `first_year <= last_year` when set; `prominence_version`
well-formed and recomputed from content.

## Status: real, committed, live

Built once against the real committed `graph.v4.json` and
`evidence/release-registry.v1.json`
(`prominence-v1-20260601-86774b7177fe`), registered as its own `prominence`
group in `PUBLIC_ARTIFACT_GROUPS`, `_artifact_validators()`, and
`scripts/submit_artifact_check.py`'s `_DEFAULT_ARTIFACTS`. Not yet consumed
by any real page -- `explorerStage.ts`'s neighbor-ranking cutover is
separate, later Phase 1 work, the same staged pattern `graph.v4.json`
itself used (publish the artifact and its validators first, wire the real
consumer as its own step).

## Revisit trigger

If Explore's real usage shows `rank`'s relative weights favor the wrong
kind of neighbor (e.g. still surfacing hubs too often, or under-ranking a
genuinely structural bridge), retune the weights in
`networked_players_graph_core.prominence` and
`networked_players_contracts.prominence` stays untouched (it validates
shape, not specific weight values) -- regenerate the real artifact; no
schema-version bump needed unless a FIELD is added or removed, not just a
weight retune.
