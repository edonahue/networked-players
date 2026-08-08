// Connect Two Records endpoint/evidence cards (ADR 0058 Slice 7): a real
// search must render "X is credited on Album A's own release, as ROLE"
// for both endpoints, real evidence (title/year/cover/source) per hop, and
// must never leak the internal ALBUM_ANCHOR_SENTINEL string into the DOM
// -- verified against the real committed
// apps/web/public/data/pathfinding/graph.v2.json artifact, same real
// Discovery <-> Joshua Tree pair game-connect.spec.ts already uses.

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

  const first = endpoints.first();
  await expect(first).toContainText(/is credited on/i);
  await expect(first).toContainText("Discovery");
  await expect(first).toContainText(/producer|vocals/i);

  const last = endpoints.last();
  await expect(last).toContainText(/is credited on/i);
  await expect(last).toContainText("The Joshua Tree");
  await expect(last).toContainText(/composed by/i);
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
      /co-credited on the same documented release/i,
    );
  }
});
