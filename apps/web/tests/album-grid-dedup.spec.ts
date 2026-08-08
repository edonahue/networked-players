// Album-grid dedup (ADR 0058 Slice 8): /albums/, /explore/, and the
// homepage's featured section all derive their album set from the shared
// connectedCatalogAlbums() helper instead of five independent copies of
// the same filter. This asserts the real, committed challenge.v2.json
// artifact (137 of 140 catalog albums are connected, 3 are not) produces
// the same connected count everywhere, and that Explore's cards link into
// /explore/ while Albums' cards link into /albums/.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

interface ChallengePath {
  from_album_id: string;
  to_album_id: string;
}
interface ChallengeData {
  albums: { id: string }[];
  paths: ChallengePath[];
}

const challengeData: ChallengeData = JSON.parse(
  readFileSync(
    fileURLToPath(new URL("../public/data/challenge.v2.json", import.meta.url)),
    "utf8",
  ),
);

const connectedAlbumCount = new Set(
  challengeData.paths.flatMap((p) => [p.from_album_id, p.to_album_id]),
).size;

test("the real committed catalog has at least one album excluded from the connected set", () => {
  // Not a tautology: this only holds if challenge.v2.json's albums[] and
  // paths[] genuinely diverge in the committed artifact -- if a future
  // regeneration connects every album, this failing is the useful signal
  // to drop the dedup-boundary assertions below, not a bug in the test.
  expect(connectedAlbumCount).toBeLessThan(challengeData.albums.length);
  expect(connectedAlbumCount).toBeGreaterThan(0);
});

test("/albums/ renders exactly the connected album count", async ({ page }) => {
  await page.goto("/albums/");
  await expect(page.locator(".album-card")).toHaveCount(connectedAlbumCount);
});

test("/explore/ renders exactly the same connected album count, linking into /explore/", async ({
  page,
}) => {
  await page.goto("/explore/");
  const cards = page.locator("[data-testid='explore-album-grid'] .album-card");
  await expect(cards).toHaveCount(connectedAlbumCount);
  await expect(cards.first()).toHaveAttribute("href", /^\/explore\/[^/]+\/$/);
});

test("an Explore card and an Albums card for the same album link to different sections", async ({
  page,
}) => {
  const firstConnectedId = challengeData.paths[0].from_album_id;

  await page.goto("/albums/");
  const albumsHref = await page
    .locator(`.album-card[href="/albums/${firstConnectedId}/"]`)
    .getAttribute("href");
  expect(albumsHref).toBe(`/albums/${firstConnectedId}/`);

  await page.goto("/explore/");
  const exploreHref = await page
    .locator(`.album-card[href="/explore/${firstConnectedId}/"]`)
    .getAttribute("href");
  expect(exploreHref).toBe(`/explore/${firstConnectedId}/`);
});

test("the sitemap lists the same number of /albums/ and /explore/ per-album pages", async ({
  request,
}) => {
  const res = await request.get("/sitemap.xml");
  const body = await res.text();
  const albumMatches = body.match(/<loc>[^<]*\/albums\/[^/]+\/<\/loc>/g) ?? [];
  const exploreMatches =
    body.match(/<loc>[^<]*\/explore\/[^/]+\/<\/loc>/g) ?? [];
  expect(albumMatches).toHaveLength(connectedAlbumCount);
  expect(exploreMatches).toHaveLength(connectedAlbumCount);
});
