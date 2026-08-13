# Pathfinding graph fixtures

Shared, cross-language test fixtures for the pathfinding graph contract
(`data/contracts/pathfinding-graph-v1.md` / `pathfinding-graph-v2.md`).
Loaded by both:

- `packages/contracts/tests/test_pathfinding_graph_contracts.py`
  (`pathfinding_graph_failures`)
- `apps/web/tests/pathfinding-bfs.spec.ts` / `pathfinding-bfs-v2.spec.ts`
  (`validatePathfindingGraph`)

so a new malformed case added here is automatically exercised against both
validators, closing the parity-drift risk ADR 0051's revisit trigger names
("no shared cross-language parity harness yet").

- `catalog.json` -- the small synthetic catalog every graph fixture here
  claims to belong to (its `catalog_version` matches). Only the Python
  suite uses this (the browser validator has no catalog cross-check).
- `well-formed-v1.json` / `well-formed-v2.json` -- internally consistent,
  real content-hashed `pathfinding_graph_version`. Must pass both
  validators with zero failures.
- `malformed-*.json` -- each file is well-formed except for exactly one
  violated invariant, and (except `malformed-tampered-hash.json`, whose
  whole point is a stale hash) has its `pathfinding_graph_version`
  recomputed over the corrupted content, so the fixture isolates that one
  invariant rather than also tripping the hash check.

This is a genuinely new fixture-sharing convention for this repo (see ADR
0051's addendum) -- kept deliberately small and single-purpose, not a
general "shared test fixtures" framework.

## Parity matrix

Every fixture below is loaded by both a Python test in
`test_pathfinding_graph_contracts.py` and a TypeScript test in
`pathfinding-bfs.spec.ts`/`pathfinding-bfs-v2.spec.ts`, asserting the same
outcome -- proof both validators agree on internal-structure invariants,
not just a claim. "Catalog-dependent" marks the one intentional asymmetry:
Python receives the real catalog and can cross-check against it; the
browser validator never has the catalog loaded alongside the graph, so it
only proves internal self-consistency (documented in both validators' own
docstrings, and in `pathfinding_graph.py`/`pathfindingGraph.ts` directly).

| Fixture | Invariant | Python | TypeScript | Catalog-dependent |
| --- | --- | --- | --- | --- |
| `well-formed-v1.json` | baseline | accept | accept | -- |
| `well-formed-v2.json` | baseline | accept | accept | -- |
| `malformed-non-monotonic-offsets.json` | offsets must be non-decreasing | reject | reject | no |
| `malformed-unsorted-node-ids.json` | node_ids must be sorted | reject | reject | no |
| `malformed-duplicate-node-ids.json` | node_ids must be unique | reject | reject | no |
| `malformed-tampered-hash.json` | version must match recomputed content hash | reject | reject | no |
| `malformed-wrong-top-level-keys.json` | exact top-level key set | reject | reject | no |
| `malformed-misplaced-sentinel.json` | album-anchor sentinel only on the virtual side | reject | reject | no |
| `malformed-empty-metadata.json` | `generated_at`/`source`/`license`/etc. non-empty | reject | reject | no |
| `malformed-virtual-node-missing-key.json` | exact key set per `album_virtual_nodes` entry | reject | reject | no |
| `malformed-virtual-node-extra-key.json` | exact key set per `album_virtual_nodes` entry | reject | reject | no |
| `malformed-fractional-offset.json` | offsets are integers | reject | reject | no |
| `malformed-fractional-neighbor.json` | neighbor indices are integers | reject | reject | no |
| `malformed-fractional-main-release-id.json` | `main_release_id` is an integer | reject | reject | no |
| `malformed-node-id-wrong-type.json` | node_ids are integers | reject | reject | no |

Python-only, not JSON-representable or not meaningfully shareable, so they
live as inline-built payloads directly in `test_pathfinding_graph_contracts.py`
rather than as fixture files here:
- a boolean `neighbors` element (`bool` is a subtype of `int` in Python and
  needs its own exclusion; TypeScript's `typeof` already excludes booleans,
  so there is nothing to test on that side)
- an unhashable `node_ids` element (proves no uncaught exception, not
  achievable as a JSON value distinct from the wrong-type case above)

TypeScript-only, since JSON has no literal for either value:
- `Infinity`/`NaN` totality tests in `pathfinding-bfs-v2.spec.ts`, proving
  `validatePathfindingGraph` returns `null` rather than throwing

Genuinely catalog-dependent checks (Python only, no TypeScript equivalent
by design, not tested via a shared fixture since the browser validator has
no catalog to check against): `catalog_version` matching the canonical
catalog, and each `album_virtual_nodes[i].album_id` resolving into it.
