# Site re-profile method (Phase 7 PR G; extended graph-expansion Phase 0 slice 0-C)

Phase 7's catalog expansion (140 → 179 albums, PR #161) grows every public
artifact and every page the site renders. The Phase 7 plan's PR G asks for a
re-profile against the 140-album baseline: catalog/graph payload sizes,
worker parse time, Connect cold/warm readiness, album-shelf grid render,
Explorer init, `astro build` duration, and mobile CPU/memory at 390px. Real
elapsed-time numbers on this machine are never published here (ADR 0018) —
this document is the reproducible method; real results live in
`local/benchmarks/` (gitignored).

The graph-expansion plan's Phase 0 slice 0-C (`docs/GRAPH_EXPANSION_DIRECTION.md`)
extends this method with two additions the plan's own §6 Explore-scaling
benchmark asks for: **Explorer recenter timing** and a **third, distinct
CPU-throttled profile** — see "What it measures" and "Profiles" below. Both
are exercised against the artifact names current since ADR 0068's
performer-only cutover (`challenge.v3.json`, `pathfinding/graph.v3.json`);
earlier revisions of this document referenced the retired `.v2.json` names.

## What has a real 140-album baseline to compare against, and what doesn't

- **`graph.v2.json` payload size** and **sitemap URL counts** have a real
  recorded 140-album figure in the Phase 7 plan doc itself (13.6 MB;
  843 URLs: 140 album / 140 explore / 549 contributor / 14 static). A
  re-profile can genuinely compare before vs. after for these two.
- **Connect Two Records cold-readiness, Explorer init, album-shelf render,
  and mobile CPU/memory** were never benchmarked at 140 albums anywhere in
  this repo. A re-profile run for these establishes a baseline for _future_
  re-profiles to diff against — report them as observed now, never implied
  as a before/after, per AGENTS.md's "identify whether a sizing claim is
  observed, sourced, projected, or measured" rule.
- **`astro build` duration** has no historical baseline (only a projected
  route count, "843 → ~1,000+"); report the observed duration and route
  count now, and note the projection's outcome.

## The script

`apps/web/scripts/reprofile-site.mjs` — a standalone Playwright-driven Node
script (not a `tests/*.spec.ts` file, so it never runs as part of `npm run
test:smoke` or CI; this is a benchmark probe, not a correctness test, same
distinction `local/experiments/graph-benchmark/` draws for the Phase 2
architecture-selection benchmark).

```bash
cd apps/web
npm run build
npm run preview -- --host 127.0.0.1 --port 4321 &
node scripts/reprofile-site.mjs                     # desktop, unthrottled
node scripts/reprofile-site.mjs --desktop-throttled  # desktop viewport, 4x CPU throttle
node scripts/reprofile-site.mjs --mobile-throttled   # Pixel 5 viewport, 4x CPU throttle
```

**Profiles** (graph-expansion plan §6 asks for exactly these three): desktop
unthrottled is the floor; `--desktop-throttled` isolates pure CPU cost
(same viewport, no device/touch/UA emulation) from `--mobile-throttled`'s
combined CPU-throttle-plus-mobile-viewport effect. Run each mode 2-3 times
per the existing guidance below — the two throttled modes are NOT simply
"slower" versions of the unthrottled run in every metric (a smaller
viewport can render fewer visible Explorer nodes per recenter, for
instance), so read all three as their own real data points, not a single
scaling factor.

**What it measures:**

- **Payload sizes** (raw + gzip): `catalog/albums.v1.json`,
  `challenge.v3.json`, `pathfinding/graph.v4.json` (ADR 0071's
  role-dictionary encoding; the only published pathfinding graph as of
  `graph.v3.json`'s retirement -- every real consumer cut over across
  PRs #219-#221), `contributors/index.v1.json`,
  `evidence/release-registry.v1.json`.
- **Sitemap composition**: total URL count, broken down into album /
  explore / contributor / other, fetched from the live `/sitemap.xml` route
  rather than read off disk, so it reflects exactly what a crawler sees.
- **Connect Two Records cold + warm readiness**: navigation → page load →
  the real `data-picker-state="ready"` contract both album pickers publish
  once the catalog has loaded (`tests/helpers/connectPicker.ts`'s own
  readiness gate, reused rather than reinvented) → select a real,
  directly-connected pair (Discovery / The Joshua Tree, the same pair
  `tests/game-connect.spec.ts` uses, verified against the real committed
  graph) → click search → `[data-connect-results]` visible: that's the cold
  number. The same still-open page (catalog, graph, and worker already
  warm) then runs a **second** search against a different real path pulled
  from the live `challenge.v3.json` (skipping any path sharing an endpoint
  with the cold pair) — that search-to-results time is the warm number.
  `warm.searchToResultsMs` is `null` only if the committed catalog has no
  second path with distinct endpoints, a valid if unlikely state.
- **Worker parse time** (Phase 7 closeout PR E): `graphWorker.ts` now
  measures its own parse+canonicalize+hash cost (the
  `validatePathfindingGraph` integrity check) with `performance.now()`,
  wrapped around the exact span the ADR 0059 Phase 5c comment names,
  excluding fetch/network time, and posts it back as `parseMs`.
  `pathfindingGraph.ts`'s main-thread fallback path (used when a Worker
  can't be constructed) measures the identical span. Either path writes
  the result to a page-scoped diagnostic global,
  `window.__NP_GRAPH_PARSE_MS__` (`pathfindingGraph.ts`'s own
  `recordGraphParseMs`) — undocumented/unlisted like a private field, but
  not gated behind a test-only flag the way `dateOverride.ts`'s override
  is, since a wall-clock number carries no privacy or security weight.
  `measureExplorerInit` reads it via `page.evaluate` right after the first
  node renders and reports it as `explorer.workerParseMs`; `null` there
  now means the graph load genuinely never completed, not "never
  measured."
- **Explorer init**: navigation → page load → first `.explorer-node`
  visible, for a real connected album id resolved from the live
  `challenge.v3.json` fetch (not hardcoded).
- **Explorer recenter** (graph-expansion Phase 0 slice 0-C, plan §6):
  measured on the SAME still-open page right after init (graph/worker
  already warm, no repeated page-load cost) — click the first non-center
  neighbor node → wait for `centerOn()`'s own real completion signal
  (`explorerStage.ts` stamps `data-is-center="true"` onto the newly-
  centered node) → record elapsed. Repeated `REPROFILE_RECENTER_ITERATIONS`
  times (default 50), reported as p50/p95/max. Deliberately walks the
  FIRST rendered non-center neighbor each time, not the plan's originally-
  stated "10 highest-degree nodes" — no degree ranking is available
  client-side without extra plumbing this slice doesn't add; note this
  simplification wherever the numbers are read. Returns `incomplete: true`
  with a real `iterationsRun` count rather than padding, if the graph ever
  runs out of a non-center neighbor before the target iteration count.
  **Not measured**: long-task count / frame time over a scripted pan/zoom
  drag (the plan's other §6 metric) -- Explore has no pan/zoom interaction
  to script yet (ADR 0052 still holds: bounded ego view, recenter as the
  primary interaction; pan/zoom is Phase 1 work). Add that measurement once
  Phase 1 ships the interaction it would measure, not before.
- **Album shelf render**: navigation → page load → real `.album-card` count
  on `/albums/` (confirms the full catalog renders, not just a timing
  number).
- **Mobile CPU/memory**: `--mobile-throttled` emulates a Pixel 5 UA/touch/
  device-scale profile, with its viewport explicitly overridden to this
  repo's own established 390×844 mobile-testing viewport
  (`apps/web/tests/smoke.spec.ts`'s "mobile layout" describe block) instead
  of the device descriptor's own default (393×727 on this repo's pinned
  Playwright version -- device descriptors vary across Playwright
  releases, so this is measured against the committed version, not
  assumed), so a re-profile's mobile
  numbers are comparable to every other mobile assertion in this codebase.
  A 4x CDP `Emulation.setCPUThrottlingRate` is applied to **every page used
  for a timed measurement** — CDP throttling is per-target, not global to a
  browser context, so a page created after the throttle was set on a
  different, now-closed page is silently unthrottled; the script's
  `newPage()` helper opens a fresh CDP session and sets the rate on each
  page it hands out specifically to avoid that trap. JS heap usage is read
  via `Performance.getMetrics` (after `Performance.enable`, which the CDP
  method requires to return populated metrics) after each of the run's
  timed pages (both Connect searches, Explorer init, album shelf); the
  output reports every sample plus their max as `maxObservedMb` — an honest
  "highest point this script happened to sample," not a true continuous
  peak (which would need CDP heap profiling, a bigger lift not yet
  justified).

Run each mode 2–3 times; page-load and readiness timings vary run to run by
normal local scheduling noise, but the throttled run should show a
consistent, clearly larger multiple across every metric — if it doesn't,
suspect the per-page throttle wiring, not the site.

## Private workbench cache measurement (Phase 7 closeout PR B)

A different tool from everything above — `apps/review`'s local workbench,
never public, never deployed — but the same ADR 0018 discipline applies: the
method is documented here, real numbers stay in a local, gitignored file
(this repo's convention: `local/tmp/`), never committed or printed in a PR
description.

**What's measured**: `WorkbenchGraphCache.checkout()` and
`ScopeTierCache.get_or_compute()` (`apps/review/review_server.py`) — before
PR B, every `/api/compare` request rebuilt the full `CreditGraph` (including
`credit_edges` materialization) from scratch, and every artist-evidence
click recomputed `measure_scope_tiers` from scratch, with no reuse across
requests at all.

**Method**: exercise both cache classes directly (no HTTP layer, no
`ThreadingHTTPServer` — that layer adds its own noise this measurement isn't
about), against a real local topic corpus (not a synthetic fixture — cache
behavior at real corpus scale is the whole point). `cold` is the first
checkout/compute against an empty cache; `warm` is a second checkout/compute
against the *same* corpus root immediately after, still in-process. Record:
corpus identity (root path, real size), the real artist_id used for the
scope-tier measurement, and both cold/warm elapsed times, computed as a
simple wall-clock delta around the call — no need for anything more precise
than that at this granularity (sub-second to low-single-digit-second spans).

**A real corpus-scale caveat, worth stating explicitly every time this is
re-run**: a small topic corpus (a few MB) has a cold cost of well under two
seconds, nowhere near `CreditGraph.open`'s own documented ~2.5-minute figure
for the FULL one-hop dataset — that full-scale number is what the cache
exists to avoid paying repeatedly, so a small-topic-corpus measurement
under-represents the real-world benefit at production scale. State the
corpus size alongside any measured number, and never imply a small-corpus
timing generalizes to the full corpus without saying so.
