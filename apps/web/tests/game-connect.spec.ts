// Connect Two Records (ADR 0051) integration tests against the real
// committed pathfinding graph. "Discovery" (Daft Punk) and "The Joshua
// Tree" (U2) are a real, directly-connected pair in the committed artifact
// (verified against apps/web/public/data/pathfinding/graph.v3.json) --
// picked from the artifact itself, not hardcoded blindly, so this survives
// a future regeneration only if that specific edge remains; if it doesn't,
// this test's failure is itself a useful signal to pick a new real pair.

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import {
  picker,
  pickerResults,
  selectAlbum,
  selectRouteFilter,
} from "./helpers/connectPicker";

/** Flushes the page's task queue past every pending promise continuation
 * spawned by a network response that just resolved -- NOT an arbitrary
 * wait. `page.waitForResponse` resolves once Playwright's protocol layer
 * has the response; the page's own `await fetch(...)` continuation is a
 * separate, slightly later microtask, so a response having arrived does
 * not yet prove the page has finished reacting to it. A double
 * requestAnimationFrame is the standard, deterministic way to wait past
 * at least one full microtask+task cycle: the browser guarantees every
 * queued microtask (including a resolved `fetch()`'s `.then` chain) runs
 * before the FIRST rAF callback, so two are a safety margin against a
 * chain with an extra hop, not a guess at how long anything takes. */
async function flushPendingWork(
  page: import("@playwright/test").Page,
): Promise<void> {
  await page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      }),
  );
}

/** For a "this stale request must never render" assertion, a double-rAF
 * flush isn't a reliable enough window: measured directly (repeated,
 * consistent, not flaky) against a deliberately un-invalidated request, its
 * `route.fulfill()`-released response takes measurably longer than two
 * animation frames to reach the page's own `await fetch(...)` continuation
 * in THIS specific shape (no second real search's own network round trip
 * intervening beforehand to absorb that latency incidentally, unlike the
 * older/newer-search staleness tests above). Actively polls for the BAD
 * outcome (a populated URL) for a bounded, generous window -- 4x the
 * measured gap -- so a broken guard is caught fast and reliably, while a
 * working guard (which never produces that outcome at all) costs exactly
 * one full timeout, the unavoidable price of proving an absence. */
async function waitOutAnyStaleRender(
  page: import("@playwright/test").Page,
): Promise<void> {
  await page
    .waitForFunction(() => window.location.search !== "", null, {
      timeout: 2000,
    })
    .catch(() => {});
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

  // The picker is fully usable by keyboard from that recovered state --
  // the real WAI-ARIA combobox pattern (ADR 0059 Phase 5 PR 4): focus
  // stays IN the input the whole time, ArrowDown moves the active
  // descendant, Enter activates it.
  await input.press("ArrowDown");
  await expect(pickerResults(page, "a").first()).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await input.press("Enter");
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
  // A genuine data-integrity failure gets the same data-phase="error" +
  // assertive-alert pairing Guesser's/Routes' own fetch failures already
  // have -- previously announced identically to an ordinary loading
  // message, on the one polite region.
  await expect(page.locator("[data-testid='connect-stage']")).toHaveAttribute(
    "data-phase",
    "error",
  );
  await expect(page.locator("[data-connect-announce-assertive]")).toContainText(
    /couldn't load the album list/i,
  );

  // Typing again retries the load, and the recovered catalog is applied to
  // the text already in the box. Recovery clears the error phase too --
  // both the structural data-phase attribute AND the assertive region's
  // own text (a real Codex-review finding: clearing data-phase alone left
  // the previous failure's text sitting in the assertive region).
  await pickerA.locator("input").fill("Discovery");
  await expect(pickerA).toHaveAttribute("data-picker-state", "ready");
  await expect(pickerResults(page, "a").first()).toBeVisible();
  expect(attempts).toBe(2);
  await expect(page.locator("[data-testid='connect-stage']")).toHaveAttribute(
    "data-phase",
    "idle",
  );
  await expect(page.locator("[data-connect-announce-assertive]")).toHaveText(
    "",
  );
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

test("a successful search announces the result and moves focus, like Guesser/Routes do", async ({
  page,
}) => {
  // A real gap this test guards against: hiding the polite status region
  // right as results appeared gave a screen-reader user no signal anything
  // happened -- flagship.ts's/routes.ts's own verdict moments both
  // announce AND move focus (verdictHeading.focus()); Connect's equivalent
  // moment did neither.
  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
  await page.locator("[data-connect-search]").click();

  const eyebrow = page.locator("[data-connect-eyebrow]");
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  await expect(eyebrow).toBeFocused();
  await expect(page.locator("[data-connect-announce]")).toHaveText(
    (await eyebrow.textContent())!.trim(),
  );
});

// Phase 6 PR 6-07: each endpoint card's album title links to its own
// /albums/<id>/ page (mirroring PR 6-01's album-page-to-Connect link).
// Both real catalog ids read from the artifact itself, not hardcoded.
test("endpoint cards link back to their own album page", async ({
  page,
  request,
}) => {
  const res = await request.get("/data/catalog/albums.v1.json");
  const { albums } = (await res.json()) as {
    albums: { id: string; title: string }[];
  };
  const discovery = albums.find((a) => a.title === "Discovery");
  const joshuaTree = albums.find((a) => a.title === "The Joshua Tree");
  if (!discovery || !joshuaTree) {
    throw new Error(
      "Discovery / The Joshua Tree missing from the real catalog",
    );
  }

  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
  await page.locator("[data-connect-search]").click();

  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  const endpoints = page.locator("[data-connect-hops] .connect-endpoint");
  await expect(endpoints).toHaveCount(2);
  await expect(
    endpoints.first().locator(`a[href='/albums/${discovery.id}/']`),
  ).toBeVisible();
  await expect(
    endpoints.last().locator(`a[href='/albums/${joshuaTree.id}/']`),
  ).toBeVisible();

  // The link must actually resolve, not just render -- a real regression
  // guard for the 3 real catalog albums that have no challenge.v3 path
  // (and so, before this PR, no /albums/<id>/ page at all).
  await endpoints.first().locator(`a[href='/albums/${discovery.id}/']`).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "Discovery",
  );
});

// Phase 6 PR 6-06: every hop name carries the contributor's own artist_id
// (data-hop-artist-id) regardless of whether that person has a published
// contributor page -- a general property test against the real contributor
// index, not a hardcoded name, so it survives a future regeneration.
test("hop names link to their own contributor page when one is published", async ({
  page,
  request,
}) => {
  const res = await request.get("/data/contributors/index.v1.json");
  const { contributors } = (await res.json()) as {
    contributors: { artist_id: number }[];
  };
  const contributorIds = new Set(contributors.map((c) => c.artist_id));

  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
  await page.locator("[data-connect-search]").click();

  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  const nameEls = page.locator("[data-connect-hops] [data-hop-artist-id]");
  await expect(nameEls.first()).toBeVisible();
  const count = await nameEls.count();
  expect(count).toBeGreaterThan(0);

  let linkedAtLeastOne = false;
  for (let i = 0; i < count; i++) {
    const el = nameEls.nth(i);
    const artistId = Number(await el.getAttribute("data-hop-artist-id"));
    const link = el.locator("a");
    if (contributorIds.has(artistId)) {
      await expect(link).toHaveAttribute("href", `/contributors/${artistId}/`);
      linkedAtLeastOne = true;
    } else {
      await expect(link).toHaveCount(0);
    }
  }
  // A vacuously-true loop (every hop name lacking a page) would prove
  // nothing about the linking behavior itself -- this pair's real data has
  // at least one linked contributor, so this genuinely exercises it.
  expect(linkedAtLeastOne).toBe(true);
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
  // "Why this route?" is a real, closed-by-default disclosure (ADR 0059
  // Phase 5 PR 5) -- expand it before reading the explanation it reveals.
  const why = page.locator("[data-connect-why-primary]");
  await expect(why).toBeVisible();
  await why.locator("summary").click();
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
// apps/web/public/data/pathfinding/graph.v3.json) -- this directly
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
  await page.route("**/data/pathfinding/graph.v4.json", (route) =>
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
  // Same data-phase="error" + assertive-alert pairing as the catalog
  // failure above -- a genuine graph-integrity failure, not an ordinary
  // "no connection found" outcome, which stays on the polite region only.
  await expect(page.locator("[data-testid='connect-stage']")).toHaveAttribute(
    "data-phase",
    "error",
  );
  await expect(page.locator("[data-connect-announce-assertive]")).toContainText(
    /couldn't fetch/i,
  );
});

test("the rest of the page keeps working after a failed search", async ({
  page,
}) => {
  await page.route("**/data/pathfinding/graph.v4.json", (route) =>
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
  await page.route("**/data/pathfinding/graph.v4.json", (route) => {
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

// Behind the Glass (ADR 0053) was RETIRED with the ADR 0068 cutover to
// graph.v3.json. Its two tests here -- a real producer-only connection, and
// an honest "no producer/engineer-only connection" negative -- are gone
// because the mode required BOTH endpoints of every hop to hold a
// producer/engineer credit, and a performer-gated graph contains zero such
// edges (verified directly against the committed graph.v3.json: 0 of 76,646
// directed edges have background-engineering-only roles on both sides). The
// mode could therefore only ever have reported "no path", which is not a
// product feature worth keeping.
//
// What replaces them: the URL-degradation test below proves an old
// `?mode=behind-the-glass` link still lands somewhere real and correctly
// labeled rather than erroring or showing a stale result.

test("an old Behind the Glass URL degrades to a real, correctly-labeled default search", async ({
  page,
}) => {
  // `parseConnectUrlParams` normalizes any unrecognized `mode` to the
  // default, so this is a genuinely fresh unfiltered search -- not an
  // error, and not a stale result carried over from the retired mode.
  await page.goto(
    "/play/connect/?a=master-9313&b=master-19194&mode=behind-the-glass",
  );
  const stage = page.locator("[data-testid='connect-stage']");
  await expect(stage).toBeVisible();

  // No retired chip is offered, and nothing is checked as if it were.
  await expect(
    page.locator("[data-connect-mode-option][data-value='behind-the-glass']"),
  ).toHaveCount(0);
  const checked = page.locator(
    "[data-connect-mode-option][aria-checked='true']",
  );
  if ((await checked.count()) > 0) {
    await expect(checked).not.toHaveAttribute("data-value", "behind-the-glass");
  }
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

// ADR 0059 review finding: the recommended-route engine needs the
// evidence registry BEFORE it can rank the unfiltered search, so its
// fetch was moved to start alongside the graph -- but a role-filtered
// search never ranks and only needs evidence to render an already-found
// route, so unconditionally starting that fetch for every search would be
// a real, wasted network cost on a role-filtered search and on any search
// (filtered or not) that finds no route at all. Verifies the fix rather
// than just the earlier parallel-fetch behavior.
test("a role-filtered search that finds no connection never fetches the evidence registry", async ({
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
  // Rhythm Section since Behind the Glass was retired (ADR 0068). Time Out
  // <-> Rumours is the same real, verified negative pair the filtered-mode
  // tests above already reuse.
  await selectRouteFilter(page, "rhythm-section");
  await page.locator("[data-connect-search]").click();

  await expect(page.locator("[data-connect-status]")).toContainText(
    /no drums\/bass-only connection/i,
  );
  expect(evidenceFetches).toBe(0);
});

// The same mode DOES fetch evidence once a route is actually found --
// deferred, not removed: it's still needed to render the hop's real
// title/year/cover.
test("a role-filtered search that finds a connection fetches evidence only after the route is confirmed", async ({
  page,
}) => {
  let evidenceFetches = 0;
  await page.route("**/data/evidence/release-registry.v1.json", (route) => {
    evidenceFetches++;
    return route.continue();
  });
  await page.goto("/play/connect/");
  // Face Value <-> Talking Book, bridged by Nathan East (Bass/Drums) --
  // the same real, verified positive pair the Rhythm Section test above
  // uses, substituted for the retired Behind the Glass mode (ADR 0068).
  await selectAlbum(page, "a", "Face Value");
  await selectAlbum(page, "b", "Talking Book");
  await selectRouteFilter(page, "rhythm-section");
  await page.locator("[data-connect-search]").click();

  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  expect(evidenceFetches).toBe(1);
});

// The radio group is mutually exclusive by construction -- selecting a
// second filter must deselect the first, never leave two checked.
test("only one route filter can be selected at a time", async ({ page }) => {
  await page.goto("/play/connect/");
  await selectRouteFilter(page, "rhythm-section");
  await selectRouteFilter(page, "guitar-paths");
  await expect(
    page.locator('[data-connect-mode-option][data-value="rhythm-section"]'),
  ).toHaveAttribute("aria-checked", "false");
  await expect(
    page.locator('[data-connect-mode-option][data-value="guitar-paths"]'),
  ).toHaveAttribute("aria-checked", "true");
});

// Slice 4 of the UI design/copy pass: the route filter is now a real
// role="radiogroup" chip tray, unified with Guesser's/Routes' own
// role="radio" pattern instead of a bespoke box of native radios -- same
// keyboard model as flagship.ts's "the chip tray is a keyboard radiogroup
// with roving focus" test.
test("the route filter is a keyboard radiogroup with roving focus", async ({
  page,
}) => {
  await page.goto("/play/connect/");

  const tray = page.locator("[data-connect-mode-group]");
  await expect(tray).toHaveAttribute("role", "radiogroup");
  const chips = tray.locator(".chip");
  // 3, not 4: Behind the Glass was retired with the ADR 0068 cutover.
  await expect(chips).toHaveCount(3);
  await expect(chips.first()).toHaveAttribute("tabindex", "0");
  await expect(chips.first()).toHaveAttribute("aria-checked", "true");

  // Arrow keys select immediately, like a native radio group (WAI-ARIA
  // APG's "automatic activation" pattern, the correct one for a
  // persistent SETTING like this filter -- unlike Guesser's/Routes' own
  // trays, where arrowing to browse a one-shot quiz answer must NOT
  // itself submit it). A real Codex-review finding: this tray replaces a
  // native <input type="radio"> group, whose browser-native arrow-key
  // behavior already selected immediately -- a keyboard user who arrowed
  // to a new filter and clicked Search without an extra Enter/Space would
  // otherwise silently search under the previous filter.
  await chips.first().focus();
  await page.keyboard.press("ArrowRight");
  await expect(chips.nth(1)).toBeFocused();
  await expect(chips.nth(1)).toHaveAttribute("tabindex", "0");
  await expect(chips.first()).toHaveAttribute("tabindex", "-1");
  await expect(chips.first()).toHaveAttribute("aria-checked", "false");
  await expect(chips.nth(1)).toHaveAttribute("aria-checked", "true");

  // A real click (or Enter/Space) also selects, same as ever -- re-picking
  // the already-checked chip via ArrowLeft-then-back is a no-op, matching
  // a native radio group's own `change` event.
  await page.keyboard.press("ArrowLeft");
  await expect(chips.first()).toHaveAttribute("aria-checked", "true");
  await expect(chips.nth(1)).toHaveAttribute("aria-checked", "false");
});

// Request lifecycle (ADR 0059 Phase 5 PR 4): the same generation-counter
// pattern explorerStage.ts already proved for its evidence drawer.
//
// A naive "click search twice quickly" race does NOT by itself prove the
// guard matters here: `loadPreparedGraph`/the evidence-registry loader are
// each a single memoized, URL-keyed promise, so two overlapping searches
// share the exact same in-flight promise and their continuations resume in
// FIFO (invocation) order regardless of the guard -- the newer search's
// continuation was scheduled second and legitimately finishes second too.
// That ordering is NOT guaranteed, though: an UNFILTERED search always
// awaits both the graph AND the evidence registry (two awaits), while a
// ROLE-FILTERED search that finds NO connection returns after `findAlbumRoute`
// fails, needing only the FIRST await (graph) -- it never reaches a second
// one at all. Gate the evidence fetch specifically and this asymmetry lets
// an OLDER, slower (unfiltered) search's completion arrive strictly AFTER a
// NEWER, faster (role-filtered, failed) search has already finished and
// posted its own status -- a real ordering inversion, not an artifact of
// invocation order, which is exactly the case the guard exists for. This
// was verified to actually fail with the guard removed before being
// trusted here (a naive "double-click, assert the second wins" version did
// NOT fail without the guard, for the FIFO reason above -- it would have
// been a false regression pin).
test("an older, still-in-flight search's late completion never overwrites a newer search that already finished faster", async ({
  page,
}) => {
  let releaseEvidence!: () => void;
  const evidenceGate = new Promise<void>((resolve) => {
    releaseEvidence = resolve;
  });
  // `route.fulfill()` with the real committed artifact's own bytes, not
  // `route.continue()`: the latter proxies through to the real preview
  // server and carries enough extra real I/O latency that a deterministic
  // post-release flush (see `flushPendingWork`) isn't reliably long
  // enough to observe the page's own fetch() continuation having run --
  // confirmed by tracing actual DOM state after each before trusting this.
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

  // Older search: unfiltered, needs the (gated) evidence registry to rank
  // at all -- stalls after its graph fetch, before it can ever finish.
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
  await page.locator("[data-connect-search]").click();
  // Honest staged status (ADR 0059 Phase 5 PR 5b): the graph resolves fast
  // (only the evidence registry is gated in these tests), so by the time
  // this check runs, status has already advanced past the initial
  // "Loading the connection graph…" to the second, ranking-specific stage.
  await expect(page.locator("[data-connect-status]")).toHaveText(
    /ranking documented routes/i,
  );

  // Newer search: role-filtered, a real pair with NO drums/bass-only
  // connection -- finishes after just the graph fetch (already resolved,
  // real and unblocked), never touching the gated evidence endpoint.
  await selectAlbum(page, "a", "Time Out");
  await selectAlbum(page, "b", "Rumours");
  await selectRouteFilter(page, "rhythm-section");
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-status]")).toContainText(
    /no drums\/bass-only connection/i,
  );
  await expect(page.locator("[data-connect-results]")).toBeHidden();

  // Only now does the older search's stalled completion arrive. Wait for
  // the real response, not an arbitrary delay -- this guarantees the
  // stale search's continuation has had the chance to run (and, if the
  // guard were broken, to overwrite the DOM) before asserting on it.
  const evidenceResponse = page.waitForResponse(
    "**/data/evidence/release-registry.v1.json",
  );
  releaseEvidence();
  await evidenceResponse;
  await flushPendingWork(page);

  // It must be discarded, not overwrite the newer search's already-final,
  // correct "no connection" state with a stale success.
  await expect(page.locator("[data-connect-status]")).toContainText(
    /no drums\/bass-only connection/i,
  );
  await expect(page.locator("[data-connect-results]")).toBeHidden();
});

// Same ordering inversion, but the older (superseded) search is the one
// restoring from a URL at page load rather than a click -- both entry
// points share the one `runSearch`, so this is the second real ENTRY
// POINT exercising the counter, not the same code path renamed.
test("a URL-restored search superseded by a faster manual search loses honestly", async ({
  page,
}) => {
  let releaseEvidence!: () => void;
  const evidenceGate = new Promise<void>((resolve) => {
    releaseEvidence = resolve;
  });
  // `route.fulfill()` with the real committed artifact's own bytes, not
  // `route.continue()`: the latter proxies through to the real preview
  // server and carries enough extra real I/O latency that a deterministic
  // post-release flush (see `flushPendingWork`) isn't reliably long
  // enough to observe the page's own fetch() continuation having run --
  // confirmed by tracing actual DOM state after each before trusting this.
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

  // The URL-restored search is unfiltered -- Discovery / Joshua Tree --
  // and stalls the same way, waiting on the gated evidence registry.
  await page.goto("/play/connect/?a=master-26647&b=master-64290");
  await expect(
    picker(page, "a").locator("[data-picker-selected]"),
  ).toContainText("Discovery");
  // Honest staged status (ADR 0059 Phase 5 PR 5b): the graph resolves fast
  // (only the evidence registry is gated in these tests), so by the time
  // this check runs, status has already advanced past the initial
  // "Loading the connection graph…" to the second, ranking-specific stage.
  await expect(page.locator("[data-connect-status]")).toHaveText(
    /ranking documented routes/i,
  );

  await selectAlbum(page, "a", "Time Out");
  await selectAlbum(page, "b", "Rumours");
  await selectRouteFilter(page, "rhythm-section");
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-status]")).toContainText(
    /no drums\/bass-only connection/i,
  );

  const evidenceResponse = page.waitForResponse(
    "**/data/evidence/release-registry.v1.json",
  );
  releaseEvidence();
  await evidenceResponse;
  await flushPendingWork(page);

  await expect(page.locator("[data-connect-status]")).toContainText(
    /no drums\/bass-only connection/i,
  );
  await expect(page.locator("[data-connect-results]")).toBeHidden();
});

// A real review finding on PR #115: only Search and Swap were disabled
// while a request was pending -- the picker inputs stayed fully live, so
// editing a selection mid-request WITHOUT clicking Search again never
// advanced `searchGeneration`. The original, now-abandoned request could
// still land and render a route/URL for albums no longer selected. Fixed
// by bumping the generation from the picker's own real-pick handler, not
// only from inside `runSearch`.
test("editing a picker selection while a search is pending invalidates it -- no stale render on late completion", async ({
  page,
}) => {
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
  // Honest staged status (ADR 0059 Phase 5 PR 5b): the graph resolves fast
  // (only the evidence registry is gated in these tests), so by the time
  // this check runs, status has already advanced past the initial
  // "Loading the connection graph…" to the second, ranking-specific stage.
  await expect(page.locator("[data-connect-status]")).toHaveText(
    /ranking documented routes/i,
  );

  // Edit picker A mid-flight without ever clicking Search again.
  await selectAlbum(page, "a", "Time Out");

  const evidenceResponse2 = page.waitForResponse(
    "**/data/evidence/release-registry.v1.json",
  );
  releaseEvidence();
  await evidenceResponse2;
  await waitOutAnyStaleRender(page);

  // The stale request's late completion must never populate results or
  // the URL for the abandoned Discovery/Joshua Tree pair.
  await expect(page.locator("[data-connect-results]")).toBeHidden();
  expect(new URL(page.url()).search).toBe("");
});

// Same gap, the mode radio instead of a picker: changing the role filter
// while a request is pending never used to advance the generation either,
// so a request captured under the OLD filter could still land and render
// for a mode the visitor had since changed away from.
test("changing the role filter while a search is pending invalidates it -- no stale render on late completion", async ({
  page,
}) => {
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
  // Honest staged status (ADR 0059 Phase 5 PR 5b): the graph resolves fast
  // (only the evidence registry is gated in these tests), so by the time
  // this check runs, status has already advanced past the initial
  // "Loading the connection graph…" to the second, ranking-specific stage.
  await expect(page.locator("[data-connect-status]")).toHaveText(
    /ranking documented routes/i,
  );

  // Change the role filter mid-flight without clicking Search again.
  await selectRouteFilter(page, "rhythm-section");

  const evidenceResponse3 = page.waitForResponse(
    "**/data/evidence/release-registry.v1.json",
  );
  releaseEvidence();
  await evidenceResponse3;
  await waitOutAnyStaleRender(page);

  await expect(page.locator("[data-connect-results]")).toBeHidden();
  expect(new URL(page.url()).search).toBe("");
});

// A third real review finding on PR #115: after a completed search, a
// real pick that discards the cached route (`clearLastSearch`) used to
// leave the PREVIOUS pair's route and Copy Link visibly on screen.
// Pressing Swap at that point found no cached route to reverse (a
// correct no-op for the route itself) but left that stale route/link
// untouched while the picker selections had already changed underneath
// it -- two mismatched states shown together.
test("a real pick after a completed search hides the stale result and Copy Link, not just the route cache", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  await expect(page.locator("[data-connect-copy-link]")).toBeVisible();

  await selectAlbum(page, "a", "Time Out");

  await expect(page.locator("[data-connect-results]")).toBeHidden();
  await expect(page.locator("[data-connect-copy-link]")).toBeHidden();

  // Swap with no cached route must just exchange the picker selections,
  // never resurrect the stale Discovery/Joshua Tree route or its link.
  await page.locator("[data-connect-swap]").click();
  await expect(page.locator("[data-connect-results]")).toBeHidden();
  await expect(page.locator("[data-connect-copy-link]")).toBeHidden();
  await expect(
    picker(page, "a").locator("[data-picker-selected]"),
  ).toContainText("Joshua Tree");
  await expect(
    picker(page, "b").locator("[data-picker-selected]"),
  ).toContainText("Time Out");
});
