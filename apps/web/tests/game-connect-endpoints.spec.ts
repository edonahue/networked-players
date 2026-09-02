// Connect Two Records endpoint/evidence cards (ADR 0058 Slice 7): a real
// search must render "X is credited on Album A's own release, as ROLE"
// for both endpoints, real evidence (title/year/cover/source) per hop, and
// must never leak the internal ALBUM_ANCHOR_SENTINEL string into the DOM
// -- verified against the real committed
// apps/web/public/data/pathfinding/graph.v3.json artifact, same real
// Discovery <-> Joshua Tree pair game-connect.spec.ts already uses.
//
// The endpoint-A role text changed with ADR 0059 (Phase 5 PR 3): the
// recommended-route engine ranks the Discovery side's art-director bridge
// (Alex And Martin, "Design Concept, Art Direction") above the old plain-
// BFS pick through Daft Punk, because that bridge's only evidence is the
// diagnostic pair's own bootleg mashup release. Still a real, documented
// co-credit endpoint -- packaging/business credits are not performer
// credits, but they are exactly as real as a producer credit.

import { expect, test } from "@playwright/test";
import { selectAlbum } from "./helpers/connectPicker";

test("a real search renders real endpoint cards for both albums", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
  await page.locator("[data-connect-search]").click();

  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });

  const endpoints = page.locator("[data-connect-hops] .connect-endpoint");
  await expect(endpoints).toHaveCount(2);

  // Assert the endpoint card's SHAPE -- "<person> is credited on <album>'s
  // own release, as <real role text>." -- rather than one specific
  // contributor's role. Which contributor bridges a pair depends on which
  // equally-valid route the ranker picks, and that legitimately changes as
  // the graph grows (it did on the 140 -> 179 expansion: this pair now
  // routes via George Duke's "Written-By, Performer" instead). Pinning the
  // role made a real, correct route look like a regression. The `, as .+\.`
  // clause still fails loudly on a missing or empty role, which is the
  // property this test actually exists to protect.
  const first = endpoints.first();
  await expect(first).toContainText(/is credited on/i);
  await expect(first).toContainText("Discovery");
  await expect(first).toContainText(/, as .+\./i);

  const last = endpoints.last();
  await expect(last).toContainText(/is credited on/i);
  await expect(last).toContainText("The Joshua Tree");
  await expect(last).toContainText(/, as .+\./i);
});

test("a real search never leaks the album-anchor sentinel into the DOM", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
  await page.locator("[data-connect-search]").click();

  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  await expect(page.locator("[data-connect-results]")).not.toContainText(
    "__np_album_anchor__",
  );
});

test("a real search renders real evidence cards with title, source link, and no bare release-id-only hop", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
  await page.locator("[data-connect-search]").click();

  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });

  const hops = page.locator("[data-connect-hops] .connect-hop");
  await expect(hops.first()).toBeVisible();
  const hopCount = await hops.count();
  expect(hopCount).toBeGreaterThan(0);

  for (let i = 0; i < hopCount; i++) {
    const hop = hops.nth(i);
    await expect(hop.locator("a[href*='discogs.com/release/']")).toBeVisible();
    // Not a bare "Release #12345 on Discogs" link -- co-credit prose must
    // also be present (the pre-v2 rendering had only the bare link).
    await expect(hop).toContainText(
      /documented performing on the same release/i,
    );
  }
});
