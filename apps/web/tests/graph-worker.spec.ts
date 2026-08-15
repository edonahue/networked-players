// Off-main-thread graph parse/canonicalize/hash (ADR 0059 Phase 5 PR 5c).
// `loadPathfindingGraph` delegates to a dedicated Worker when one can be
// constructed, falling back to doing the identical work on the main thread
// when it can't -- these tests exercise both paths against a real browser,
// not a mocked Worker global.

import { expect, test } from "@playwright/test";
import { selectAlbum } from "./helpers/connectPicker";

test("the pathfinding graph is loaded via a dedicated Worker script, not only inline on the main thread", async ({
  page,
}) => {
  const workerScriptRequests: string[] = [];
  page.on("request", (req) => {
    if (/\/graphWorker[.\-][^/]*\.js$/.test(new URL(req.url()).pathname)) {
      workerScriptRequests.push(req.url());
    }
  });

  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });

  expect(workerScriptRequests.length).toBeGreaterThan(0);
});

test("a search still finds a real, correct route when Worker construction fails (main-thread fallback)", async ({
  page,
}) => {
  await page.addInitScript(() => {
    // Simulates an environment where constructing a Worker throws (e.g. a
    // strict CSP) -- exercises `getGraphWorker`'s catch branch, which is
    // the realistic failure mode this fallback exists for.
    // @ts-expect-error -- deliberately replacing the global for this test
    window.Worker = class {
      constructor() {
        throw new Error("simulated: Worker construction blocked");
      }
    };
  });

  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
  await page.locator("[data-connect-search]").click();

  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  await expect(
    page.locator("[data-connect-hops] .connect-hop").first(),
  ).toBeVisible();
  await expect(
    page.locator("[data-connect-hops] a[href*='discogs.com/release/']").first(),
  ).toBeVisible();
});

test("a Worker that crashes on load falls back to the main thread for that search", async ({
  page,
}) => {
  // Replaces the real worker script with one that throws immediately at
  // top-level evaluation -- fires the Worker object's own `error` event on
  // the main thread, the real crash signal `wireGraphWorker`'s handler
  // reacts to (distinct from a request the worker completed normally and
  // reported a real failure for).
  await page.route("**/graphWorker*.js", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/javascript",
      body: "throw new Error('simulated worker crash');",
    }),
  );

  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
  await page.locator("[data-connect-search]").click();

  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  await expect(
    page.locator("[data-connect-hops] .connect-hop").first(),
  ).toBeVisible();
});

test("a fetch failure still degrades gracefully when going through the Worker", async ({
  page,
}) => {
  await page.route("**/data/pathfinding/graph.v2.json", (route) =>
    route.abort(),
  );
  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
  await page.locator("[data-connect-search]").click();

  await expect(page.locator("[data-connect-status]")).toContainText(
    /couldn't fetch/i,
  );
  await expect(page.locator("[data-connect-results]")).toBeHidden();
});
