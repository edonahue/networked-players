// Guard (Atlas P4): internal jargon that the public copy pass retired must not
// come back. This scans the RENDERED text of a representative set of routes
// (after scripts have run), not source files. Routes that need a record or a
// player use the first catalog album and first indexed player by id.

import { expect, test } from "@playwright/test";
import { catalogAlbums, readArtifact } from "./helpers/catalogFacts";

const RETIRED = [
  "linked identity",
  "linked identities",
  "bounded view",
  "bounded neighborhood",
  "pre-performer-model",
  "primarily credited for",
  "credit graph",
  "credit-graph",
  "credit network",
  "not yet indexed",
  "synthetic universe",
];

const firstPlayer = readArtifact<{ contributors: { artist_id: number }[] }>(
  "contributors/index.v1.json",
).contributors.reduce((a, b) => (a.artist_id <= b.artist_id ? a : b));
const album = catalogAlbums[0];

const ROUTES = [
  "/",
  "/about/",
  "/play/",
  "/play/connection/?motion=off",
  "/play/daily/?motion=off",
  "/play/routes/?motion=off",
  "/play/connect/",
  "/albums/",
  `/albums/${album.id}/`,
  "/explore/",
  `/explore/${album.id}/`,
  "/contributors/",
  `/contributors/${firstPlayer.artist_id}/`,
  "/cohorts/",
  "/404.html",
];

for (const route of ROUTES) {
  test(`no retired phrase in the rendered text of ${route.replace(/[0-9a-z-]{6,}/g, "…")}`, async ({
    page,
  }) => {
    await page.goto(route);
    await page.waitForLoadState("networkidle");
    const text = (await page.locator("body").innerText()).toLowerCase();
    const description = (
      (await page
        .locator("meta[name='description']")
        .first()
        .getAttribute("content")) ?? ""
    ).toLowerCase();
    for (const phrase of RETIRED) {
      expect(text, `visible text contains "${phrase}"`).not.toContain(phrase);
      expect(
        description,
        `meta description contains "${phrase}"`,
      ).not.toContain(phrase);
    }
  });
}
