// Connect Two Records presentation polish (ADR 0059 Phase 5 PR 5): the
// pre-selection empty state, endpoint cover art (with the site's own
// established placeholder fallback, ADR 0044/0045), the always-shown route
// length, and the closed-by-default "Why this route?" disclosure.

import { expect, test } from "@playwright/test";
import {
  picker,
  selectAlbum,
  selectRouteFilter,
} from "./helpers/connectPicker";

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
  // The catalog_version must MATCH the real catalog, or the registry is
  // rejected outright and this stops testing "an empty registry" -- it would
  // silently become a duplicate of the invalid-registry case while still
  // passing (both render placeholders). Read it from the real artifact so
  // the distinction survives every catalog regeneration.
  const catalogRes = await page.request.get("/data/catalog/albums.v1.json");
  const { catalog_version: realCatalogVersion } = (await catalogRes.json()) as {
    catalog_version: string;
  };
  await page.route("**/data/catalog/album-art.v1.json", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        schema_version: 1,
        catalog_version: realCatalogVersion,
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

// Phone-viewport coverage (matching game-mobile.spec.ts's established
// 390x844 probe for the flagship game) -- never checked for Connect
// before this phase's genuinely new layout (the timeline connector,
// endpoint cover cards, hop release sub-cards, the disclosure). Checked
// at both the empty pre-selection state and after a real completed
// search, the two states most likely to differ in width.
test.describe("390px viewport", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("Connect Two Records never scrolls sideways on a phone-sized screen, empty or with a completed search", async ({
    page,
  }) => {
    const overflow = () =>
      page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      );

    await page.goto("/play/connect/");
    await expect(page.locator("[data-connect-empty-state]")).toBeVisible();
    expect(await overflow()).toBeLessThanOrEqual(0);

    await selectAlbum(page, "a", "Discovery");
    await selectAlbum(page, "b", "Joshua Tree");
    await page.locator("[data-connect-search]").click();
    await expect(page.locator("[data-connect-results]")).toBeVisible({
      timeout: 15000,
    });
    expect(await overflow()).toBeLessThanOrEqual(0);

    // The disclosure's own expansion is a real, common layout change --
    // check it too, not just the closed default.
    await page.locator("[data-connect-why-primary] summary").click();
    expect(await overflow()).toBeLessThanOrEqual(0);
  });
});
