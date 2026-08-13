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
