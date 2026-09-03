# Pathfinding graph contract (pathfinding-graph-v4)

The public pathfinding graph's role-dictionary encoding
(graph-expansion Phase 1, `docs/GRAPH_EXPANSION_DIRECTION.md`), produced by
`networked-players-catalog build-pathfinding-graph --schema-version 4` and
validated by `validate-pathfinding-graph` /
`networked_players_contracts.pathfinding_graph::pathfinding_graph_failures`.

> **Not yet a published artifact.** This contract documents a real, tested
> builder + validator capability landed ahead of publication, the same
> sequencing the catalog schema v2 capability (ADR 0069) used. `graph.v3.json`
> remains the only published pathfinding graph until v4 is actually built,
> published as `graph.v4.json`, and every real consumer (Connect, Explore,
> the private research workbench, the fleet artifact-check default) has cut
> over — the same dual-live-then-retire precedent `pathfinding-graph-v3.md`
> itself describes for v2 → v3.

## What changed from v3

Every v3 field keeps its exact same meaning; the edge SET, node set,
`album_virtual_nodes`, and `graph_policy_version` are byte-for-byte
identical — v4 only changes how role text is encoded:

| Field | v3 | v4 |
| --- | --- | --- |
| `roles` | *(absent)* | New: every distinct role-text string across `edge_role_a`/`edge_role_b`, first-seen order. No duplicates. |
| `edge_role_a` | `string[]` — the role text itself | `int[]` — an index into `roles` |
| `edge_role_b` | `string[]` — the role text itself | `int[]` — an index into `roles` |

Nothing else changes shape or meaning. Given the same real one-hop dataset,
catalog, and album-credit-membership artifact, a v4 build's `roles[edge_role_a[slot]]`
equals the corresponding v3 build's `edge_role_a[slot]` exactly, for every
slot — a pure re-encoding, never a lossy or reordering transform of the
underlying role assignment (`test_v4_dictionary_encodes_roles`).

## Real measured effect (2026-09-03, `discogs-onehop-v4`, `snapshot=20260601`)

Built from the same real committed catalog (179 albums) and one-hop corpus
`graph.v3.json` already uses — same 20,845 nodes, 38,323 undirected (76,646
directed) edges, 179 album anchors, byte-for-byte identical edge set:

| Metric | v3 | v4 | Change |
| --- | --- | --- | --- |
| Raw JSON bytes | 8,292,647 | 4,848,644 | **−41.5%** |
| Gzip bytes | 1,317,241 | 1,001,541 | **−24.0%** |
| Distinct role strings (`roles.length`) | n/a (inline, repeated) | 11,807 | over 76,646 slots |

Gzip's win is smaller than raw's because `edge_role_a`/`edge_role_b`'s
repeated short strings already compress reasonably well — the dictionary
mainly removes the repetition gzip was already partially capturing, not a
new compression opportunity. Both numbers are real byte counts of a public
artifact's encoding, not hardware performance data, so they're published
directly here rather than routed through `local/benchmarks/` (ADR 0018
restricts elapsed-time/throughput/memory-on-this-hardware numbers, not
artifact-size facts — the same precedent `pathfinding-graph-v3.md`'s own
measured-effect table already sets for node/edge counts).

## Validation

`pathfinding_graph_failures(graph, catalog)` runs every v3 check unchanged
(structural CSR invariants, `catalog_version` agreement, version
recomputation, `album_virtual_nodes` catalog-coverage, `graph_policy_version`
positivity) plus, when `schema_version == 4`:

- `roles` must be an array of strings.
- `edge_role_a`/`edge_role_b` must be arrays of non-negative integers, each
  a valid index into `roles` (rather than arrays of strings, as v1-3
  require) — a v3 payload accidentally stamped `schema_version: 4` fails
  this check rather than silently validating.
- The album-anchor sentinel-placement check resolves each slot's role
  index through `roles` before comparing to the sentinel string, so a
  misplaced sentinel is still caught exactly as it is in v1-3.

`pathfinding_graph_version` additionally hashes `roles` for schema_version
4, so two v4 graphs with the same edges but a different role dictionary
(e.g. after `eligibility.py`'s token set changes) never collide on a
recomputed hash.

## Status: not published

`build_pathfinding_graph`'s `schema_version` parameter defaults to 3 — every
existing caller (the real `graph.v3.json` regeneration command, every
existing test) is unaffected. `--schema-version 4` is opt-in on the CLI.
Publishing `graph.v4.json` for real, migrating `apps/web`'s consumers
(`pathfindingGraph.ts`, `graphWorker.ts`'s typed-array transfer, `Connect`,
`Explore`) to decode the dictionary, and the eventual `graph.v3.json`
retirement are separate, later Phase 1 slices — this slice lands and proves
the encoding capability only.

## Revisit trigger

If a future measurement of the actual consuming JavaScript shows the
decode-to-full-strings-on-load approach (the simplest consumption strategy:
resolve every index back to text once, immediately after fetch, so every
existing consumer keeps working against plain strings) costs more parse
time than it saves in transfer time, consider keeping indices live in the
worker instead and threading `roles` through every consumer — a real,
measured tradeoff to make when that Phase 1 slice is implemented, not
guessed at here.
