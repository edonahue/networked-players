#!/usr/bin/env node
// Site re-profile method (Phase 7 PR G, "re-profile against the 140-album
// baseline"). Real, reproducible measurements against a locally-served
// production build. Per ADR 0018, the numbers this script prints are NEVER
// committed to the repo -- only this method is public; results belong in
// `local/benchmarks/` (gitignored).
//
// Usage (from apps/web/):
//   npm run build && npm run preview -- --host 127.0.0.1 --port 4321 &
//   node scripts/reprofile-site.mjs                    # desktop, unthrottled
//   node scripts/reprofile-site.mjs --desktop-throttled # desktop viewport, 4x CPU
//   node scripts/reprofile-site.mjs --mobile-throttled  # Pixel 5 viewport, 4x CPU
//
// What's compared against a real prior baseline, and what's a new one:
// - graph.v3.json payload size and sitemap URL counts have a real recorded
//   140-album figure in the Phase 7 plan doc's section 10 (13.6 MB,
//   843 URLs: 140 album/140 explore/549 contributor/14 static) -- this
//   script's own output should be read alongside those, not instead of.
// - Connect Two Records cold-readiness, Explorer init, album-shelf render,
//   and mobile CPU/memory were never benchmarked at 140 albums anywhere in
//   this repo. This run establishes a baseline for FUTURE re-profiles to
//   diff against, not a before/after for these specific numbers -- report
//   them as "observed now," never implied as a comparison.
//
// Explorer RECENTER timing (graph-expansion Phase 0 slice 0-C, plan section
// 6's benchmark method): added alongside Explorer INIT above -- recentering
// (click a neighbor node -> `centerOn()` rebuilds the SVG) is the ring's
// primary interaction (ADR 0052) and the thing Phase 1's tiles-vs-single-file
// decision is actually gated on. Measured via the real `data-is-center`
// attribute `centerOn()` already stamps onto the newly-centered node
// (`explorerStage.ts`), not a timeout guess. Each iteration recenters onto
// the FIRST non-center neighbor currently rendered -- a simple, deterministic
// walk, not the plan's originally-stated "10 highest-degree nodes" (no
// degree data is available client-side without extra plumbing this slice
// doesn't add); note this simplification wherever the numbers are read.
// Deliberately NOT measured here: long-task count / frame time over a
// scripted pan/zoom drag -- Explore has no pan/zoom interaction to script
// yet (ADR 0052 still holds: bounded ego view, recenter-as-primary,
// zoom/pan is Phase 1 work per the graph-expansion plan). Add that
// measurement once Phase 1 ships the interaction to measure, not before.

import { chromium, devices } from "@playwright/test";
import { readFileSync, statSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { fileURLToPath } from "node:url";
import path from "node:path";

const BASE_URL = process.env.REPROFILE_BASE_URL ?? "http://127.0.0.1:4321";
const MOBILE_THROTTLED = process.argv.includes("--mobile-throttled");
const DESKTOP_THROTTLED = process.argv.includes("--desktop-throttled");
const THROTTLED = MOBILE_THROTTLED || DESKTOP_THROTTLED;
const RECENTER_ITERATIONS = Number(
  process.env.REPROFILE_RECENTER_ITERATIONS ?? 50,
);
const ROOT = path.resolve(fileURLToPath(new URL("..", import.meta.url)));

function payloadSize(relPath) {
  const abs = path.join(ROOT, "public", relPath);
  const raw = statSync(abs).size;
  const gzip = gzipSync(readFileSync(abs)).length;
  return { path: relPath, rawBytes: raw, gzipBytes: gzip };
}

function measurePayloads() {
  return [
    "data/catalog/albums.v1.json",
    "data/challenge.v3.json",
    // v4 (graph-expansion Phase 1, ADR 0071): the only published pathfinding
    // graph as of the retirement of graph.v3.json -- every real consumer
    // (Connect, Explore, the private research workbench, the fleet
    // artifact-check default) cut over across PRs #219-#221.
    "data/pathfinding/graph.v4.json",
    "data/contributors/index.v1.json",
    "data/evidence/release-registry.v1.json",
  ].map(payloadSize);
}

function isLeaf(url, section) {
  return (
    url.includes(`/${section}/`) &&
    url.replace(/\/$/, "").split("/").pop() !== section
  );
}

async function measureSitemap(page) {
  const res = await page.request.get(`${BASE_URL}/sitemap.xml`);
  const body = await res.text();
  const locs = [...body.matchAll(/<loc>(https:\/\/[^<]+)<\/loc>/g)].map(
    (m) => m[1],
  );
  const albumPages = locs.filter((l) => isLeaf(l, "albums")).length;
  const explorePages = locs.filter((l) => isLeaf(l, "explore")).length;
  const contributorPages = locs.filter((l) => isLeaf(l, "contributors")).length;
  return {
    total: locs.length,
    albumPages,
    explorePages,
    contributorPages,
    otherPages: locs.length - albumPages - explorePages - contributorPages,
  };
}

// CDP's Emulation.setCPUThrottlingRate is per-target (per-page CDP
// session), not global to a browser context -- setting it on one page and
// then opening a NEW page for each measurement (as an earlier version of
// this script did) silently leaves every subsequent page unthrottled.
// Every page used for a timed measurement must have the rate set on its
// own session, before navigation.
async function newPage(context) {
  const page = await context.newPage();
  if (THROTTLED) {
    const client = await context.newCDPSession(page);
    await client.send("Emulation.setCPUThrottlingRate", { rate: 4 });
  }
  return page;
}

async function selectAndSearch(page, fromTitle, toTitle) {
  await page.locator('[data-picker="a"] input').fill(fromTitle);
  await page
    .locator('[data-picker="a"] [data-picker-results] [role="option"]')
    .first()
    .click();
  await page.locator('[data-picker="b"] input').fill(toTitle);
  await page
    .locator('[data-picker="b"] [data-picker-results] [role="option"]')
    .first()
    .click();

  const searchClickedAt = Date.now();
  await page.locator("[data-connect-search]").click();
  await page
    .locator("[data-connect-results]")
    .waitFor({ state: "visible", timeout: 15_000 });
  return Date.now() - searchClickedAt;
}

// The cold-start pair: the first real, directly-connected pair in
// `challenge.paths`, resolved to titles -- not a hardcoded literal (an
// earlier version hardcoded "Discovery"/"The Joshua Tree", the real
// 179-album catalog's own diagnostic pair, which made this script unusable
// against any other catalog, including the graph-expansion plan's own
// local 500-tier benchmark fixture (plan section 6): pointing this script
// at a different `challenge.v3.json` -- and therefore a different `graph.v4.json`
// via the same swapped `apps/web/public/data/` tree -- now genuinely works
// against ANY committed or local catalog, not just the one this script was
// originally written against.
function pickColdPair(challenge) {
  const albumsById = new Map(challenge.albums.map((a) => [a.id, a]));
  const path = challenge.paths[0];
  if (!path) return null;
  const from = albumsById.get(path.from_album_id);
  const to = albumsById.get(path.to_album_id);
  if (!from || !to) return null;
  return { fromTitle: from.title, toTitle: to.title };
}

// A second, real, directly-connected pair distinct from the cold-start
// pair below -- reusing that same pair for the "warm" search would make it
// indistinguishable from "the same search, run twice" rather than a
// genuine warm-cache search. Picked from `challenge.paths` (the same
// artifact the cold-start pair is verified against elsewhere), skipping
// any path that happens to share an endpoint with the cold pair.
function pickWarmPair(challenge, excludeTitles) {
  const albumsById = new Map(challenge.albums.map((a) => [a.id, a]));
  for (const path of challenge.paths) {
    const from = albumsById.get(path.from_album_id);
    const to = albumsById.get(path.to_album_id);
    if (!from || !to) continue;
    if (excludeTitles.has(from.title) || excludeTitles.has(to.title)) {
      continue;
    }
    return { fromTitle: from.title, toTitle: to.title };
  }
  return null;
}

// Cold: navigation -> page load -> picker ready -> first search. Warm: a
// SECOND, different search on the SAME still-open page/worker/catalog --
// the method doc promises "Connect cold/warm readiness," but until this
// fix the script only ever measured one cold search and called the
// missing second number "warm" by omission. `null` warm timings mean the
// committed catalog had no second path with distinct endpoints to search
// (a valid, if unlikely, state -- not a script failure).
async function measureConnectReadiness(context, challenge, heapSamples) {
  const page = await newPage(context);
  const navStart = Date.now();
  await page.goto(`${BASE_URL}/play/connect/`, { waitUntil: "load" });
  const pageLoadMs = Date.now() - navStart;

  await page.waitForSelector('[data-picker="a"][data-picker-state="ready"]');
  const pickerReadyMs = Date.now() - navStart;

  const coldPair = pickColdPair(challenge);
  if (!coldPair) {
    throw new Error(
      "challenge.v3.json has no paths at all -- cannot measure Connect readiness",
    );
  }
  const coldSearchToResultsMs = await selectAndSearch(
    page,
    coldPair.fromTitle,
    coldPair.toTitle,
  );
  const resultsVisibleMs = Date.now() - navStart;
  heapSamples.push(await measureMemory(page));

  const warmPair = pickWarmPair(
    challenge,
    new Set([coldPair.fromTitle, coldPair.toTitle]),
  );
  const warmSearchToResultsMs = warmPair
    ? await selectAndSearch(page, warmPair.fromTitle, warmPair.toTitle)
    : null;
  heapSamples.push(await measureMemory(page));

  await page.close();
  return {
    cold: {
      pair: coldPair,
      pageLoadMs,
      pickerReadyMs,
      resultsVisibleMs,
      searchToResultsMs: coldSearchToResultsMs,
    },
    warm: { pair: warmPair, searchToResultsMs: warmSearchToResultsMs },
  };
}

function percentile(sortedValues, p) {
  if (sortedValues.length === 0) return null;
  const index = Math.min(
    sortedValues.length - 1,
    Math.ceil((p / 100) * sortedValues.length) - 1,
  );
  return sortedValues[Math.max(0, index)];
}

// Recenters onto the first non-center neighbor currently rendered,
// `iterations` times, timing click -> the newly-centered node's real
// `data-is-center="true"` attribute (centerOn()'s own completion signal,
// not a guessed timeout). Returns null (not a partial array) if the graph
// ever runs out of a non-center neighbor to click -- a real dead end, not
// silently under-counted.
async function measureExplorerRecenter(page, iterations) {
  const samplesMs = [];
  for (let i = 0; i < iterations; i++) {
    const nextId = await page
      .locator(
        "[data-explorer-nodes] .explorer-node[data-artist-id]:not([data-is-center='true'])",
      )
      .first()
      .getAttribute("data-artist-id");
    if (nextId === null)
      return { samplesMs, incomplete: true, iterationsRun: i };

    const clickStart = Date.now();
    await page
      .locator(
        `[data-explorer-nodes] .explorer-node[data-artist-id="${nextId}"]`,
      )
      .click();
    await page
      .locator(
        `[data-explorer-nodes] .explorer-node[data-artist-id="${nextId}"][data-is-center="true"]`,
      )
      .waitFor({ state: "attached", timeout: 5_000 });
    samplesMs.push(Date.now() - clickStart);
  }
  const sorted = [...samplesMs].sort((a, b) => a - b);
  return {
    samplesMs,
    incomplete: false,
    iterationsRun: iterations,
    p50Ms: percentile(sorted, 50),
    p95Ms: percentile(sorted, 95),
    maxMs: sorted.length ? sorted[sorted.length - 1] : null,
  };
}

async function measureExplorerInit(context, albumId, heapSamples) {
  const page = await newPage(context);
  const navStart = Date.now();
  await page.goto(`${BASE_URL}/explore/${albumId}/`, { waitUntil: "load" });
  const pageLoadMs = Date.now() - navStart;
  await page
    .locator("[data-explorer-nodes] .explorer-node")
    .first()
    .waitFor({ state: "visible", timeout: 15_000 });
  const firstNodeVisibleMs = Date.now() - navStart;
  // `window.__NP_GRAPH_PARSE_MS__` (pathfindingGraph.ts) isolates the
  // worker's own parse+canonicalize+hash cost from page load -- this is
  // the timing hook docs/SITE_REPROFILE_METHOD.md previously documented as
  // missing entirely; `null` here means the page loaded but the graph
  // fetch/parse genuinely never completed (a real failure, not a stub).
  const workerParseMs = await page.evaluate(
    () => window.__NP_GRAPH_PARSE_MS__ ?? null,
  );
  heapSamples.push(await measureMemory(page));
  // Recenter measured on the SAME still-open page (graph/worker already
  // warm) -- a fresh navigation per recenter would measure page-load cost
  // 50 times over, not the in-page recenter cost the plan's budget
  // (p95 <= 100ms) is actually about.
  const recenter = await measureExplorerRecenter(page, RECENTER_ITERATIONS);
  heapSamples.push(await measureMemory(page));
  await page.close();
  return { pageLoadMs, firstNodeVisibleMs, workerParseMs, recenter };
}

async function measureAlbumShelf(context, heapSamples) {
  const page = await newPage(context);
  const navStart = Date.now();
  await page.goto(`${BASE_URL}/albums/`, { waitUntil: "load" });
  const pageLoadMs = Date.now() - navStart;
  const cardCount = await page.locator(".album-card").count();
  heapSamples.push(await measureMemory(page));
  await page.close();
  return { pageLoadMs, cardCount };
}

async function measureMemory(page) {
  const client = await page.context().newCDPSession(page);
  await client.send("Performance.enable");
  const metrics = await client.send("Performance.getMetrics");
  const heap = metrics.metrics.find((m) => m.name === "JSHeapUsedSize");
  await client.detach();
  return heap ? Math.round(heap.value / 1024 / 1024) : null;
}

async function run() {
  const browser = await chromium.launch();
  const results = {
    profile: DESKTOP_THROTTLED
      ? "desktop-4x-throttled"
      : MOBILE_THROTTLED
        ? "mobile-pixel5-4x-throttled"
        : "desktop-unthrottled",
    throttled: THROTTLED,
    payloads: measurePayloads(),
  };

  const sitemapPage = await browser.newPage();
  results.sitemap = await measureSitemap(sitemapPage);
  await sitemapPage.close();

  // `devices["Pixel 5"]` carries its own viewport (393x727 on the
  // Playwright version this repo pins, per `npx playwright --version` and
  // a direct `page.viewportSize()` check -- device descriptors have
  // changed across Playwright releases, so this is measured against the
  // committed version, not assumed) -- overridden
  // here to this repo's own established 390x844 mobile-testing viewport
  // (apps/web/tests/smoke.spec.ts's "mobile layout" describe block), so a
  // re-profile's mobile numbers are actually comparable to every other
  // mobile assertion in this codebase, not a third, unrelated size.
  // `--desktop-throttled` (graph-expansion Phase 0 slice 0-C) applies the
  // same 4x CPU throttle with NO device emulation -- default desktop
  // viewport -- the plan's third, distinct profile ("desktop, 4x throttled,
  // and a Pixel 5 device profile"), isolating CPU cost from the mobile
  // viewport/touch/UA differences the Pixel 5 profile also introduces.
  const contextOptions = MOBILE_THROTTLED
    ? { ...devices["Pixel 5"], viewport: { width: 390, height: 844 } }
    : {};
  const context = await browser.newContext(contextOptions);

  // Fetched before any timed page so the two page-load-dependent
  // measurements below (Connect's warm pair, Explorer's start album) can
  // both resolve real, current catalog data without a second round trip.
  const challengeRes = await context.request.get(
    `${BASE_URL}/data/challenge.v3.json`,
  );
  const challenge = await challengeRes.json();

  // A single JS-heap snapshot only ever caught whatever happened to be
  // resident at that one instant -- a real allocation spike during parsing
  // could already be GC'd by the time it's sampled. Sampling after each
  // measured page and reporting the max is a real improvement, but still
  // not a true continuous peak (that needs CDP heap profiling, a bigger
  // lift not obviously justified yet) -- labeled "observed," not "peak,"
  // in the output.
  const heapSamples = [];

  results.connect = await measureConnectReadiness(
    context,
    challenge,
    heapSamples,
  );

  // A real, connected album id from the committed catalog -- resolved from
  // the same challenge fetch above rather than hardcoded, so this survives
  // a future catalog regeneration.
  const connectedAlbumId = challenge.paths[0].from_album_id;
  results.explorer = await measureExplorerInit(
    context,
    connectedAlbumId,
    heapSamples,
  );
  results.albumShelf = await measureAlbumShelf(context, heapSamples);

  results.jsHeapUsedMb = {
    samplesMb: heapSamples,
    maxObservedMb: heapSamples.some((v) => v !== null)
      ? Math.max(...heapSamples.filter((v) => v !== null))
      : null,
  };

  await context.close();
  await browser.close();

  console.log(JSON.stringify(results, null, 2));
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
