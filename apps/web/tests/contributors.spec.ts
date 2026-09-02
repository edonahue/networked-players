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

interface AlbumHopDistanceEntry {
  artist_id: number;
  album_id: string;
  hop_distance: number;
}

async function albumHopDistancesFor(
  request: import("@playwright/test").APIRequestContext,
  artistId: number,
): Promise<AlbumHopDistanceEntry[]> {
  const res = await request.get(
    "/data/contributors/album-hop-distances.v1.json",
  );
  const { entries } = (await res.json()) as {
    entries: AlbumHopDistanceEntry[];
  };
  return entries.filter((e) => e.artist_id === artistId);
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

// Regression guard for a real review finding: an earlier draft only
// flagged hop_distance > 1, leaving 1-hop connections (a real, if close,
// chain -- not a direct credit on that album's own release) rendered
// identically to a direct hop_distance-0 credit. Every non-zero distance,
// including 1, must carry a visible note.
test("a contributor page labels a non-direct album connection with its real hop distance", async ({
  page,
  request,
}) => {
  const res = await request.get(
    "/data/contributors/album-hop-distances.v1.json",
  );
  const { entries } = (await res.json()) as {
    entries: AlbumHopDistanceEntry[];
  };
  // Specifically hop_distance === 1, not just "> 0": that exact boundary is
  // what the reverted-threshold bug missed (a note only appeared for
  // hop_distance > 1), so a test that accepted any positive distance would
  // not have caught it.
  const indirect = entries.find((e) => e.hop_distance === 1);
  if (!indirect) {
    throw new Error(
      "no contributor with a hop_distance === 1 album in the real index",
    );
  }
  const artistEntries = await albumHopDistancesFor(request, indirect.artist_id);

  await page.goto(`/contributors/${indirect.artist_id}/`);
  const card = page.locator(
    `.album-card[data-album-id='${indirect.album_id}']`,
  );
  await expect(card).toBeVisible();
  await expect(card).toContainText(
    `${indirect.hop_distance} documented hop${indirect.hop_distance === 1 ? "" : "s"} away`,
  );

  const direct = artistEntries.find((e) => e.hop_distance === 0);
  if (direct) {
    const directCard = page.locator(
      `.album-card[data-album-id='${direct.album_id}']`,
    );
    await expect(directCard).not.toContainText("documented hop");
  }
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
// built from challenge.v3.json path endpoints, the same set that backs
// every /explore/<album.id>/ static page, so this route always resolves).
test("a contributor page links into the Network Explorer centered on themselves", async ({
  page,
  request,
}) => {
  const contributor = await firstContributor(request);
  await page.goto(`/contributors/${contributor.artist_id}/`);

  const centerAlbumId = contributor.albums[0];
  const exploreLink = page.locator(
    `a[href='/explore/${centerAlbumId}/?center=${contributor.artist_id}']`,
  );
  await expect(exploreLink).toBeVisible();

  await exploreLink.click();
  await page.waitForURL(
    `**/explore/${centerAlbumId}/?center=${contributor.artist_id}`,
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

  // Scoped to the specific "worth a look" paragraph (the one that also
  // links to the neighbor) -- both the contributor's own name and the
  // phrase "different kind of role" also appear elsewhere on the page
  // (the Explore link, the header) since PR 2's role-summary additions.
  const worthALookPara = page.locator(
    `.lede:has(a[href='/contributors/${neighbor.artist_id}/'])`,
  );
  await expect(worthALookPara).toContainText("a different kind of role than");
  await expect(worthALookPara).toContainText(`${contributor.name}'s`);
  await expect(
    worthALookPara.locator(`a[href='/contributors/${neighbor.artist_id}/']`),
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

test("a contributor page shows a visual anchor -- a real cover or the house placeholder", async ({
  page,
  request,
}) => {
  const contributor = await firstContributor(request);
  await page.goto(`/contributors/${contributor.artist_id}/`);

  const cover = page.locator(".play-header__cover");
  const placeholder = page.locator(".play-header__placeholder");
  const coverCount = await cover.count();
  const placeholderCount = await placeholder.count();
  expect(coverCount + placeholderCount).toBe(1);
});

test("a contributor page summarizes its role categories in plain language", async ({
  page,
  request,
}) => {
  const contributor = await firstContributor(request);
  await page.goto(`/contributors/${contributor.artist_id}/`);

  await expect(
    page.getByText("Primarily credited for:", { exact: false }),
  ).toBeVisible();
});

// Every real contributor in the committed index has at least 2 connected
// albums today, so this exercises the real, common case, not an edge case.
test("a contributor page offers to connect two of their own records", async ({
  page,
  request,
}) => {
  const contributor = await firstContributor(request);
  test.skip(
    contributor.albums.length < 2,
    "this contributor has fewer than 2 connected albums in the real index",
  );
  const challengeRes = await request.get("/data/challenge.v3.json");
  const { albums } = (await challengeRes.json()) as {
    albums: { id: string; title: string }[];
  };
  const albumById = new Map(albums.map((a) => [a.id, a]));
  const idA = contributor.albums[0];
  const idB = contributor.albums[1];
  const albumA = albumById.get(idA);
  const albumB = albumById.get(idB);
  if (!albumA || !albumB)
    throw new Error("connected album missing from challenge.v3.json");

  await page.goto(`/contributors/${contributor.artist_id}/`);
  const connectLink = page.locator(
    `a[href='/play/connect/?a=${idA}&b=${idB}']`,
  );
  await expect(connectLink).toBeVisible();

  await connectLink.click();
  await expect(page).toHaveURL(
    new RegExp(`/play/connect/\\?a=${idA}&b=${idB}$`),
  );
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  await expect(
    page.locator('[data-picker="a"] [data-picker-selected]'),
  ).toContainText(albumA.title);
  await expect(
    page.locator('[data-picker="b"] [data-picker-selected]'),
  ).toContainText(albumB.title);
});

test("a contributor page never leaves a zero-connection contributor without a CTA", async ({
  page,
  request,
}) => {
  const res = await request.get("/data/contributors/index.v1.json");
  const { contributors } = (await res.json()) as {
    contributors: ContributorLite[];
  };
  const noAlbums = contributors.find((c) => c.albums.length === 0);
  test.skip(
    !noAlbums,
    "no contributor with zero connected albums exists in the real index today",
  );

  await page.goto(`/contributors/${noAlbums!.artist_id}/`);
  await expect(
    page.getByText("Browse everyone else in the graph", { exact: false }),
  ).toBeVisible();
});

test("a contributor page never leaves a neighbor-less contributor without a CTA", async ({
  page,
  request,
}) => {
  const res = await request.get("/data/contributors/index.v1.json");
  const { contributors } = (await res.json()) as {
    contributors: ContributorLite[];
  };
  const noNeighbors = contributors.find(
    (c) => c.neighboring_contributor_ids.length === 0,
  );
  test.skip(
    !noNeighbors,
    "no contributor with zero neighbors exists in the real index today",
  );

  await page.goto(`/contributors/${noNeighbors!.artist_id}/`);
  await expect(
    page.getByText("Browse the full directory", { exact: false }),
  ).toBeVisible();
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

test.describe("mobile layout", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("a contributor page's new header/CTA modules don't cause sideways scroll on a phone-sized screen", async ({
    page,
    request,
  }) => {
    const contributor = await firstContributor(request);
    await page.goto(`/contributors/${contributor.artist_id}/`);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });
});
