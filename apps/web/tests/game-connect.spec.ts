// Connect Two Records (ADR 0051) integration tests against the real
// committed pathfinding graph. "Discovery" (Daft Punk) and "The Joshua
// Tree" (U2) are a real, directly-connected pair in the committed artifact
// (verified against apps/web/public/data/pathfinding/graph.v2.json) --
// picked from the artifact itself, not hardcoded blindly, so this survives
// a future regeneration only if that specific edge remains; if it doesn't,
// this test's failure is itself a useful signal to pick a new real pair.

import { expect, test } from "@playwright/test";
import { picker, pickerResults, selectAlbum } from "./helpers/connectPicker";

async function selectRouteFilter(
  page: import("@playwright/test").Page,
  value: "none" | "behind-the-glass" | "rhythm-section" | "guitar-paths",
) {
  await page.locator(`[data-connect-mode-option][value="${value}"]`).check();
}

// Initialization race (P1 after #108). The inputs are interactive from first
// paint, long before the deferred module has fetched the album catalog. This
// gates the catalog response behind a manually released promise so "the user
// types during initialization" is a controlled, deterministic event rather
// than a matter of typing fast enough. Against the pre-fix code this fails
// for exactly the right reason: wirePicker ran only after the fetch resolved,
// so the typed value's `input` event hit no listener and nothing ever
// re-evaluated it -- suggestions stayed empty until a second keystroke.
test("a query typed before the catalog arrives is evaluated when it lands", async ({
  page,
}) => {
  let releaseCatalog!: () => void;
  const catalogGate = new Promise<void>((resolve) => {
    releaseCatalog = resolve;
  });
  await page.route("**/data/catalog/albums.v1.json", async (route) => {
    await catalogGate;
    await route.continue();
  });

  await page.goto("/play/connect/");

  const pickerA = picker(page, "a");
  const input = pickerA.locator("input");
  await expect(pickerA).toHaveAttribute("data-picker-state", "loading");
  await expect(input).toHaveAttribute("aria-busy", "true");

  // Type while the catalog is still in flight.
  await input.fill("Discovery");
  await expect(pickerResults(page, "a")).toHaveCount(0);

  releaseCatalog();

  // No second input event, no synthetic keystroke: the picker re-evaluates
  // the value already in the box once the catalog is ready.
  await expect(pickerA).toHaveAttribute("data-picker-state", "ready");
  await expect(input).toHaveAttribute("aria-busy", "false");
  await expect(pickerResults(page, "a").first()).toBeVisible();
  await expect(input).toHaveValue("Discovery");

  // The picker is fully usable by keyboard from that recovered state.
  await input.press("Tab");
  await expect(pickerResults(page, "a").first()).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(pickerA.locator("[data-picker-selected]")).toContainText(
    "Discovery",
  );
});

// A catalog that fails to load must leave a recoverable control, not a
// silently dead input. Pre-fix, a non-`ok` response yielded an empty catalog
// with no message at all (indistinguishable from "nothing matched"), and a
// thrown fetch returned early without even wiring the search button.
test("a failed catalog load is announced and recovers on the next keystroke", async ({
  page,
}) => {
  let attempts = 0;
  await page.route("**/data/catalog/albums.v1.json", async (route) => {
    attempts += 1;
    if (attempts === 1) return route.fulfill({ status: 503, body: "" });
    return route.continue();
  });

  await page.goto("/play/connect/");

  const pickerA = picker(page, "a");
  await expect(pickerA).toHaveAttribute("data-picker-state", "unavailable");
  await expect(page.locator("[data-connect-status]")).toContainText(
    /couldn't load the album list/i,
  );

  // Typing again retries the load, and the recovered catalog is applied to
  // the text already in the box.
  await pickerA.locator("input").fill("Discovery");
  await expect(pickerA).toHaveAttribute("data-picker-state", "ready");
  await expect(pickerResults(page, "a").first()).toBeVisible();
  expect(attempts).toBe(2);
});

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

// The recommended-route engine (ADR 0059, Phase 5 PR 3): Discovery ->
// Joshua Tree is the ADR's own diagnostic pair -- production's plain BFS
// used to surface a route through "u2", evidenced by a 1998 Italian
// mashup 12" (release #200783, now published with the `unofficial` caveat
// flag). Verified against the real committed artifacts: an equal-hop,
// uncaveated alternative exists (Alex And Martin <-> U2), so the ranked
// engine should pick it and label the result accordingly -- this is a
// real, live behavior change this PR ships, not just an internal refactor.
test("the diagnostic pair (Discovery / Joshua Tree) is ranked away from its caveated evidence", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
  await page.locator("[data-connect-search]").click();

  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  await expect(page.locator("[data-connect-eyebrow]")).toHaveText(
    "Recommended documented route",
  );
  const explanation = page.locator("[data-connect-explain-primary]");
  await expect(explanation).toBeVisible();
  await expect(explanation).toContainText(
    "no hop's evidence carries a published caveat",
  );
  // The bootleg release must never appear as the recommended route's own
  // evidence -- it may still appear elsewhere (the distinct alternate,
  // an evidence card) since it is never hidden, only de-prioritized.
  await expect(
    page.locator("[data-connect-hops] a[href*='/release/200783']"),
  ).toHaveCount(0);
});

// Distinct alternate route (ADR 0058 Slice 7, renamed post-Phase-4 cleanup
// audit -- the old label implied a musical ranking this never actually
// computed, see ADR 0051's addendum): a real second bounded search that
// hard-excludes the first route's own edges. Discovery <-> Joshua Tree's
// real committed data has a genuinely distinct alternate route within the
// same hop budget (verified against
// apps/web/public/data/pathfinding/graph.v2.json) -- this directly
// regression-guards the pre-Slice-7 bug where this section silently
// re-rendered the same hop list under a second heading.
test("the distinct alternate route section renders content genuinely distinct from the documented route", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
  await page.locator("[data-connect-search]").click();

  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  const alternateSection = page.locator("[data-connect-result='alternate']");
  await expect(alternateSection).toBeVisible();

  const documentedHtml = await page.locator("[data-connect-hops]").innerHTML();
  const alternateHtml = await page
    .locator("[data-connect-hops-alternate]")
    .innerHTML();
  expect(alternateHtml.length).toBeGreaterThan(0);
  expect(alternateHtml).not.toBe(documentedHtml);
  await expect(page.locator("[data-connect-explain]")).not.toContainText(
    /no distinct alternate route/i,
  );
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
  await page.route("**/data/pathfinding/graph.v2.json", (route) =>
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
  await page.route("**/data/pathfinding/graph.v2.json", (route) =>
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

// loadPreparedGraph (post-Phase-4 cleanup audit F11/F12): the ~2.34MB
// graph is fetched, parsed, and indexed at most once per page session --
// a second/third search on the same page load must not re-issue the
// network request at all, not just reuse a sessionStorage cache entry.
test("a multi-search session fetches the pathfinding graph exactly once", async ({
  page,
}) => {
  let fetchCount = 0;
  await page.route("**/data/pathfinding/graph.v2.json", (route) => {
    fetchCount++;
    return route.continue();
  });
  await page.goto("/play/connect/");

  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });

  await selectAlbum(page, "a", "Ziggy Stardust");
  await selectAlbum(page, "b", "A Night At The Opera");
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });

  expect(fetchCount).toBe(1);
});

// Behind the Glass (ADR 0053): restricts the same search to producer/
// engineer/mixer-only credits. Ziggy Stardust (David Bowie) <-> A Night
// At The Opera (Queen) is a real, directly-connected pair in the committed
// artifact bridged by a shared "Producer" credit -- verified against
// apps/web/public/data/pathfinding/graph.v2.json.
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
  await expect(page.locator("[data-connect-result='alternate']")).toBeHidden();
});

// "Time Out" (Dave Brubeck) <-> "Rumours" (Fleetwood Mac) has a real
// unfiltered connection in the committed artifact but no producer/
// engineer-only bridge within 4 hops from ANY of either album's credited
// contributors (verified against apps/web/public/data/pathfinding/graph.v2.json,
// re-checked against v2's multi-source-contributor search specifically --
// Discovery <-> Joshua Tree, this test's pre-v2 negative pair, stopped
// being a real negative case once search started from every credited
// contributor on an album instead of only its primary artist).
test("Behind the Glass reports no connection when the real path doesn't qualify", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Time Out");
  await selectAlbum(page, "b", "Rumours");
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
  await expect(page.locator("[data-connect-result='alternate']")).toBeHidden();
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

// Time Out <-> Rumours has no rhythm-section- or guitar-only bridge within
// 4 hops either (verified against the committed artifact, from any
// credited contributor on either album) -- the same real negative case
// reused across every filtered mode.
test("Rhythm Section and Guitar Paths report no connection for the same real non-matching pair", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Time Out");
  await selectAlbum(page, "b", "Rumours");

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
