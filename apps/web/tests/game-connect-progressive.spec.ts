// Progressive rendering (ADR 0059 Phase 5 PR 5b): graph preparation begins
// on the real intent signal of a second valid pick, not the search click,
// and status text is staged honestly rather than one flat "Searching…".

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { selectAlbum } from "./helpers/connectPicker";

async function selectRouteFilter(
  page: import("@playwright/test").Page,
  value: "none" | "behind-the-glass" | "rhythm-section" | "guitar-paths",
) {
  await page.locator(`[data-connect-mode-option][value="${value}"]`).check();
}

test("the pathfinding graph is requested as soon as both albums are picked, before the search click", async ({
  page,
}) => {
  let graphFetches = 0;
  await page.route("**/data/pathfinding/graph.v2.json", (route) => {
    graphFetches++;
    return route.continue();
  });

  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  expect(graphFetches).toBe(0);

  await selectAlbum(page, "b", "Joshua Tree");
  await expect.poll(() => graphFetches).toBe(1);

  // The search click still works normally and doesn't re-fetch --
  // loadPreparedGraph's own memoized cache absorbs the click's own call.
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  expect(graphFetches).toBe(1);
});

test("the album-art registry is requested as soon as both albums are picked, before the search click", async ({
  page,
}) => {
  let artFetches = 0;
  await page.route("**/data/catalog/album-art.v1.json", (route) => {
    artFetches++;
    return route.continue();
  });

  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  expect(artFetches).toBe(0);

  await selectAlbum(page, "b", "Joshua Tree");
  await expect.poll(() => artFetches).toBe(1);
});

// The narrower, deliberately-preserved half of the progressive-rendering
// design: unlike the graph, evidence is NOT warmed on pick-completion,
// because whether it's needed at all depends on the role-filter mode,
// which isn't decided yet at pick time (defaults to unfiltered, but
// picking both albums and only afterward choosing a role filter is a
// real, common order). Warming it unconditionally here would silently
// reintroduce the exact wasted-fetch cost
// `runSearch`'s own mode-conditional fetch was written to avoid.
test("picking both albums does not eagerly fetch the evidence registry, even before a role filter is chosen", async ({
  page,
}) => {
  let evidenceFetches = 0;
  await page.route("**/data/evidence/release-registry.v1.json", (route) => {
    evidenceFetches++;
    return route.continue();
  });

  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Time Out");
  await selectAlbum(page, "b", "Rumours");
  expect(evidenceFetches).toBe(0);

  await selectRouteFilter(page, "behind-the-glass");
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-status]")).toContainText(
    /no producer\/engineer-only connection/i,
  );
  expect(evidenceFetches).toBe(0);
});

test("status is staged honestly: loading the graph, then ranking, for an unfiltered search", async ({
  page,
}) => {
  let releaseGraph!: () => void;
  const graphGate = new Promise<void>((resolve) => {
    releaseGraph = resolve;
  });
  await page.route("**/data/pathfinding/graph.v2.json", async (route) => {
    await graphGate;
    await route.continue();
  });
  // Also gate evidence -- ranking needs it, so this is what holds status at
  // the second stage long enough to observe it; without this the whole
  // rest of the search resolves in the same tick the graph gate releases
  // in, and a real, working transition can race past a polling assertion.
  let releaseEvidence!: () => void;
  const evidenceGate = new Promise<void>((resolve) => {
    releaseEvidence = resolve;
  });
  const realEvidenceBody = readFileSync(
    join(process.cwd(), "public/data/evidence/release-registry.v1.json"),
  );
  await page.route(
    "**/data/evidence/release-registry.v1.json",
    async (route) => {
      await evidenceGate;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: realEvidenceBody,
      });
    },
  );

  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
  await page.locator("[data-connect-search]").click();

  await expect(page.locator("[data-connect-status]")).toHaveText(
    /loading the connection graph/i,
  );

  releaseGraph();

  await expect(page.locator("[data-connect-status]")).toHaveText(
    /ranking documented routes/i,
  );

  releaseEvidence();

  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
});

test("status is staged honestly: loading the graph, then searching, for a role-filtered search", async ({
  page,
}) => {
  let releaseGraph!: () => void;
  const graphGate = new Promise<void>((resolve) => {
    releaseGraph = resolve;
  });
  await page.route("**/data/pathfinding/graph.v2.json", async (route) => {
    await graphGate;
    await route.continue();
  });
  // Gates the rendering-only evidence fetch this mode makes AFTER finding
  // its route, holding status at the second stage long enough to observe.
  let releaseEvidence!: () => void;
  const evidenceGate = new Promise<void>((resolve) => {
    releaseEvidence = resolve;
  });
  const realEvidenceBody = readFileSync(
    join(process.cwd(), "public/data/evidence/release-registry.v1.json"),
  );
  await page.route(
    "**/data/evidence/release-registry.v1.json",
    async (route) => {
      await evidenceGate;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: realEvidenceBody,
      });
    },
  );

  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Ziggy Stardust");
  await selectAlbum(page, "b", "A Night At The Opera");
  await selectRouteFilter(page, "behind-the-glass");
  await page.locator("[data-connect-search]").click();

  await expect(page.locator("[data-connect-status]")).toHaveText(
    /loading the connection graph/i,
  );

  releaseGraph();

  await expect(page.locator("[data-connect-status]")).toHaveText(
    /searching for a documented connection/i,
  );

  releaseEvidence();

  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
});
