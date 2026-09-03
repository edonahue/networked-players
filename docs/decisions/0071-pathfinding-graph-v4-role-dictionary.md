# ADR 0071: Pathfinding graph v4 — role-text dictionary encoding

- **Status:** Accepted (encoding capability); publication and consumer migration deferred
- **Extends:** [ADR 0050](0050-browser-pathfinding-architecture-selection.md),
  [ADR 0051](0051-connect-two-records.md),
  [ADR 0058](0058-album-credit-membership-and-evidence-registry.md) (v2 virtual anchors),
  [ADR 0068](0068-performer-only-public-graph.md) (v3 performer gate) without modifying any
  of them
- **Relates to:** [ADR 0069](0069-public-universe-model-and-expansion-policy.md) (the same
  opt-in, code-lands-before-artifact-regenerates sequencing), [ADR 0070](0070-community-detection-and-explore-scaling-measurement.md)
  (the recenter-cost finding this encoding change is measured against next)

## Context

Graph-expansion Phase 1 (`docs/GRAPH_EXPANSION_DIRECTION.md`, plan §6) identified
`pathfinding/graph.v3.json`'s `edge_role_a`/`edge_role_b` — the per-slot role text,
inline and repeated at every slot — as the single largest structural inefficiency in
the artifact: a real measurement found these two fields are roughly 68% of the raw
payload's bytes, over only ~11.8K distinct strings spread across ~76.6K directed slots.
This is exactly the shape a dictionary encoding fixes, with zero semantic change.

Slice 0-C (ADR 0070) separately measured that Explore's recenter cost is *already* at
or above Phase 1's own budget at 179 albums, in every profile tested — raising the
stakes on this encoding change: it needs to measurably help, not just avoid making
things worse, before graph-expansion growth makes the payload larger still.

## Decision

`build_pathfinding_graph` (`packages/graph-core/.../pathfinding_graph.py`) gains an
opt-in `schema_version` parameter (default `3`, today's published shape). When called
with `schema_version=4`:

- A new `roles: list[str]` array collects every distinct role-text string that would
  otherwise appear inline, in first-seen order, no duplicates.
- `edge_role_a`/`edge_role_b` become `list[int]` — indices into `roles` — instead of
  the text itself. Everything else (node ids, names, offsets, neighbors,
  `evidence_release_ids`, `album_virtual_nodes`, `graph_policy_version`) is
  byte-for-byte identical to a v3 build from the same inputs.
- `pathfinding_graph_version` additionally hashes `roles` for v4, so a role-set change
  (e.g. `eligibility.py`'s token set changing) is never silently invisible to the
  content hash.

`networked_players_contracts.pathfinding_graph::pathfinding_graph_failures` (the
pure-Python, Pi-fleet-safe validator) accepts v4 payloads: `roles` must be an array of
strings; `edge_role_a`/`edge_role_b` must be arrays of valid indices into it (not
strings, as v1-3 require — a v3 payload mis-stamped `schema_version: 4` fails this
check rather than silently validating); the album-anchor sentinel-placement check
resolves each slot's index through `roles` before comparing, so a misplaced sentinel is
still caught exactly as in v1-3.

**Real measured effect** (same real committed catalog and one-hop corpus `graph.v3.json`
already uses — identical 20,845 nodes, 38,323 undirected edges, 179 anchors, byte-for-byte
identical edge set): raw JSON **−41.5%** (8,292,647 → 4,848,644 bytes), gzip **−24.0%**
(1,317,241 → 1,001,541 bytes). Full detail in `data/contracts/pathfinding-graph-v4.md`.
The gzip win is smaller than raw's because gzip was already partially capturing the
repetition the dictionary removes outright — real, expected, not a discrepancy to
explain away.

**Scope of this slice, deliberately narrow.** This lands the encoding capability and
its validators only:

- `build-pathfinding-graph --schema-version 4` is wired end-to-end and tested, but the
  real committed `graph.v3.json` is untouched — no `graph.v4.json` is published here.
- `apps/web` is **not** touched in this slice. `pathfindingGraph.ts` still only ever
  parses v1-3 shape; `graphWorker.ts`'s typed-array transfer, `explorerStage.ts`'s
  consumption, and every other real consumer migration is separate, later Phase 1 work.
  This mirrors the exact same reason ADR 0069 (catalog schema v2) deferred its own
  artifact regeneration: coordinating a wire-format change with its consumer's code
  change in one PR is a larger, riskier diff than landing the capability first and the
  cutover second, and the real precedent for this exact artifact (v2 → v3) was ALSO a
  dual-live, staged migration, not a single big-bang PR.

## Consequences

- No product code changes. No real public artifact changes shape. `validate-public-
  artifacts` passes unchanged against the real committed `graph.v3.json`.
- The real 41.5%/24.0% size win is now measured, not projected — Phase 1's next slice
  (publish `graph.v4.json` for real, migrate consumers) can budget against real numbers
  instead of the plan's earlier estimate.
- ADR 0070's revisit trigger ("re-run the recenter measurement after graph.v4 lands,
  before deciding whether the tiles-fallback trigger fires") is **not yet satisfied** by
  this ADR alone — that requires the actual consumer migration (a worker that decodes or
  threads the dictionary) to exist, so its real effect on recenter cost can be measured.
  This ADR is a prerequisite for that measurement, not the measurement itself.

## Validation

`packages/contracts/tests/test_pathfinding_graph_contracts.py`: 10 new tests (clean v4
payload; version-prefix; missing `roles` key rejected; a v3 payload mis-stamped
`schema_version: 4` rejected via the index-vs-string check; out-of-range and negative
role indices rejected; non-string `roles` entries rejected; sentinel placement still
caught through the dictionary; v3 album-virtual-node checks still apply; v3/v4
dual-live coexistence). `packages/graph-core/tests/test_pathfinding_graph.py`: 3 new
tests (default stays v3-shaped; v4's `roles[edge_role_a[slot]]` recovers the exact v3
text for every slot, with every other field byte-for-byte identical between a v3 and a
v4 build of the same inputs; an unsupported schema_version raises). CLI wiring test:
`--schema-version 4` end-to-end through `build-pathfinding-graph` then
`validate-pathfinding-graph`. `make check` (1,507 pytest, ruff, mypy,
`validate-public-artifacts`, `validate-album-catalog-audit`) all green.

## Revisit trigger

- Publish `graph.v4.json` for real and migrate `apps/web`'s consumers only after
  deciding the consumption strategy (decode-to-strings-once-on-load vs. threading
  indices live through the worker) — see the open question in
  `data/contracts/pathfinding-graph-v4.md`'s own revisit trigger.
- Re-run ADR 0070's `measureExplorerRecenter` benchmark immediately once that
  consumer migration lands, before deciding whether Phase 1's tiles-fallback trigger
  fires.
- Retire `graph.v3.json` only after every real consumer (Connect, Explore, the private
  research workbench, the fleet artifact-check default) has cut over to v4 — the same
  explicit, separate retirement step ADR 0058 set as precedent for v1 → v2.
