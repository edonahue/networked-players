// Player page (Atlas P4): leads with what the person is documented PLAYING;
// non-performance credits sit in a secondary "Also credited" block. Players
// are chosen by rule from the committed contributor index, never named:
//   (a) the first player (by artist id) with a voice/instrument credit in
//       their indexed evidence and at least one record;
//   (b) the first player with records whose indexed evidence has none.

import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { readArtifact, SCAN_ALBUM_CAP } from "./helpers/catalogFacts";
import { stubCoverArt } from "./helpers/coverArt";
import type { Contributor } from "../src/data/contributors";
import { playedPhrase, playerRoles } from "../src/data/playerRecord";

const players = readArtifact<{ contributors: Contributor[] }>(
  "contributors/index.v1.json",
)
  .contributors.slice()
  .sort((a, b) => a.artist_id - b.artist_id);

const withPlay = players.find(
  (c) => c.albums.length > 0 && playerRoles(c).played.length > 0,
);
// Prefer one that also has non-performance credits, so the "Also credited"
// block is exercised.
const withPlayAndAlso =
  players.find(
    (c) =>
      c.albums.length > 0 &&
      playerRoles(c).played.length > 0 &&
      playerRoles(c).also.length > 0,
  ) ?? withPlay;
const withoutPlay = players.find(
  (c) => c.albums.length > 0 && playerRoles(c).played.length === 0,
);
// Axe on a page with hundreds of evidence rows times out (the accessibility
// scan bounds its player by SCAN_ALBUM_CAP for the same reason), so the axe
// run uses the first players of each kind within that bound.
const bounded = (c: Contributor) =>
  c.albums.length > 0 && c.albums.length <= SCAN_ALBUM_CAP;
const axeWithPlay = players.find(
  (c) => bounded(c) && playerRoles(c).played.length > 0,
);
const axeWithoutPlay = players.find(
  (c) => bounded(c) && playerRoles(c).played.length === 0,
);

test.beforeEach(async ({ page }) => {
  await stubCoverArt(page);
});

test("the rule finds a player with and a player without a performance role", () => {
  expect(withPlay, "no player with a performance role").toBeTruthy();
  expect(withoutPlay, "no player without a performance role").toBeTruthy();
});

test("a player with performance roles leads with what they played", async ({
  page,
}) => {
  const player = withPlayAndAlso!;
  const roles = playerRoles(player);
  await page.goto(`/contributors/${player.artist_id}/`);

  await expect(page.getByRole("heading", { level: 1 })).toHaveText(player.name);
  await expect(page.locator("[data-player-summary]")).toHaveText(
    `Documented playing ${playedPhrase(roles.played)}.`,
  );
  // Retired headline and raw identity text are gone.
  // (The evidence tables further down keep their per-credit identity column.)
  const lead = [
    await page.locator(".play-header").innerText(),
    await page.locator("[data-player-recurs]").innerText(),
  ].join("\n");
  expect(lead).not.toContain("Primarily credited for");
  expect(lead).not.toContain("linked identity");
  expect(lead).not.toMatch(/#\d+/);
  expect(await page.locator("body").innerText()).not.toContain(
    "linked identity",
  );

  // Order: summary, then records, then who they recur with, then the
  // secondary "Also credited" block, then evidence.
  const order = await page.evaluate(() => {
    const q = (s: string) => document.querySelector(s);
    const pos = (el: Element | null) =>
      el
        ? Array.from(document.querySelectorAll("*")).indexOf(el)
        : Number.POSITIVE_INFINITY;
    return [
      pos(q("[data-player-summary]")),
      pos(q("[data-player-records]")),
      pos(q("[data-player-recurs]")),
      pos(q("[data-player-also]")),
    ];
  });
  expect(order).toEqual([...order].sort((a, b) => a - b));
  expect(order.every((n) => Number.isFinite(n))).toBe(true);

  const also = page.locator("[data-player-also]");
  await expect(
    also.getByRole("heading", { name: "Also credited" }),
  ).toBeVisible();
  await expect(also).toContainText("do not make a connection");

  // Entry links stay.
  await expect(
    page.locator(
      `a[href='/explore/${player.albums[0]}/?center=${player.artist_id}']`,
    ),
  ).toBeVisible();
  if (player.albums.length > 1) {
    await expect(
      page.locator(
        `a[href='/play/connect/?a=${player.albums[0]}&b=${player.albums[1]}']`,
      ),
    ).toBeVisible();
  }

  // The meta description says what the person did, in plain words.
  const description = await page
    .locator("meta[name='description']")
    .getAttribute("content");
  expect(description).toContain(
    `documented playing ${playedPhrase(roles.played)}`,
  );
});

test("a player with no indexed performance role says so and keeps their credits as evidence", async ({
  page,
}) => {
  const player = withoutPlay!;
  const roles = playerRoles(player);
  await page.goto(`/contributors/${player.artist_id}/`);

  await expect(page.locator("[data-player-summary]")).toHaveText(
    "No voice or instrument credit is indexed for this person yet.",
  );
  await expect(page.locator("[data-player-summary]")).not.toContainText(
    "Documented playing",
  );
  const description = await page
    .locator("meta[name='description']")
    .getAttribute("content");
  expect(description).toContain("No voice or instrument credit is indexed");
  if (roles.also.length > 0) {
    await expect(page.locator("[data-player-also]")).toContainText(
      "do not make a connection",
    );
  }
});

for (const theme of ["dark", "light"] as const) {
  test(`axe: player pages (with and without performance roles), ${theme} theme`, async ({
    page,
  }) => {
    await page.addInitScript(
      (t) => window.localStorage.setItem("networked-players-theme", t),
      theme,
    );
    for (const player of [axeWithPlay!, axeWithoutPlay!]) {
      await page.goto(`/contributors/${player.artist_id}/`);
      await page.waitForLoadState("networkidle");
      const results = await new AxeBuilder({ page }).analyze();
      expect(
        results.violations,
        JSON.stringify(
          results.violations.map((v) => [v.id, v.nodes.map((n) => n.target)]),
        ),
      ).toEqual([]);
    }
  });
}

test.describe("390px", () => {
  test.use({ viewport: { width: 390, height: 844 } });
  test("a player page has no sideways scroll", async ({ page }) => {
    for (const player of [withPlayAndAlso!, withoutPlay!]) {
      await page.goto(`/contributors/${player.artist_id}/`);
      const overflow = await page.evaluate(
        () =>
          document.documentElement.scrollWidth >
          document.documentElement.clientWidth,
      );
      expect(overflow).toBe(false);
    }
  });
});
