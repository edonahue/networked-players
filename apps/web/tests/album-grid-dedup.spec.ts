// Album universe (ADR 0058 Slice 8 dedup; ADR 0067 + its 2026-09-02
// addendum): /albums/, /explore/, the homepage, per-album static paths, and
// the sitemap all derive their album set from the catalog itself
// (challenge.albums), never from which albums happen to be challenge.v3
// path endpoints. The shared connectedAlbumIds() helper only decides which
// cards carry the honest "No documented path yet" badge. This file asserts
// the real, committed challenge.v3.json artifact produces the full catalog
// count in each of those places, that Explore's cards link into /explore/
// while Albums' cards link into /albums/, and that the badge is honest in
// both directions: absent when every album has a path, present on exactly
// the albums that lack one if a future regeneration ever leaves one out.

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

const connectedIds = new Set(
  challengeData.paths.flatMap((p) => [p.from_album_id, p.to_album_id]),
);
const excludedAlbums = challengeData.albums.filter(
  (a) => !connectedIds.has(a.id),
);
const firstConnectedId = challengeData.paths[0].from_album_id;

test("the real committed challenge artifact reaches every catalog album", () => {
  // The expansion-phase pair-order fix (stratified candidate order +
  // max_paths >= 2 per album) makes this a build guarantee, not a
  // coincidence. If it ever fails, the regeneration was run with an
  // undersized --max-paths or the ordering regressed -- fix the build, do
  // not loosen this.
  expect(connectedIds.size).toBe(challengeData.albums.length);
  expect(excludedAlbums).toHaveLength(0);
});

// Phase 6 PR 6-07: an album with no challenge.v3 path still needs a real
// /albums/ and /explore/ page -- Connect's own endpoint cards link to
// /albums/<id>/ unconditionally for any catalog album a visitor picks.
// Skip-guarded rather than deleted: it resumes being exercised
// automatically if a regeneration ever leaves an album out again.
test("an album without a documented path still has a real /albums/ and /explore/ page", async ({
  page,
}) => {
  const excluded = excludedAlbums[0];
  test.skip(
    excluded === undefined,
    "every catalog album has a documented path in the committed artifact",
  );
  if (!excluded) return;

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

for (const [path, testId] of [
  ["/albums/", undefined],
  ["/explore/", "explore-album-grid"],
] as const) {
  test(`${path} renders the full catalog with an honest per-card badge`, async ({
    page,
  }) => {
    await page.goto(path);
    const grid = testId ? page.locator(`[data-testid='${testId}']`) : page;
    const cards = grid.locator(".album-card");
    await expect(cards).toHaveCount(challengeData.albums.length);
    await expect(cards.first()).toHaveAttribute(
      "href",
      new RegExp(`^${path.replace(/\//g, "\\/")}[^/]+\\/$`),
    );

    const connectedCard = grid.locator(
      `.album-card[href="${path}${firstConnectedId}/"]`,
    );
    await expect(connectedCard).toHaveAttribute("data-album-connected", "true");
    await expect(connectedCard.getByText("No documented path yet")).toHaveCount(
      0,
    );

    // Badge count must equal the number of albums the artifact actually
    // leaves out -- zero today -- never more, never fewer.
    await expect(grid.locator("[data-album-connected='false']")).toHaveCount(
      excludedAlbums.length,
    );
    for (const excluded of excludedAlbums) {
      const excludedCard = grid.locator(
        `.album-card[href="${path}${excluded.id}/"]`,
      );
      await expect(excludedCard).toHaveAttribute(
        "data-album-connected",
        "false",
      );
      await expect(
        excludedCard.getByText("No documented path yet"),
      ).toBeVisible();
    }
  });
}

test("an Explore card and an Albums card for the same album link to different sections", async ({
  page,
}) => {
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

// Phase 6 PR 6-07: per-album /albums/ and /explore/ pages cover the FULL
// catalog (a catalog album is a real, individually reachable
// pathfinding-graph node, and so a valid Connect/Explore destination,
// regardless of challenge.v3 paths). The sitemap lists every real page.
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
