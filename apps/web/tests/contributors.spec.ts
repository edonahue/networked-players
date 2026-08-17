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
  connection_count: number;
  neighboring_contributor_ids: number[];
  interesting_next_step: { artist_id: number; reason: string } | null;
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

// Phase 6 PR 6-10: picked from the real artifact itself (ADR 0060's own
// signal), not hardcoded -- survives a future regeneration. Bounded to a
// small connection_count so the highlighted neighbor is guaranteed to be
// within Explorer's own MAX_NEIGHBORS cap too (shared by the Explorer test
// below).
async function contributorWithInterestingNextStep(
  request: import("@playwright/test").APIRequestContext,
): Promise<{ contributor: ContributorLite; neighbor: ContributorLite }> {
  const res = await request.get("/data/contributors/index.v1.json");
  const { contributors } = (await res.json()) as {
    contributors: ContributorLite[];
  };
  const byId = new Map(contributors.map((c) => [c.artist_id, c]));
  const contributor = contributors.find(
    (c) =>
      c.interesting_next_step && c.connection_count <= 5 && c.albums.length > 0,
  );
  if (!contributor) {
    throw new Error(
      "no contributor with a bounded interesting_next_step in the artifact",
    );
  }
  const neighbor = byId.get(contributor.interesting_next_step!.artist_id);
  if (!neighbor)
    throw new Error("interesting_next_step neighbor missing from the index");
  return { contributor, neighbor };
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

test("a contributor page highlights its interesting_next_step neighbor without hiding the rest", async ({
  page,
  request,
}) => {
  const { contributor, neighbor } =
    await contributorWithInterestingNextStep(request);
  await page.goto(`/contributors/${contributor.artist_id}/`);

  await expect(
    page.getByText(
      `is credited in a different kind of role than ${contributor.name}`,
    ),
  ).toBeVisible();
  await expect(
    page.locator(`.lede a[href='/contributors/${neighbor.artist_id}/']`),
  ).toHaveText(neighbor.name);

  // The full neighbor list stays intact -- every id, including the
  // highlighted one, is still a real card, and the badge decorates rather
  // than replaces it.
  const highlightedCard = page.locator(
    `.contributor-card[href='/contributors/${neighbor.artist_id}/']`,
  );
  await expect(highlightedCard).toBeVisible();
  await expect(highlightedCard.locator(".tag--highlight")).toHaveText(
    "Different role",
  );
  // The highlight decorates one card; the full neighbor list -- every id in
  // neighboring_contributor_ids -- still renders alongside it.
  await expect(page.locator(".contributor-grid .contributor-card")).toHaveCount(
    contributor.neighboring_contributor_ids.length,
  );
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
