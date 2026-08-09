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
