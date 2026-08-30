#!/usr/bin/env node
// Site re-profile method (Phase 7 PR G, "re-profile against the 140-album
// baseline"). Real, reproducible measurements against a locally-served
// production build. Per ADR 0018, the numbers this script prints are NEVER
// committed to the repo -- only this method is public; results belong in
// `local/benchmarks/` (gitignored).
//
// Usage (from apps/web/):
//   npm run build && npm run preview -- --host 127.0.0.1 --port 4321 &
//   node scripts/reprofile-site.mjs [--mobile-throttled]
//
// What's compared against a real prior baseline, and what's a new one:
// - graph.v2.json payload size and sitemap URL counts have a real recorded
//   140-album figure in the Phase 7 plan doc's section 10 (13.6 MB,
//   843 URLs: 140 album/140 explore/549 contributor/14 static) -- this
//   script's own output should be read alongside those, not instead of.
// - Connect Two Records cold-readiness, Explorer init, album-shelf render,
//   and mobile CPU/memory were never benchmarked at 140 albums anywhere in
//   this repo. This run establishes a baseline for FUTURE re-profiles to
//   diff against, not a before/after for these specific numbers -- report
//   them as "observed now," never implied as a comparison.

import { chromium, devices } from "@playwright/test";
import { readFileSync, statSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { fileURLToPath } from "node:url";
import path from "node:path";

const BASE_URL = process.env.REPROFILE_BASE_URL ?? "http://127.0.0.1:4321";
const THROTTLED = process.argv.includes("--mobile-throttled");
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
    "data/challenge.v2.json",
    "data/pathfinding/graph.v2.json",
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

  // Discovery/The Joshua Tree: a real, directly-connected pair in the
  // committed pathfinding graph (see tests/game-connect.spec.ts's own
  // comment) -- picked from the real artifact, not invented.
  const coldSearchToResultsMs = await selectAndSearch(
    page,
    "Discovery",
    "The Joshua Tree",
  );
  const resultsVisibleMs = Date.now() - navStart;
  heapSamples.push(await measureMemory(page));

  const warmPair = pickWarmPair(
    challenge,
    new Set(["Discovery", "The Joshua Tree"]),
  );
  const warmSearchToResultsMs = warmPair
    ? await selectAndSearch(page, warmPair.fromTitle, warmPair.toTitle)
    : null;
  heapSamples.push(await measureMemory(page));

  await page.close();
  return {
    cold: {
      pageLoadMs,
      pickerReadyMs,
      resultsVisibleMs,
      searchToResultsMs: coldSearchToResultsMs,
    },
    warm: { pair: warmPair, searchToResultsMs: warmSearchToResultsMs },
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
  heapSamples.push(await measureMemory(page));
  await page.close();
  return { pageLoadMs, firstNodeVisibleMs };
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
    throttled: THROTTLED,
    payloads: measurePayloads(),
    // No timing hook exists anywhere in the app (graphWorker.ts posts a
    // result message with no elapsed-time field) to isolate worker parse
    // time from page load -- rather than fake a number by subtracting two
    // already-noisy wall-clock timings, this is left explicitly null. See
    // docs/SITE_REPROFILE_METHOD.md.
    workerParseMs: null,
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
  const contextOptions = THROTTLED
    ? { ...devices["Pixel 5"], viewport: { width: 390, height: 844 } }
    : {};
  const context = await browser.newContext(contextOptions);

  // Fetched before any timed page so the two page-load-dependent
  // measurements below (Connect's warm pair, Explorer's start album) can
  // both resolve real, current catalog data without a second round trip.
  const challengeRes = await context.request.get(
    `${BASE_URL}/data/challenge.v2.json`,
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
