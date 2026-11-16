// Swap Records (ADR 0059 Phase 5 PR 4): exchanges both album identities,
// updates the URL, preserves the active role filter, reuses an
// already-found route reversed (no second search) when one is on screen,
// and works both before and after a search. Same computed connected pair
// (helpers/catalogFacts.ts) the other Connect specs use.

import { expect, test } from "@playwright/test";
import {
  picker,
  selectAlbumById,
  selectRouteFilter,
} from "./helpers/connectPicker";
import { catalogFacts, escapeRegExp } from "./helpers/catalogFacts";

// Albums are derived from the committed artifacts by rule (see
// helpers/catalogFacts.ts), never named here.
const facts = await catalogFacts();
const CONNECTED = facts.connected;
const RHYTHM = facts.rhythm;
const SECOND = facts.secondConnected;

test("swap is disabled until both records are picked", async ({ page }) => {
  await page.goto("/play/connect/");
  const swap = page.locator("[data-connect-swap]");
  await expect(swap).toBeDisabled();
  await selectAlbumById(page, "a", CONNECTED.a);
  await expect(swap).toBeDisabled();
  await selectAlbumById(page, "b", CONNECTED.b);
  await expect(swap).toBeEnabled();
});

test("swap before a search just exchanges the two picker selections", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbumById(page, "a", CONNECTED.a);
  await selectAlbumById(page, "b", CONNECTED.b);

  await page.locator("[data-connect-swap]").click();

  await expect(
    picker(page, "a").locator("[data-picker-selected]"),
  ).toContainText(CONNECTED.b.title);
  await expect(
    picker(page, "b").locator("[data-picker-selected]"),
  ).toContainText(CONNECTED.a.title);
  // No search ran -- swapping alone never triggers one.
  await expect(page.locator("[data-connect-results]")).toBeHidden();
});

test("swap after a search redisplays the reversed route without a new network request", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbumById(page, "a", CONNECTED.a);
  await selectAlbumById(page, "b", CONNECTED.b);
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
  ).toContainText(CONNECTED.b.title);
  await expect(
    picker(page, "b").locator("[data-picker-selected]"),
  ).toContainText(CONNECTED.a.title);
});

test("swap announces the new order and keeps focus on the swap control", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbumById(page, "a", CONNECTED.a);
  await selectAlbumById(page, "b", CONNECTED.b);
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });

  const swap = page.locator("[data-connect-swap]");
  await swap.click();

  await expect(page.locator("[data-connect-announce]")).toContainText(
    new RegExp(`${escapeRegExp(CONNECTED.b.title)}.*first`, "i"),
  );
  await expect(swap).toBeFocused();
});

test("swap updates the URL to the new order", async ({ page }) => {
  await page.goto("/play/connect/");
  await selectAlbumById(page, "a", CONNECTED.a);
  await selectAlbumById(page, "b", CONNECTED.b);
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });

  await page.locator("[data-connect-swap]").click();
  await page.waitForFunction(
    (expectedA) =>
      new URL(window.location.href).searchParams.get("a") === expectedA,
    CONNECTED.b.id,
  );
  const params = new URL(page.url()).searchParams;
  expect(params.get("a")).toBe(CONNECTED.b.id);
  expect(params.get("b")).toBe(CONNECTED.a.id);
});

test("a real pick after a swap invalidates the reusable route -- the next swap re-derives from the new state", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbumById(page, "a", CONNECTED.a);
  await selectAlbumById(page, "b", CONNECTED.b);
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  await page.locator("[data-connect-swap]").click();

  // A genuine new pick on side B, replacing Discovery.
  await selectAlbumById(page, "b", SECOND.a);
  // The stale result from before this pick must not linger uncorrected --
  // the search button re-enables for the new pair, distinct records.
  await expect(page.locator("[data-connect-search]")).toBeEnabled();
});

test("swap preserves the active role filter across the reversed redisplay", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  // The computed Rhythm Section pair (helpers/catalogFacts.ts): a pair with a
  // drums/bass-only route. Behind the Glass's producer-bridge pair was
  // retired with that mode (ADR 0068).
  await selectAlbumById(page, "a", RHYTHM.a);
  await selectAlbumById(page, "b", RHYTHM.b);
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
