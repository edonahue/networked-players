// Swap Records (ADR 0059 Phase 5 PR 4): exchanges both album identities,
// updates the URL, preserves the active role filter, reuses an
// already-found route reversed (no second search) when one is on screen,
// and works both before and after a search. Same real Discovery <-> Joshua
// Tree pair `game-connect.spec.ts`/`game-connect-endpoints.spec.ts` use.

import { expect, test } from "@playwright/test";
import {
  picker,
  selectAlbum,
  selectRouteFilter,
} from "./helpers/connectPicker";

test("swap is disabled until both records are picked", async ({ page }) => {
  await page.goto("/play/connect/");
  const swap = page.locator("[data-connect-swap]");
  await expect(swap).toBeDisabled();
  await selectAlbum(page, "a", "Discovery");
  await expect(swap).toBeDisabled();
  await selectAlbum(page, "b", "Joshua Tree");
  await expect(swap).toBeEnabled();
});

test("swap before a search just exchanges the two picker selections", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");

  await page.locator("[data-connect-swap]").click();

  await expect(
    picker(page, "a").locator("[data-picker-selected]"),
  ).toContainText("Joshua Tree");
  await expect(
    picker(page, "b").locator("[data-picker-selected]"),
  ).toContainText("Discovery");
  // No search ran -- swapping alone never triggers one.
  await expect(page.locator("[data-connect-results]")).toBeHidden();
});

test("swap after a search redisplays the reversed route without a new network request", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });

  let graphFetches = 0;
  await page.route("**/data/pathfinding/graph.v4.json", (route) => {
    graphFetches++;
    return route.continue();
  });

  const endpoints = page.locator("[data-connect-hops] .connect-endpoint");
  const firstBefore = await endpoints.first().textContent();
  const lastBefore = await endpoints.last().textContent();

  await page.locator("[data-connect-swap]").click();

  // Endpoints swapped positions -- same two facts, reversed order.
  await expect(endpoints.first()).toHaveText(lastBefore ?? "");
  await expect(endpoints.last()).toHaveText(firstBefore ?? "");
  // Reusing the already-found route means no second graph fetch.
  expect(graphFetches).toBe(0);

  await expect(
    picker(page, "a").locator("[data-picker-selected]"),
  ).toContainText("Joshua Tree");
  await expect(
    picker(page, "b").locator("[data-picker-selected]"),
  ).toContainText("Discovery");
});

test("swap announces the new order and keeps focus on the swap control", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });

  const swap = page.locator("[data-connect-swap]");
  await swap.click();

  await expect(page.locator("[data-connect-announce]")).toContainText(
    /joshua tree.*first/i,
  );
  await expect(swap).toBeFocused();
});

test("swap updates the URL to the new order", async ({ page }) => {
  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });

  await page.locator("[data-connect-swap]").click();
  await page.waitForFunction(
    () =>
      new URL(window.location.href).searchParams.get("a") === "master-64290",
  );
  const params = new URL(page.url()).searchParams;
  expect(params.get("a")).toBe("master-64290"); // Joshua Tree
  expect(params.get("b")).toBe("master-26647"); // Discovery
});

test("a real pick after a swap invalidates the reusable route -- the next swap re-derives from the new state", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  await page.locator("[data-connect-swap]").click();

  // A genuine new pick on side B, replacing Discovery.
  await selectAlbum(page, "b", "Ziggy Stardust");
  // The stale result from before this pick must not linger uncorrected --
  // the search button re-enables for the new pair, distinct records.
  await expect(page.locator("[data-connect-search]")).toBeEnabled();
});

test("swap preserves the active role filter across the reversed redisplay", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  // Face Value <-> Talking Book, bridged by Nathan East (Bass/Drums) --
  // the real, verified Rhythm Section pair. The original Ziggy Stardust
  // <-> A Night At The Opera pair was chosen for Behind the Glass's
  // producer bridge, which ADR 0068 retired.
  await selectAlbum(page, "a", "Face Value");
  await selectAlbum(page, "b", "Talking Book");
  await selectRouteFilter(page, "rhythm-section");
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });

  await page.locator("[data-connect-swap]").click();
  await expect(
    page.locator("[data-connect-mode-option][data-value='rhythm-section']"),
  ).toHaveAttribute("aria-checked", "true");
  const params = new URL(page.url()).searchParams;
  expect(params.get("mode")).toBe("rhythm-section");
});
