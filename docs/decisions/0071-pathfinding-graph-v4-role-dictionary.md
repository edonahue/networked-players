# ADR 0071: Pathfinding graph v4 — role-text dictionary encoding

- **Status:** Accepted and fully rolled out -- every real consumer has cut over and
  `graph.v3.json` has been retired
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

## Addendum (2026-09-03): published dual-live; TS decode strategy chosen

Two follow-on slices resolved the open items above:

1. **Consumption strategy decided:** `apps/web/src/game/pathfindingGraph.ts`'s
   `validatePathfindingGraph` now accepts v4 payloads and decodes the role dictionary
   into plain strings immediately, before returning — `PathfindingGraph.edge_role_a`/
   `edge_role_b` stay `string[]` regardless of schema version, so every existing
   consumer needs zero changes. Chosen over threading indices live through the worker
   specifically because it makes graph.v4 acceptance a validator-only change with no
   consumer risk, mirroring how this file already staged v3 acceptance well before any
   default fetch URL pointed at `graph.v3.json`.
2. **`graph.v4.json` published for real, dual-live.** Registered as its own
   `pathfinding_graph_v4` group in `PUBLIC_ARTIFACT_GROUPS` (validated by `make check`
   independently of `graph.v3.json`, the same mechanism the v2/v3 transition used) —
   real committed file, `pathfinding-graph-v4-20260601-847c1c7dfe02`, 4,848,644 raw
   bytes, matching the earlier measurement exactly (deterministic given the same real
   inputs). No default fetch URL in `apps/web` points at it yet, so it carries zero
   live traffic — the consumer cutover (Connect, Explore, the research workbench, the
   fleet artifact-check default, in that order) remains a separate, later slice.
   Deliberately no dedicated Pi-fleet workload registered for `pathfinding_graph_v4`
   yet (`test_artifact_registration_completeness.py`'s
   `_ARTIFACT_GROUPS_WITHOUT_A_PI_CHECK`) — no real consumer depends on it, so a
   distributed re-check has no independent operational need before the cutover; the
   existing `pathfinding-graph` Pi validator can already check it ad hoc via
   `submit_artifact_check.py`'s `--artifact` override if ever wanted sooner.

The recenter-measurement revisit trigger above is **still open** — it needs the actual
consumer cutover, not just decode-capability + dual-live publication, to produce a
measurement worth re-running ADR 0070's benchmark against.

## Addendum (2026-09-03): every consumer cut over; `graph.v3.json` retired

The remaining two revisit-trigger items above are now resolved:

1. **Consumer cutover, one at a time (PRs #219-#221):** `apps/web`'s `connect.ts` and
   `explorerStage.ts` (Connect Two Records and Network Explorer), then
   `packages/research/src/networked_players_research/route_quality.py`'s
   `load_published_graph` (the private research workbench, given its own schema-version-
   aware decode step it was missing before the flip), then
   `scripts/submit_artifact_check.py`'s fleet artifact-check default -- each its own PR,
   CI-green, live-verified before the next, matching the order this ADR's original
   revisit trigger named.
2. **`graph.v3.json` retired.** `build_pathfinding_graph`'s `schema_version` default
   flipped from 3 to 4; `schema_version=3` remains available on request (never removed --
   the validator-never-narrows precedent applied to the builder too) for reproducing the
   pre-dictionary-encoding shape on demand. The real committed `graph.v3.json` and its
   contract doc (`data/contracts/pathfinding-graph-v3.md`) were deleted; the separate
   `pathfinding_graph_v4` registration group collapsed back into the single
   `pathfinding_graph` group (`PUBLIC_ARTIFACT_GROUPS`, its contracts/CLI/test call
   sites, `docs/OPERATOR_SETUP.md`'s table) -- the same collapse-to-one-group step ADR
   0058 set as precedent for the v1 retirement, and this ADR's own dual-live publication
   used for v2 -> v3. One stale provenance string was found and fixed while checking for
   the same class of defect PR #209 (the v2/v3 retirement) caught: `evidence/
   release-registry.v1.json`'s `source` field still named `pathfinding/graph.v3.json`;
   fixed and the artifact regenerated (the field is excluded from
   `evidence_release_registry_version`'s content hash, so this is a real fix with no
   version change).

The recenter-measurement revisit trigger (re-run ADR 0070's `measureExplorerRecenter`
benchmark against the real cutover, before deciding whether Phase 1's tiles-fallback
trigger fires) remains the one open item, now unblocked -- every consumer is live on
v4, so a real measurement is possible. (Re-run 2026-09-03, ADR 0070's own addendum: real
improvement, budget still marginally open -- see that ADR, not repeated here.)

## Addendum (2026-09-03): `graphWorker.ts` typed-array transfer

The one named-but-deferred item from this ADR's original "scope of this slice" section --
`graphWorker.ts`'s typed-array transfer -- is now done, a separate optimization from the
role dictionary above (that shrank the WIRE payload; this shrinks what the parsed graph
costs to hold and hand across the worker boundary once parsed).

`validatePathfindingGraph`'s final step now converts the four large parallel CSR arrays
(`node_ids`, `offsets`, `neighbors`, `evidence_release_ids` -- previously `number[]`) into
real `Int32Array`s, for every schema version, both the worker path and the main-thread
fallback (one shared conversion, not duplicated). `PathfindingGraph`'s own type reflects
this; every real consumer only ever indexes these arrays (`graph.offsets[i]`), which a
typed array supports identically to a plain array, so no consumer code changed. The one
real internal fix this required: `loadPreparedGraph`'s `nameById` map construction used
`graph.node_ids.map(...)` to build `[id, name]` tuples -- `Int32Array.prototype.map`'s
callback must return a `number` (it produces another `Int32Array`), so this became
`Array.from(graph.node_ids, (id, i) => [id, graph.names[i]])`, which has no such
constraint.

`graphWorker.ts`'s successful responses now pass these four arrays' underlying
`ArrayBuffer`s as `postMessage`'s Transferable list instead of letting the structured-
clone algorithm copy them -- each buffer comes from its own separate `Int32Array.from`
call (no aliasing), and the worker never reuses `graph` after responding, so detaching
these buffers on transfer is safe.

**What was and wasn't independently re-measured:** the existing `reprofile-site.mjs`
heap sample (`jsHeapUsedMb`) is a coarse, whole-page-lifecycle observation (its own
header comment already says so), not an instrument isolating this specific effect, and
`workerParseMs` measures only in-worker parse/hash time, not the `postMessage` transfer
itself -- neither metric moved in a way that confirms or refutes the win here, and
building a precise instrument (e.g. CDP heap profiling, or timing the transfer step in
isolation) was judged a bigger lift than this slice's real scope. The change rests on the
well-established, general JS-engine fact a packed typed array of N integers uses
substantially less heap than a boxed `number[]` of the same length, and that a
`postMessage` Transferable is a zero-copy ownership transfer versus structured-clone's
full copy -- not a bespoke measurement this ADR invented. If this is ever worth
confirming precisely, it needs new instrumentation, not a re-run of the existing script.

Every real consumer (`connect.ts`, `explorerStage.ts`, `networkExplorer.ts`,
`recommendedRoute.ts`) needed zero changes -- confirmed by inspection (only plain indexed
access on these fields anywhere in `apps/web/src`) and by the full existing test suite
(106 targeted unit tests, 85 real-browser Connect/Explore/worker tests including the
actual `postMessage`/transfer path, then the full smoke suite: 520 passed, only the known
pre-existing contributor-page a11y-scan timeout flake). `make check`-equivalent for
`apps/web` (`npm run check`, `npm run format:check`) both green.
