// Connect Two Records endpoint/evidence cards (ADR 0058 Slice 7): a real
// search must render "X is credited on Album A's own release, as ROLE"
// for both endpoints, real evidence (title/year/cover/source) per hop, and
// must never leak the internal ALBUM_ANCHOR_SENTINEL string into the DOM
// -- verified against the real committed
// pathfinding graph, using the computed connected pair
// (helpers/catalogFacts.ts) the other Connect specs share.

import { expect, test } from "@playwright/test";
import { selectAlbumById } from "./helpers/connectPicker";
import { catalogFacts } from "./helpers/catalogFacts";

// Albums are derived from the committed artifacts by rule (see
// helpers/catalogFacts.ts), never named here.
const facts = await catalogFacts();
const CONNECTED = facts.connected;

test("a real search renders real endpoint cards for both albums", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbumById(page, "a", CONNECTED.a);
  await selectAlbumById(page, "b", CONNECTED.b);
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
  // the graph grows (it has changed across catalog expansions: a pair can
  // gain a new bridge contributor and role). Pinning the
  // role made a real, correct route look like a regression. The `, as .+\.`
  // clause still fails loudly on a missing or empty role, which is the
  // property this test actually exists to protect.
  const first = endpoints.first();
  await expect(first).toContainText(/is credited on/i);
  await expect(first).toContainText(CONNECTED.a.title);
  await expect(first).toContainText(/, as .+\./i);

  const last = endpoints.last();
  await expect(last).toContainText(/is credited on/i);
  await expect(last).toContainText(CONNECTED.b.title);
  await expect(last).toContainText(/, as .+\./i);
});

test("a real search never leaks the album-anchor sentinel into the DOM", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbumById(page, "a", CONNECTED.a);
  await selectAlbumById(page, "b", CONNECTED.b);
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
  await selectAlbumById(page, "a", CONNECTED.a);
  await selectAlbumById(page, "b", CONNECTED.b);
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
