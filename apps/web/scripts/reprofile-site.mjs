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

async function measureConnectColdStart(context) {
  const page = await newPage(context);
  const navStart = Date.now();
  await page.goto(`${BASE_URL}/play/connect/`, { waitUntil: "load" });
  const pageLoadMs = Date.now() - navStart;

  await page.waitForSelector('[data-picker="a"][data-picker-state="ready"]');
  const pickerReadyMs = Date.now() - navStart;

  // Discovery/The Joshua Tree: a real, directly-connected pair in the
  // committed pathfinding graph (see tests/game-connect.spec.ts's own
  // comment) -- picked from the real artifact, not invented.
  await page.locator('[data-picker="a"] input').fill("Discovery");
  await page
    .locator('[data-picker="a"] [data-picker-results] [role="option"]')
    .first()
    .click();
  await page.locator('[data-picker="b"] input').fill("The Joshua Tree");
  await page
    .locator('[data-picker="b"] [data-picker-results] [role="option"]')
    .first()
    .click();

  const searchClickedAt = Date.now();
  await page.locator("[data-connect-search]").click();
  await page
    .locator("[data-connect-results]")
    .waitFor({ state: "visible", timeout: 15_000 });
  const resultsVisibleMs = Date.now() - navStart;
  const searchToResultsMs = Date.now() - searchClickedAt;

  await page.close();
  return { pageLoadMs, pickerReadyMs, resultsVisibleMs, searchToResultsMs };
}

async function measureExplorerInit(context, albumId) {
  const page = await newPage(context);
  const navStart = Date.now();
  await page.goto(`${BASE_URL}/explore/${albumId}/`, { waitUntil: "load" });
  const pageLoadMs = Date.now() - navStart;
  await page
    .locator("[data-explorer-nodes] .explorer-node")
    .first()
    .waitFor({ state: "visible", timeout: 15_000 });
  const firstNodeVisibleMs = Date.now() - navStart;
  await page.close();
  return { pageLoadMs, firstNodeVisibleMs };
}

async function measureAlbumShelf(context) {
  const page = await newPage(context);
  const navStart = Date.now();
  await page.goto(`${BASE_URL}/albums/`, { waitUntil: "load" });
  const pageLoadMs = Date.now() - navStart;
  const cardCount = await page.locator(".album-card").count();
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
  const results = { throttled: THROTTLED, payloads: measurePayloads() };

  const sitemapPage = await browser.newPage();
  results.sitemap = await measureSitemap(sitemapPage);
  await sitemapPage.close();

  const contextOptions = THROTTLED ? { ...devices["Pixel 5"] } : {};
  const context = await browser.newContext(contextOptions);

  results.connect = await measureConnectColdStart(context);

  // A real, connected album id from the committed catalog -- resolved from
  // the sitemap fetch above's own request rather than hardcoded, so this
  // survives a future catalog regeneration.
  const albumsRes = await context.request.get(
    `${BASE_URL}/data/challenge.v2.json`,
  );
  const challenge = await albumsRes.json();
  const connectedAlbumId = challenge.paths[0].from_album_id;
  results.explorer = await measureExplorerInit(context, connectedAlbumId);
  results.albumShelf = await measureAlbumShelf(context);

  const memPage = await newPage(context);
  await memPage.goto(`${BASE_URL}/albums/`, { waitUntil: "load" });
  results.jsHeapUsedMb = await measureMemory(memPage);
  await memPage.close();

  await context.close();
  await browser.close();

  console.log(JSON.stringify(results, null, 2));
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
