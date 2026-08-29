# Site re-profile method (Phase 7 PR G)

Phase 7's catalog expansion (140 → 179 albums, PR #161) grows every public
artifact and every page the site renders. The Phase 7 plan's PR G asks for a
re-profile against the 140-album baseline: catalog/graph payload sizes,
worker parse time, Connect cold/warm readiness, album-shelf grid render,
Explorer init, `astro build` duration, and mobile CPU/memory at 390px. Real
elapsed-time numbers on this machine are never published here (ADR 0018) —
this document is the reproducible method; real results live in
`local/benchmarks/` (gitignored).

## What has a real 140-album baseline to compare against, and what doesn't

- **`graph.v2.json` payload size** and **sitemap URL counts** have a real
  recorded 140-album figure in the Phase 7 plan doc itself (13.6 MB;
  843 URLs: 140 album / 140 explore / 549 contributor / 14 static). A
  re-profile can genuinely compare before vs. after for these two.
- **Connect Two Records cold-readiness, Explorer init, album-shelf render,
  and mobile CPU/memory** were never benchmarked at 140 albums anywhere in
  this repo. A re-profile run for these establishes a baseline for *future*
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
node scripts/reprofile-site.mjs                  # desktop, unthrottled
node scripts/reprofile-site.mjs --mobile-throttled  # Pixel 5 + 4x CPU throttle
```

**What it measures:**

- **Payload sizes** (raw + gzip): `catalog/albums.v1.json`,
  `challenge.v2.json`, `pathfinding/graph.v2.json`,
  `contributors/index.v1.json`, `evidence/release-registry.v1.json`.
- **Sitemap composition**: total URL count, broken down into album /
  explore / contributor / other, fetched from the live `/sitemap.xml` route
  rather than read off disk, so it reflects exactly what a crawler sees.
- **Connect Two Records cold start**: navigation → page load → the real
  `data-picker-state="ready"` contract both album pickers publish once the
  catalog has loaded (`tests/helpers/connectPicker.ts`'s own readiness
  gate, reused rather than reinvented) → select a real, directly-connected
  pair (Discovery / The Joshua Tree, the same pair
  `tests/game-connect.spec.ts` uses, verified against the real committed
  graph) → click search → `[data-connect-results]` visible.
- **Explorer init**: navigation → page load → first `.explorer-node`
  visible, for a real connected album id resolved from the live
  `challenge.v2.json` fetch (not hardcoded).
- **Album shelf render**: navigation → page load → real `.album-card` count
  on `/albums/` (confirms the full catalog renders, not just a timing
  number).
- **Mobile CPU/memory**: `--mobile-throttled` emulates a Pixel 5 viewport/UA
  and applies a 4x CDP `Emulation.setCPUThrottlingRate` to **every page
  used for a timed measurement** — CDP throttling is per-target, not global
  to a browser context, so a page created after the throttle was set on a
  different, now-closed page is silently unthrottled; the script's `newPage()`
  helper opens a fresh CDP session and sets the rate on each page it hands
  out specifically to avoid that trap. JS heap usage is read via
  `Performance.getMetrics` (after `Performance.enable`, which the CDP
  method requires to return populated metrics) on the album shelf page.

Run each mode 2–3 times; page-load and readiness timings vary run to run by
normal local scheduling noise, but the throttled run should show a
consistent, clearly larger multiple across every metric — if it doesn't,
suspect the per-page throttle wiring, not the site.
