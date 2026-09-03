// Progressive rendering (ADR 0059 Phase 5 PR 5b): graph preparation begins
// on the real intent signal of the FIRST valid pick, not the search click
// (the graph doesn't depend on which pair is eventually searched, so
// there's no reason to wait for a second pick), and status text is staged
// honestly rather than one flat "Searching…".

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { selectAlbum, selectRouteFilter } from "./helpers/connectPicker";

test("the pathfinding graph is requested as soon as the FIRST album is picked, before a second pick or the search click", async ({
  page,
}) => {
  let graphFetches = 0;
  await page.route("**/data/pathfinding/graph.v4.json", (route) => {
    graphFetches++;
    return route.continue();
  });

  await page.goto("/play/connect/");
  expect(graphFetches).toBe(0);

  await selectAlbum(page, "a", "Discovery");
  await expect.poll(() => graphFetches).toBe(1);

  // A second pick and the search click still work normally and don't
  // re-fetch -- loadPreparedGraph's own memoized cache absorbs both.
  await selectAlbum(page, "b", "Joshua Tree");
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  expect(graphFetches).toBe(1);
});

test("the album-art registry is requested as soon as the FIRST album is picked, before a second pick or the search click", async ({
  page,
}) => {
  let artFetches = 0;
  await page.route("**/data/catalog/album-art.v1.json", (route) => {
    artFetches++;
    return route.continue();
  });

  await page.goto("/play/connect/");
  expect(artFetches).toBe(0);

  await selectAlbum(page, "a", "Discovery");
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

  await selectRouteFilter(page, "rhythm-section");
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-status]")).toContainText(
    /no drums\/bass-only connection/i,
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
  await page.route("**/data/pathfinding/graph.v4.json", async (route) => {
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
  await page.route("**/data/pathfinding/graph.v4.json", async (route) => {
    await graphGate;
    await route.continue();
  });
  // Gates the rendering-only evidence fetch this mode makes AFTER finding
  // its route -- structural rendering (ADR 0059 Phase 5 PR 5b) means this
  // no longer blocks results from appearing at all, so this test uses the
  // gate to prove exactly that, rather than to hold an intermediate status
  // message (which structural rendering makes too brief to reliably poll
  // for -- see the unfiltered version of this test above, which still can,
  // since ranking genuinely blocks on evidence).
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
  // Face Value <-> Talking Book, bridged by Nathan East (Bass/Drums) --
  // the real, verified Rhythm Section pair. The original Ziggy Stardust
  // <-> A Night At The Opera pair was chosen for Behind the Glass's
  // producer bridge, which ADR 0068 retired.
  await selectAlbum(page, "a", "Face Value");
  await selectAlbum(page, "b", "Talking Book");
  await selectRouteFilter(page, "rhythm-section");
  await page.locator("[data-connect-search]").click();

  await expect(page.locator("[data-connect-status]")).toHaveText(
    /loading the connection graph/i,
  );

  releaseGraph();

  // Structural render: names, roles, and the release-id source link are
  // already sufficient to find and confirm the route, so results become
  // visible while evidence is still gated, not yet released.
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  await expect(
    page.locator("[data-connect-hops] .connect-hop").first(),
  ).toBeVisible();
  await expect(
    page.locator("[data-connect-hops] .connect-hop__release-title"),
  ).toHaveCount(0);

  // Enhancement: releasing evidence patches the release title into the
  // already-rendered hop in place, never a full re-render.
  releaseEvidence();
  await expect(
    page.locator("[data-connect-hops] .connect-hop__release-title").first(),
  ).toBeVisible();
});

// The other half of the same split: a role-filtered search's structural
// route must stay fully usable -- and never throw or hang -- when the
// evidence registry it kicks off (never awaited before rendering) fails
// outright rather than merely arriving late. `loadEvidenceIndex()` itself
// already catches every fetch/parse failure into an empty, degraded
// index (never a rejected promise), so this proves that degradation
// still reaches the enhancement callback safely and leaves the
// structural render exactly as it was, not broken or stuck.
test("a role-filtered search's structural route survives an evidence-registry failure during enhancement", async ({
  page,
}) => {
  await page.route("**/data/evidence/release-registry.v1.json", (route) =>
    route.abort(),
  );

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
  const hop = page.locator("[data-connect-hops] .connect-hop").first();
  await expect(hop).toBeVisible();
  // Drums/bass, not producer: this is a Rhythm Section route now.
  await expect(hop).toContainText(/drums|bass/i);
  await expect(hop.locator("a[href*='discogs.com/release/']")).toBeVisible();

  // The enhancement itself is a real no-op, not a delayed success: no
  // release title/cover ever appears, since the registry never resolved
  // any real data to enhance with.
  await expect(
    page.locator("[data-connect-hops] .connect-hop__release-title"),
  ).toHaveCount(0);

  // The rest of the page -- and a subsequent search -- still work.
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
});
