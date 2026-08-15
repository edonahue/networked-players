// Connect Two Records presentation polish (ADR 0059 Phase 5 PR 5): the
// pre-selection empty state, endpoint cover art (with the site's own
// established placeholder fallback, ADR 0044/0045), the always-shown route
// length, and the closed-by-default "Why this route?" disclosure.

import { expect, test } from "@playwright/test";
import { picker, selectAlbum } from "./helpers/connectPicker";

async function selectRouteFilter(
  page: import("@playwright/test").Page,
  value: "none" | "behind-the-glass" | "rhythm-section" | "guitar-paths",
) {
  await page.locator(`[data-connect-mode-option][value="${value}"]`).check();
}

test("the empty state is visible before any search and hides once a search starts", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await expect(page.locator("[data-connect-empty-state]")).toBeVisible();

  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
  await page.locator("[data-connect-search]").click();

  await expect(page.locator("[data-connect-empty-state]")).toBeHidden();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  await expect(page.locator("[data-connect-empty-state]")).toBeHidden();
});

test("a real pick that invalidates a completed search brings the empty state back", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  await expect(page.locator("[data-connect-empty-state]")).toBeHidden();

  await selectAlbum(page, "a", "Time Out");

  await expect(page.locator("[data-connect-results]")).toBeHidden();
  await expect(page.locator("[data-connect-empty-state]")).toBeVisible();
});

test("endpoint cards render real cover art from the album-art registry", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });

  const covers = page.locator(
    "[data-connect-hops] .connect-endpoint .connect-endpoint__cover",
  );
  await expect(covers).toHaveCount(2);
  for (const cover of await covers.all()) {
    await expect(cover).toHaveJSProperty("tagName", "IMG");
    const src = await cover.getAttribute("src");
    expect(src).toContain("i.discogs.com");
  }
});

test("an album with no art-registry entry renders the polished placeholder, not a broken image", async ({
  page,
}) => {
  await page.route("**/data/catalog/album-art.v1.json", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        schema_version: 1,
        catalog_version: "catalog-v1-20260601-0e7ec70fbb7e",
        art_version: "test-empty",
        albums: [],
      }),
    }),
  );
  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });

  const placeholders = page.locator(
    "[data-connect-hops] .connect-endpoint .connect-endpoint__cover--placeholder",
  );
  await expect(placeholders).toHaveCount(2);
  await expect(page.locator("[data-connect-hops] img")).toHaveCount(0);
});

test("route length is always shown, for a ranked search, a role-filtered search, and the distinct alternate", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  await expect(page.locator("[data-connect-route-length]")).toHaveText(
    /^\d+ hops? documented$/,
  );
  await expect(page.locator("[data-connect-route-length-alt]")).toHaveText(
    /^\d+ hops? documented$/,
  );

  await selectAlbum(page, "a", "Ziggy Stardust");
  await selectAlbum(page, "b", "A Night At The Opera");
  await selectRouteFilter(page, "behind-the-glass");
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  await expect(page.locator("[data-connect-route-length]")).toHaveText(
    /^\d+ hops? documented$/,
  );
});

test('"Why this route?" is a real disclosure, closed by default, that reveals the ranking explanation on click', async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });

  const why = page.locator("[data-connect-why-primary]");
  await expect(why).toBeVisible();
  await expect(why).not.toHaveJSProperty("open", true);
  const explanation = page.locator("[data-connect-explain-primary]");
  await expect(explanation).toBeHidden();

  await why.locator("summary").click();
  await expect(why).toHaveJSProperty("open", true);
  await expect(explanation).toBeVisible();
  await expect(explanation).toContainText(
    "no hop's evidence carries a published caveat",
  );
});

test('"Why this route?" stays hidden entirely for a role-filtered search, which never ranks', async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Ziggy Stardust");
  await selectAlbum(page, "b", "A Night At The Opera");
  await selectRouteFilter(page, "behind-the-glass");
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  await expect(page.locator("[data-connect-why-primary]")).toBeHidden();
});

test("swap preserves the endpoint cover art and route length across the reversed redisplay", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  const lengthBefore = await page
    .locator("[data-connect-route-length]")
    .textContent();

  await page.locator("[data-connect-swap]").click();
  await expect(
    picker(page, "a").locator("[data-picker-selected]"),
  ).toContainText("Joshua Tree");

  await expect(
    page.locator(
      "[data-connect-hops] .connect-endpoint .connect-endpoint__cover",
    ),
  ).toHaveCount(2);
  await expect(page.locator("[data-connect-route-length]")).toHaveText(
    lengthBefore ?? "",
  );
});

// A real review finding: `fetchAlbumArt()` has no fetch timeout, and
// endpoint covers are purely presentational, so a slow or hung art
// registry must never delay showing a route that's already been found.
test("a slow album-art registry never delays the route from rendering, and covers upgrade in place once it resolves", async ({
  page,
}) => {
  let releaseArt!: () => void;
  const artGate = new Promise<void>((resolve) => {
    releaseArt = resolve;
  });
  await page.route("**/data/catalog/album-art.v1.json", async (route) => {
    await artGate;
    await route.continue();
  });

  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
  await page.locator("[data-connect-search]").click();

  // The route renders fully -- status clears, results show, placeholders
  // stand in for the covers -- while the art registry is still gated.
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  await expect(page.locator("[data-connect-status]")).toBeHidden();
  const placeholders = page.locator(
    "[data-connect-hops] .connect-endpoint .connect-endpoint__cover--placeholder",
  );
  await expect(placeholders).toHaveCount(2);
  await expect(page.locator("[data-connect-hops] img")).toHaveCount(0);

  // Releasing it upgrades the placeholders to real covers in place --
  // the results stay mounted throughout, never re-rendered wholesale.
  releaseArt();
  await expect(
    page.locator("[data-connect-hops] .connect-endpoint img"),
  ).toHaveCount(2);
  await expect(placeholders).toHaveCount(0);
});
