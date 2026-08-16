// Phase 2 Slice C: the first per-person page (ADR 0048). The contributor
// index is real, committed data -- pick an entry from the artifact itself
// rather than hardcoding an id, so this test survives a future regeneration.

import { expect, test } from "@playwright/test";
import { pickBoundedConnectedAlbum } from "./helpers/challengeAlbums";
import { stubCoverArt } from "./helpers/coverArt";

interface ContributorLite {
  artist_id: number;
  name: string;
  role_categories: string[];
  albums: string[];
}

async function firstContributor(
  request: import("@playwright/test").APIRequestContext,
): Promise<ContributorLite> {
  const res = await request.get("/data/contributors/index.v1.json");
  const { contributors } = (await res.json()) as {
    contributors: ContributorLite[];
  };
  const withAlbum = contributors.find((c) => c.albums.length > 0);
  if (!withAlbum)
    throw new Error("no contributor with an associated album in the artifact");
  return withAlbum;
}

test("a contributor page renders name, role chips, albums, and evidence", async ({
  page,
  request,
}) => {
  const contributor = await firstContributor(request);
  await page.goto(`/contributors/${contributor.artist_id}/`);

  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    contributor.name,
  );
  await expect(page.locator(".album-card").first()).toBeVisible();
  await expect(page.locator(".evidence-card").first()).toBeVisible();
});

test("an album page links to a contributor page that resolves", async ({
  page,
  request,
}) => {
  const { album } = await pickBoundedConnectedAlbum(request);
  await stubCoverArt(page);

  await page.goto(`/albums/${album.id}/`);
  const contributorLink = page.locator("a.contributor-card").first();
  await expect(contributorLink).toBeVisible();
  const href = await contributorLink.getAttribute("href");
  expect(href).toMatch(/^\/contributors\/\d+\/$/);

  await contributorLink.click();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
});

// Phase 6 PR 6-04: a contributor page links into the Network Explorer
// centered on that contributor specifically -- routed through the first
// of their own connected albums (contributor_index.py's `albums` field is
// built from challenge.v2.json path endpoints, the same set that backs
// every /explore/<album.id>/ static page, so this route always resolves).
test("a contributor page links into the Network Explorer centered on themselves", async ({
  page,
  request,
}) => {
  const contributor = await firstContributor(request);
  await page.goto(`/contributors/${contributor.artist_id}/`);

  const exploreLink = page.locator(
    `a[href='/explore/${contributor.albums[0]}/?center=${contributor.artist_id}']`,
  );
  await expect(exploreLink).toBeVisible();

  await exploreLink.click();
  await page.waitForURL(
    `**/explore/${contributor.albums[0]}/?center=${contributor.artist_id}`,
  );
  await expect(
    page.locator("[data-explorer-nodes] .explorer-node[data-is-center='true']"),
  ).toHaveAttribute("data-artist-id", String(contributor.artist_id), {
    timeout: 15000,
  });
});

test("an unknown contributor id 404s gracefully", async ({ page }) => {
  const response = await page.goto("/contributors/999999999999/");
  expect(response?.status()).toBe(404);
});

test("sitemap includes contributor pages", async ({ request }) => {
  const contributor = await firstContributor(request);
  const res = await request.get("/sitemap.xml");
  const body = await res.text();
  expect(body).toContain(`/contributors/${contributor.artist_id}/`);
});
