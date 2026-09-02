// Album-grid dedup (ADR 0058 Slice 8): /explore/, the homepage's featured
// section, and per-album static paths/sitemap all derive their album set
// from the shared connectedCatalogAlbums()/connectedAlbumIds() helpers
// instead of independent copies of the same filter. /albums/ itself no
// longer uses that filter (ADR 0067) -- it shows the full catalog and
// marks unconnected albums honestly instead of hiding them, so it
// INTENTIONALLY diverges from /explore/'s connected-only count below.
// This file asserts the real, committed challenge.v3.json artifact
// produces the right count in each of those distinct places, and that
// Explore's cards link into /explore/ while Albums' cards link into
// /albums/.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

interface ChallengePath {
  from_album_id: string;
  to_album_id: string;
}
interface ChallengeData {
  albums: { id: string; title: string }[];
  paths: ChallengePath[];
}

const challengeData: ChallengeData = JSON.parse(
  readFileSync(
    fileURLToPath(new URL("../public/data/challenge.v3.json", import.meta.url)),
    "utf8",
  ),
);

const connectedAlbumCount = new Set(
  challengeData.paths.flatMap((p) => [p.from_album_id, p.to_album_id]),
).size;

test("the real committed catalog has at least one album excluded from the connected set", () => {
  // Not a tautology: this only holds if challenge.v3.json's albums[] and
  // paths[] genuinely diverge in the committed artifact -- if a future
  // regeneration connects every album, this failing is the useful signal
  // to drop the dedup-boundary assertions below, not a bug in the test.
  expect(connectedAlbumCount).toBeLessThan(challengeData.albums.length);
  expect(connectedAlbumCount).toBeGreaterThan(0);
});

// Phase 6 PR 6-07: an album excluded from the "connected" set (no
// challenge.v3 path) still needs a real /albums/ and /explore/ page --
// Connect's own endpoint cards link to /albums/<id>/ unconditionally for
// any catalog album a visitor picks, including these.
test("an album excluded from the connected set still has a real /albums/ and /explore/ page", async ({
  page,
}) => {
  const connectedIds = new Set(
    challengeData.paths.flatMap((p) => [p.from_album_id, p.to_album_id]),
  );
  const excluded = challengeData.albums.find((a) => !connectedIds.has(a.id));
  if (!excluded)
    throw new Error("no excluded album in the real committed catalog");

  const albumRes = await page.goto(`/albums/${excluded.id}/`);
  expect(albumRes?.status()).toBe(200);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(
    page.getByText(
      `No documented connection is indexed from ${excluded.title} yet.`,
      {
        exact: false,
      },
    ),
  ).toBeVisible();
  // The Explore cross-link (PR 6-02) renders unconditionally, so it must
  // point somewhere real, not a page that doesn't exist.
  await expect(
    page.locator(`.play-from-here a[href='/explore/${excluded.id}/']`),
  ).toBeVisible();

  const exploreRes = await page.goto(`/explore/${excluded.id}/`);
  expect(exploreRes?.status()).toBe(200);
  await expect(
    page.locator("[data-explorer-nodes] .explorer-node").first(),
  ).toBeVisible({ timeout: 15000 });
});

test("/albums/ renders the full catalog, marking unconnected albums honestly", async ({
  page,
}) => {
  const connectedIds = new Set(
    challengeData.paths.flatMap((p) => [p.from_album_id, p.to_album_id]),
  );
  const excluded = challengeData.albums.find((a) => !connectedIds.has(a.id));
  if (!excluded)
    throw new Error("no excluded album in the real committed catalog");
  const connectedId = challengeData.paths[0].from_album_id;

  await page.goto("/albums/");
  await expect(page.locator(".album-card")).toHaveCount(
    challengeData.albums.length,
  );

  const excludedCard = page.locator(
    `.album-card[href="/albums/${excluded.id}/"]`,
  );
  await expect(excludedCard).toHaveAttribute("data-album-connected", "false");
  await expect(excludedCard.getByText("No documented path yet")).toBeVisible();

  const connectedCard = page.locator(
    `.album-card[href="/albums/${connectedId}/"]`,
  );
  await expect(connectedCard).toHaveAttribute("data-album-connected", "true");
  await expect(connectedCard.getByText("No documented path yet")).toHaveCount(
    0,
  );
});

test("/explore/ renders exactly the connected album count, linking into /explore/", async ({
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

// Phase 6 PR 6-07: per-album /albums/ and /explore/ pages were widened to
// the FULL catalog (getStaticPaths no longer filters to connectedAlbumCount
// -- a catalog album can be a real, individually reachable pathfinding-graph
// node, and so a valid Connect/Explore destination, without ever being a
// challenge.v3 path endpoint). /explore/'s GRID stays at connectedAlbumCount
// on purpose (ADR 0067: exploring from a disconnected node isn't a
// meaningful entry into that experience); /albums/'s grid does not (ADR
// 0067 flipped that for the shelf specifically). The sitemap lists every
// real page that exists, which is the full catalog either way.
test("the sitemap lists the same number of /albums/ and /explore/ per-album pages", async ({
  request,
}) => {
  const res = await request.get("/sitemap.xml");
  const body = await res.text();
  const albumMatches = body.match(/<loc>[^<]*\/albums\/[^/]+\/<\/loc>/g) ?? [];
  const exploreMatches =
    body.match(/<loc>[^<]*\/explore\/[^/]+\/<\/loc>/g) ?? [];
  expect(albumMatches).toHaveLength(challengeData.albums.length);
  expect(exploreMatches).toHaveLength(challengeData.albums.length);
});
