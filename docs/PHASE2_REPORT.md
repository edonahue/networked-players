# Phase 2 report: from static games to an explorable credit network

**Status: complete.** All nine planned slices (A–I) shipped, each as its own
branch/PR, auto-merged once CI (backend `make check` + frontend `npm run
check`/`format:check`/`test:smoke`) was green. This report is the closing
summary the `/goal` mandate asked for: what shipped, what was measured, what
was rejected, and what's left.

## What shipped

| Slice | PR | What it is |
|---|---|---|
| A | [#57](https://github.com/edonahue/networked-players/pull/57) | Homepage/nav repositioning away from "early build" framing; sitemap gap fix (`/play/routes/` was missing) |
| B | [#58](https://github.com/edonahue/networked-players/pull/58) | `role_taxonomy.py` — a third, orthogonal classification layer (11 `RoleCategory` values) alongside the existing traversal-denylist and performer-allowlist, plus a `classify-roles` corpus-coverage diagnostic (ADR 0047) |
| C | [#59](https://github.com/edonahue/networked-players/pull/59) | Contributor index (549 real contributors, built only from already-published artifacts) and `/contributors/[id]/` pages — the album page's "Names only" placeholder became real links (ADR 0048) |
| D | [#60](https://github.com/edonahue/networked-players/pull/60) | Exploration-tier measurement: real candidate counts at 500/1000-album scale, a policy for growing past 140 albums, a new `exploration_corpus_version` namespace (ADR 0049) |
| E | [#61](https://github.com/edonahue/networked-players/pull/61) | Real browser/payload benchmark deciding the pathfinding architecture: browser-local CSR viable at bounded (140-catalog) scope; parallel-array serialization measured ~15x smaller gzip than array-of-objects (ADR 0050) |
| F | [#62](https://github.com/edonahue/networked-players/pull/62) | Connect Two Records — the first search UI: pick any two albums, get a documented route with evidence and a transparent "more musical route" re-ranking (ADR 0051) |
| G | [#63](https://github.com/edonahue/networked-players/pull/63) | Network Explorer — a bounded (≤24-neighbor), SVG, click-to-recenter graph view at `/explore/[album]/` (ADR 0052) |
| H | [#64](https://github.com/edonahue/networked-players/pull/64) | Behind the Glass — a measured-first role-aware mode (producer/engineer-only pathfinding), shipped as a toggle on Connect Two Records rather than a new mode/page (ADR 0053) |
| I | [#65](https://github.com/edonahue/networked-players/pull/65) | Daily archive/calendar at `/play/daily/archive/`; `store.ts` v1→v2 migration adding per-date rating alongside the share string |

Net diff from the pre-Phase-2 baseline (`09bfa7b`) to the tip of Slice I:
**72 files changed, ~338K insertions** (dominated by the real 60,696-edge
pathfinding graph artifact and the 549-contributor index — both real,
generated data, not placeholders). Seven new ADRs (0047–0053).

## What was measured before being built

Per the plan's "prototype → benchmark → decide → document → productionize"
discipline, three decisions were made from real numbers, not guesses:

- **Slice E** (browser pathfinding): measured real payload sizes for three
  candidate architectures at the 140-album scope before choosing browser-
  local CSR. The parallel-array vs. array-of-objects serialization choice in
  Slice F was itself a measured correction mid-slice (~15x gzip difference,
  documented in ADR 0050's addendum).
- **Slice D** (exploration tiers): measured that a naive 1000-candidate
  ranking limit undershoots a 500-album target (373 achieved) while a
  3000-candidate limit hits both 500 and 1000 exactly — a real, checked-in
  table (`docs/EXPLORATION_TIER_COMPARISON.md`), not an estimate.
- **Slice H** (role-aware mode): measured one-hop/two-hop candidate counts
  for three candidate modes (Behind the Glass, Rhythm Section, Guitar Paths)
  against the real 140-album catalog *before* building any of them. All
  three cleared ADR 0043's launch floor (≥50 one-hop/≥20 two-hop) by a wide
  margin — Behind the Glass won on coverage (202/429 pairs, 137/140 albums)
  and was shipped; the other two are documented as viable future toggles
  with their measured counts already on record (170/455 for Rhythm Section,
  109/196 for Guitar Paths), so a future slice doesn't have to re-measure.

Real hardware/timing numbers from these benchmarks were kept in
`local/benchmarks/`/`local/analysis/` (gitignored) per ADR 0018 — only
methodology and catalog-quality facts are public.

## Rejected or descoped approaches

- **A second round-based game mode for Behind the Glass** (forking or
  parameterizing `connection_rounds.py`, the flagship's most-trafficked,
  most-tested module) was rejected in favor of a toggle on the existing
  Connect Two Records page — lower risk, no new public artifact, and a more
  direct fit for what the mode actually is (a role-filtered path search).
- **Canvas rendering for the Network Explorer** was rejected in ADR 0052:
  bounded node counts (≤24) make Canvas's scale advantage moot, and SVG
  gives real, focusable, `aria`-labeled DOM elements instead of a second
  accessibility problem.
- **A DuckDB-WASM or server-side-Worker pathfinding backend** were both
  considered in Slice E's rubric and rejected in favor of browser-local CSR
  — the former's runtime payload was disproportionate to the bounded
  scope, the latter risked violating static-first delivery.
- **Committing to a specific future album-tier count** (500/1000) was
  deliberately deferred — Slice D produced a measured comparison and a
  policy, not a commitment, consistent with the plan's own tripwire against
  pre-announcing a number before Slice E's feasibility check.

## Tests run

- Backend: `make check` (Ruff lint/format, mypy, pytest, both artifact-gate
  validators) — green at every slice merge; 867 backend tests at the final
  count, including full parity/coverage suites for `role_taxonomy.py`,
  `contributor_index.py`, `pathfinding_graph.py`, `role_mode_candidates.py`,
  and `eligibility_engineering.py`.
- Frontend: `npm run check` (Astro typecheck/build/`validate:data`) and
  `npm run format:check` — 0 errors/0 warnings at every slice.
- Playwright (`npm run test:smoke`): 213 tests at the final count, including
  real-artifact-verified cases (not just fixtures) — e.g. Discovery↔Joshua
  Tree and Ziggy Stardust↔A Night at the Opera as real, artifact-confirmed
  Connect Two Records pairs; Elvis Presley (1,695 real neighbors) to exercise
  Network Explorer's truncation; a real played daily date and a real future
  scheduled date for the new archive page.

## Not exercised (explicitly out of scope, consistent with the plan)

- Real Pi-fleet dispatch of any new artifact's validator (issue #53's fleet
  gaps predate this plan and remain open).
- A manual accessibility pass (also issue #53).
- `diff-artifact-version` tooling for the publication train's "semantic
  diff" stage — still a manual byte-for-byte diff against the prior
  publish, as documented in `docs/PHASE2_PLAN.md`'s spine table.
- A cross-language BFS parity test between `compact_graph_bench.py` and
  `pathfindingGraph.ts` — both ADR 0050 and ADR 0051 flag this as a real,
  open gap, revisit-triggered by any future BFS bug found in only one
  implementation.

## Remaining risks / highest-leverage next work

1. **BFS parity gap** (above) — low current risk (both implementations are
   independently tested against the same fixture shapes) but a real latent
   inconsistency risk if either is modified without the other.
2. **Fleet canary dispatch** (issue #53) — every new artifact type added in
   Phase 2 (contributor index, pathfinding graph) has never been validated
   through the real Pi fleet pipeline, only locally and in CI.
3. **Exploration tier growth** — Slice D's policy and Slice H's extra
   measured candidates (Rhythm Section, Guitar Paths) are ready to build on
   whenever a larger album tier ships; that's the natural next expansion
   rather than new architecture work.
4. **Accessibility pass** — deferred consistently across G and prior slices;
   now touches more surface area (Network Explorer, contributor pages,
   Connect Two Records) than before Phase 2, raising the value of doing it.
