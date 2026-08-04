// Connect Two Records (ADR 0051) integration tests against the real
// committed pathfinding graph. "Discovery" (Daft Punk) and "The Joshua
// Tree" (U2) are a real, directly-connected pair in the committed artifact
// (verified against apps/web/public/data/pathfinding/graph.v1.json) --
// picked from the artifact itself, not hardcoded blindly, so this survives
// a future regeneration only if that specific edge remains; if it doesn't,
// this test's failure is itself a useful signal to pick a new real pair.

import { expect, test } from "@playwright/test";

async function selectAlbum(
  page: import("@playwright/test").Page,
  picker: string,
  query: string,
) {
  const input = page.locator(`[data-picker="${picker}"] input`);
  await input.fill(query);
  await page
    .locator(`[data-picker="${picker}"] [data-picker-results] button`)
    .first()
    .click();
}

async function selectRouteFilter(
  page: import("@playwright/test").Page,
  value: "none" | "behind-the-glass" | "rhythm-section" | "guitar-paths",
) {
  await page.locator(`[data-connect-mode-option][value="${value}"]`).check();
}

test("a real connected pair finds a documented route with evidence", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");

  const searchButton = page.locator("[data-connect-search]");
  await expect(searchButton).toBeEnabled();
  await searchButton.click();

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

test("search button stays disabled until two different albums are picked", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await expect(page.locator("[data-connect-search]")).toBeDisabled();
  await selectAlbum(page, "a", "Discovery");
  await expect(page.locator("[data-connect-search]")).toBeDisabled();
});

test("picking the same album twice keeps the search disabled", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Discovery");
  await expect(page.locator("[data-connect-search]")).toBeDisabled();
});

test("a fetch failure for the pathfinding graph degrades gracefully", async ({
  page,
}) => {
  await page.route("**/data/pathfinding/graph.v1.json", (route) =>
    route.abort(),
  );
  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
  await page.locator("[data-connect-search]").click();

  await expect(page.locator("[data-connect-status]")).toBeVisible();
  await expect(page.locator("[data-connect-status]")).toContainText(
    /couldn't fetch/i,
  );
  await expect(page.locator("[data-connect-results]")).toBeHidden();
});

test("the rest of the page keeps working after a failed search", async ({
  page,
}) => {
  await page.route("**/data/pathfinding/graph.v1.json", (route) =>
    route.abort(),
  );
  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-status]")).toBeVisible();

  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByRole("link", { name: "About" })).toBeVisible();
});

// Behind the Glass (ADR 0053): restricts the same search to producer/
// engineer/mixer-only credits. Ziggy Stardust (David Bowie) <-> A Night
// At The Opera (Queen) is a real, directly-connected pair in the committed
// artifact bridged by a shared "Producer" credit -- verified against
// apps/web/public/data/pathfinding/graph.v1.json.
test("Behind the Glass finds a real producer-only connection", async ({
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
  const hop = page.locator("[data-connect-hops] .connect-hop").first();
  await expect(hop).toBeVisible();
  await expect(hop).toContainText(/producer/i);
  // No role-signal re-ranking section in this mode -- every hop is already
  // producer/engineer-only by construction.
  await expect(page.locator("[data-connect-result='musical']")).toBeHidden();
});

// Discovery <-> Joshua Tree's real direct edge is a plain "Credited
// artist" credit, not a producer/engineer credit, and there is no
// producer/engineer-only bridge between them within 4 hops either
// (verified against the committed artifact) -- a real negative case for
// the filtered search, distinct from "no-path" in the unfiltered mode.
test("Behind the Glass reports no connection when the real path doesn't qualify", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
  await selectRouteFilter(page, "behind-the-glass");
  await page.locator("[data-connect-search]").click();

  await expect(page.locator("[data-connect-status]")).toBeVisible();
  await expect(page.locator("[data-connect-status]")).toContainText(
    /no producer\/engineer-only connection/i,
  );
  await expect(page.locator("[data-connect-results]")).toBeHidden();
});

// Rhythm Section: restricts the search to drums/bass-only credits.
// "Face Value" (Phil Collins) <-> "Talking Book" (Stevie Wonder) is a
// real, two-hop path bridged by Nathan East (Bass/Drums both hops) --
// verified against the committed pathfinding graph artifact. No direct
// one-hop rhythm-section pair exists among the 140-album catalog's main
// artists, so this is a genuine multi-hop case, unlike Behind the Glass's
// one-hop pair.
test("Rhythm Section finds a real drums/bass-only connection", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Face Value");
  await selectAlbum(page, "b", "Talking Book");
  await selectRouteFilter(page, "rhythm-section");
  await page.locator("[data-connect-search]").click();

  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  const hops = page.locator("[data-connect-hops] .connect-hop");
  await expect(hops).toHaveCount(2);
  await expect(hops.first()).toContainText(/drums|bass/i);
  await expect(page.locator("[data-connect-result='musical']")).toBeHidden();
});

// Guitar Paths: restricts the search to guitar-only credits. "Blood On
// The Tracks" (Bob Dylan) <-> "Harvest" (Neil Young) is a real, directly-
// connected pair bridged by a shared "Guitar, Vocals" credit -- verified
// against the committed artifact.
test("Guitar Paths finds a real guitar-only connection", async ({ page }) => {
  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Blood On The Tracks");
  await selectAlbum(page, "b", "Harvest");
  await selectRouteFilter(page, "guitar-paths");
  await page.locator("[data-connect-search]").click();

  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  const hop = page.locator("[data-connect-hops] .connect-hop").first();
  await expect(hop).toBeVisible();
  await expect(hop).toContainText(/guitar/i);
});

// Discovery <-> Joshua Tree has no rhythm-section- or guitar-only bridge
// within 4 hops either (verified against the committed artifact) -- the
// same real negative case reused across every filtered mode.
test("Rhythm Section and Guitar Paths report no connection for the same real non-matching pair", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");

  await selectRouteFilter(page, "rhythm-section");
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-status]")).toContainText(
    /no drums\/bass-only connection/i,
  );

  await selectRouteFilter(page, "guitar-paths");
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-status]")).toContainText(
    /no guitar-only connection/i,
  );
});

// The radio group is mutually exclusive by construction -- selecting a
// second filter must deselect the first, never leave two checked.
test("only one route filter can be selected at a time", async ({ page }) => {
  await page.goto("/play/connect/");
  await selectRouteFilter(page, "behind-the-glass");
  await selectRouteFilter(page, "guitar-paths");
  await expect(
    page.locator('[data-connect-mode-option][value="behind-the-glass"]'),
  ).not.toBeChecked();
  await expect(
    page.locator('[data-connect-mode-option][value="guitar-paths"]'),
  ).toBeChecked();
});
