import { expect, test, type APIRequestContext } from "@playwright/test";
import {
  pickBoundedConnectedAlbum,
  pickConnectedAlbumWithArt,
} from "./helpers/challengeAlbums";
import { stubCoverArt } from "./helpers/coverArt";
import {
  buildAlbumIndex,
  buildArtistIndex,
  findAlbumRoute,
  type PathfindingGraph,
} from "../src/game/pathfindingGraph";
import { behindTheGlassEdgeFilter } from "../src/game/roleTaxonomy";

// Shared by the about-page and llms.txt regression tests below: both quote
// the same real, current catalog/round counts, and both were caught stating
// stale hardcoded numbers ("140 studio albums, 250 artists...") after the
// Phase 7 catalog expansion to 179 albums.
async function realCatalogStats(request: APIRequestContext) {
  const challenge = await (await request.get("/data/challenge.v2.json")).json();
  const manifest = await (
    await request.get("/data/game/daily-manifest.v1.json")
  ).json();
  const newestGeneration = manifest.generations.at(-1);
  const rounds = (await (await request.get(newestGeneration.rounds_url)).json())
    .rounds as { kind: string }[];
  return {
    studioAlbumCount: challenge.albums.length as number,
    artistCount: challenge.artists.length as number,
    documentedConnectionCount: challenge.paths.length as number,
    oneHopRoundCount: rounds.filter((r) => r.kind === "one_hop").length,
    twoHopRoundCount: rounds.filter((r) => r.kind === "two_hop").length,
  };
}

test("homepage's hardcoded Behind the Glass editorial pick still resolves a real producer-only route", async ({
  request,
}) => {
  // index.astro's "An editorial pick" paragraph hardcodes Ziggy Stardust
  // (master-1561) / A Night At The Opera (master-5863) as a real Behind the
  // Glass example -- unlike featuredPath just above it in that file (picked
  // deterministically from challenge.paths[0]), this specific pair is prose,
  // not derived from the artifact. It happens to still be true after the
  // Phase 7 catalog expansion (verified directly against the real published
  // graph.v2.json below), but nothing catches it silently going false on a
  // future expansion the way about.json's stale counts did -- this test is
  // that catch. If this ever fails, either the pair no longer has a real
  // producer-only route (fix the copy) or the album ids no longer exist in
  // the catalog (same).
  const graph = (await (
    await request.get("/data/pathfinding/graph.v2.json")
  ).json()) as PathfindingGraph;
  const artistIndex = buildArtistIndex(graph);
  const albumIndex = buildAlbumIndex(graph);
  const result = findAlbumRoute(
    graph,
    artistIndex,
    albumIndex,
    "master-1561",
    "master-5863",
    4,
    behindTheGlassEdgeFilter,
  );
  expect(result.ok).toBe(true);
});

test("home renders hero, nav, and the album grid", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "Explore the hidden network",
  );
  await expect(
    page.getByRole("link", { name: "Browse the albums" }).first(),
  ).toBeVisible();
  await expect(page.locator(".album-card").first()).toBeVisible();
});

test("about page renders", async ({ page }) => {
  await page.goto("/about/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
});

test("about page's stats paragraph quotes the real, current artifact counts", async ({
  page,
  request,
}) => {
  // Regression test: these numbers were hardcoded at "140 studio albums, 250
  // artists, 300 documented connections" and left stale across the Phase 7
  // catalog expansion to 179 albums. about.astro now derives them from the
  // real artifacts at build time -- this proves the RENDERED page, not just
  // the derivation logic, actually reflects whatever is currently published.
  const stats = await realCatalogStats(request);

  await page.goto("/about/");
  // "N studio albums" appears in both the stats paragraph and the following
  // game paragraph ("...those N studio albums..."); .first() is the one
  // that also carries the artist/connection counts.
  const statsParagraph = page
    .getByText(`${stats.studioAlbumCount} studio albums`)
    .first();
  await expect(statsParagraph).toContainText(`${stats.artistCount} artists`);
  await expect(statsParagraph).toContainText(
    `${stats.documentedConnectionCount} documented connections`,
  );
  await expect(
    page.getByText(
      `${stats.oneHopRoundCount} one-hop and ${stats.twoHopRoundCount} two-hop rounds`,
    ),
  ).toBeVisible();
});

test("llms.txt quotes the real, current catalog counts and never re-states the old synthetic framing", async ({
  request,
}) => {
  // Regression test: public/llms.txt used to describe a much earlier
  // project state ("no public API or full public catalog," the album
  // experience "still uses a small, versioned, synthetic static dataset")
  // that was false the moment the real CC0-dump catalog shipped. It is now
  // generated (llms.txt.ts) from the same real counts as the about page.
  const stats = await realCatalogStats(request);
  const res = await request.get("/llms.txt");
  expect(res.headers()["content-type"]).toContain("text/plain");
  const body = await res.text();

  expect(body).toContain(
    `${stats.studioAlbumCount} studio albums, ${stats.artistCount} artists, ${stats.documentedConnectionCount} documented connections`,
  );
  expect(body).toContain(
    `${stats.oneHopRoundCount} one-hop and ${stats.twoHopRoundCount} two-hop rounds`,
  );
  expect(body.toLowerCase()).not.toContain("synthetic");
  expect(body).not.toContain("no public API");
});

test("demo renders a path with evidence and switches paths", async ({
  page,
  request,
}) => {
  // Path labels are real, curated Discogs data and change whenever the artifact is
  // regenerated -- read them from the artifact itself rather than hardcoding names.
  const res = await request.get("/data/challenge.v1.json");
  const { paths } = await res.json();
  test.skip(paths.length < 2, "need at least two paths to test switching");

  await page.goto("/demo/");
  // First path visible by default with an evidence table.
  await expect(page.locator(".path-card:not([hidden])")).toHaveCount(1);
  await expect(
    page.locator(".path-card:not([hidden]) .evidence table").first(),
  ).toBeVisible();

  // Switch to another path via the picker.
  const secondPath = paths[1];
  await page.getByRole("button", { name: secondPath.label }).click();
  const visibleCard = page.locator(".path-card:not([hidden])");
  await expect(visibleCard).toHaveCount(1);
  await expect(visibleCard).toHaveAttribute("data-path-id", secondPath.id);
});

test("theme toggle persists", async ({ page }) => {
  await page.goto("/");
  const html = page.locator("html");
  await expect(html).toHaveAttribute("data-theme", "dark");
  await page.locator("[data-theme-toggle]").click();
  await expect(html).toHaveAttribute("data-theme", "light");
  await page.reload();
  await expect(html).toHaveAttribute("data-theme", "light");
});

test("static demo artifact is reachable", async ({ request }) => {
  const res = await request.get("/data/challenge.v1.json");
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.schema_version).toBe(1);
  expect(Array.isArray(body.paths)).toBe(true);
});

test("static challenge.v2 artifact is reachable", async ({ request }) => {
  const res = await request.get("/data/challenge.v2.json");
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.schema_version).toBe(2);
  expect(Array.isArray(body.albums)).toBe(true);
  expect(Array.isArray(body.paths)).toBe(true);
});

test("an album page renders mode controls and reveals evidence", async ({
  page,
  request,
}) => {
  // Cover art is optional product data, resolved from a wholly separate
  // artifact (public/data/catalog/album-art.v1.json) with its own
  // presence/version validation -- nothing ties "fewest documented paths"
  // (what this helper picks for) to "has registry art". A regenerated
  // artifact could legitimately leave the bounded album without art, in
  // which case the page intentionally renders its placeholder -- this test
  // stays art-agnostic (asserts the header art slot rendered SOMETHING,
  // real cover or placeholder, not which branch). The real hotlink contract
  // has its own dedicated, art-guaranteed test below.
  const { album, pathCount } = await pickBoundedConnectedAlbum(request);
  await stubCoverArt(page);

  await page.goto(`/albums/${album.id}/`);
  await expect(
    page.locator(".play-header__cover, .play-header__placeholder"),
  ).toBeVisible();

  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    album.title,
  );
  await expect(
    page.getByRole("button", { name: "Find the connection" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Reveal every path" }),
  ).toBeVisible();

  // Evidence starts hidden (guess mode); revealing one path shows its evidence table.
  await expect(page.locator(".evidence-card:not([hidden])")).toHaveCount(0);
  const firstReveal = page.locator("[data-reveal-button]").first();
  await expect(firstReveal).toHaveText("Reveal");
  await expect(firstReveal).toHaveAttribute("aria-expanded", "false");
  const controls = await firstReveal.getAttribute("aria-controls");
  if (!controls) throw new Error("Reveal button is missing aria-controls");
  await expect(page.locator(`#${controls}`)).toBeHidden();

  await firstReveal.click();
  await expect(firstReveal).toHaveText("Hide");
  await expect(firstReveal).toHaveAttribute("aria-expanded", "true");
  await expect(
    page.locator(".evidence-card:not([hidden]) .evidence table").first(),
  ).toBeVisible();
  await expect(page.locator(`#${controls}`)).toBeVisible();

  await firstReveal.click();
  await expect(firstReveal).toHaveText("Reveal");
  await expect(firstReveal).toHaveAttribute("aria-expanded", "false");
  await expect(page.locator(`#${controls}`)).toBeHidden();

  // "Reveal every path" unhides every evidence card on the page. Compared
  // against the artifact-derived path count rather than a number read back
  // off the same page, so this is an independent expectation.
  await expect(page.locator("[data-play-path]")).toHaveCount(pathCount);
  await page.getByRole("button", { name: "Reveal every path" }).click();
  await expect(page.locator(".evidence-card:not([hidden])")).toHaveCount(
    pathCount,
  );
  await expect(
    page.getByRole("button", { name: "Hide" }).first(),
  ).toHaveAttribute("aria-expanded", "true");

  await page.getByRole("button", { name: "Find the connection" }).click();
  await expect(page.locator(".evidence-card:not([hidden])")).toHaveCount(0);
  await expect(page.locator("[data-reveal-button]").first()).toHaveAttribute(
    "aria-expanded",
    "false",
  );

  // Plan §12.7: minimal contributor cards and the play-from-here cross-link.
  await expect(page.locator(".contributor-card").first()).toBeVisible();
  await expect(
    page.locator(".play-from-here a[href='/play/connection/']"),
  ).toBeVisible();
});

// Phase 6 PR 6-02: every album page links directly into the Network
// Explorer, centered on the album's own artist -- `/explore/<album.id>/`
// already exists as a static page for every connected album (same
// connectedCatalogAlbums set backs both routes), so this is a pure
// cross-link with no new URL-state contract.
test("an album page links directly into the Network Explorer", async ({
  page,
  request,
}) => {
  const { album } = await pickBoundedConnectedAlbum(request);
  await stubCoverArt(page);

  await page.goto(`/albums/${album.id}/`);
  const exploreLink = page.locator(
    `.play-from-here a[href='/explore/${album.id}/']`,
  );
  await expect(exploreLink).toBeVisible();

  await exploreLink.click();
  await page.waitForURL(`**/explore/${album.id}/`);
  await expect(page.locator("[data-testid='explorer-stage']")).toBeVisible();
});

// Phase "make it fun to wander": "nearby in the credit network" is a real,
// build-time join over the already-published contributor index (this
// album's own contributors' neighboring_contributor_ids, then THOSE
// neighbors' own albums) -- not a new artifact. 137 of 140 real catalog
// albums have at least one such suggestion today.
test("an album page surfaces nearby records via shared contributors", async ({
  page,
  request,
}) => {
  const { album } = await pickBoundedConnectedAlbum(request);
  await stubCoverArt(page);

  await page.goto(`/albums/${album.id}/`);
  const nearbySection = page.locator("section[aria-label='Nearby records']");
  test.skip(
    (await nearbySection.count()) === 0,
    "this album has no nearby-record suggestion in the real index today",
  );

  await expect(
    nearbySection.getByText("Nearby in the credit network"),
  ).toBeVisible();
  // Honest framing, not a similarity claim.
  await expect(nearbySection).toContainText(
    "Connected through shared contributors",
  );
  await expect(nearbySection.locator(".album-card").first()).toBeVisible();
});

// The 3 real catalog albums with zero documented challenge.v2 paths
// (Phase 6 PR 6-07 widened getStaticPaths to cover them) used to be a
// silent, CTA-less dead end.
test("an album with zero documented connections still offers a real way onward", async ({
  page,
  request,
}) => {
  const res = await request.get("/data/challenge.v2.json");
  const { albums, paths } = (await res.json()) as {
    albums: { id: string; title: string }[];
    paths: { from_album_id: string; to_album_id: string }[];
  };
  const connectedIds = new Set(
    paths.flatMap((p) => [p.from_album_id, p.to_album_id]),
  );
  const zeroConnection = albums.find((a) => !connectedIds.has(a.id));
  if (!zeroConnection)
    throw new Error("no zero-connection album in the real catalog artifact");

  await stubCoverArt(page);
  await page.goto(`/albums/${zeroConnection.id}/`);
  // The empty-state message and the "Play from here" footer both link to
  // Explore -- deliberate, harmless redundancy (top-of-page and
  // bottom-of-page CTAs to the same real destination), so scope to the
  // first occurrence rather than asserting a single match.
  const exploreLink = page
    .locator(`a[href='/explore/${zeroConnection.id}/']`)
    .first();
  await expect(exploreLink).toBeVisible();
  const connectLink = page
    .locator(`a[href='/play/connect/?a=${zeroConnection.id}']`)
    .first();
  await expect(connectLink).toBeVisible();

  await connectLink.click();
  await page.waitForURL(`**/play/connect/?a=${zeroConnection.id}`);
  await expect(
    page.locator("[data-picker='a'] [data-picker-selected]"),
  ).toContainText(zeroConnection.title);
  // No search runs -- there's no second record chosen yet.
  await expect(page.locator("[data-connect-results]")).toBeHidden();
});

// No real catalog album currently has a non-indexed contributor (every
// artist tied to a documented path already clears the index's own
// inclusion rule) -- skip-guarded, honest defensive coverage for a future
// regeneration where one might.
test("a non-indexed contributor card explains itself instead of silently failing to link", async ({
  page,
  request,
}) => {
  const [challengeRes, contributorRes] = await Promise.all([
    request.get("/data/challenge.v2.json"),
    request.get("/data/contributors/index.v1.json"),
  ]);
  const { albums, paths } = (await challengeRes.json()) as {
    albums: { id: string }[];
    paths: {
      from_album_id: string;
      to_album_id: string;
      hops: { artist_a_id: number; artist_b_id: number }[];
    }[];
  };
  const { contributors } = (await contributorRes.json()) as {
    contributors: { artist_id: number }[];
  };
  const indexedIds = new Set(contributors.map((c) => c.artist_id));

  let targetAlbumId: string | null = null;
  for (const album of albums) {
    const connectedPaths = paths.filter(
      (p) => p.from_album_id === album.id || p.to_album_id === album.id,
    );
    const hasNonIndexed = connectedPaths.some((p) =>
      p.hops.some(
        (h) => !indexedIds.has(h.artist_a_id) || !indexedIds.has(h.artist_b_id),
      ),
    );
    if (hasNonIndexed) {
      targetAlbumId = album.id;
      break;
    }
  }
  test.skip(
    !targetAlbumId,
    "no album with a non-indexed contributor exists in the real catalog today",
  );

  await stubCoverArt(page);
  await page.goto(`/albums/${targetAlbumId}/`);
  const nonLinkedCard = page.locator(
    "div.contributor-card:has-text('not yet indexed')",
  );
  await expect(nonLinkedCard.first()).toBeVisible();
});

// Phase 6: continuous navigation -- every documented connection shown on an
// album page is also a direct, prefilled entry point into Connect Two
// Records, reusing connectUrlState.ts's existing ?a=/?b= contract untouched
// (no new URL-parsing code; this only adds a link to an already-shipped,
// already-tested restore-from-URL path).
test("an album page's documented connections link directly into Connect Two Records", async ({
  page,
  request,
}) => {
  const { album } = await pickBoundedConnectedAlbum(request);
  const challengeRes = await request.get("/data/challenge.v2.json");
  const { albums, paths } = (await challengeRes.json()) as {
    albums: { id: string; title: string }[];
    paths: { from_album_id: string; to_album_id: string }[];
  };
  const albumById = new Map(albums.map((a) => [a.id, a]));
  const firstPath = paths.find(
    (p) => p.from_album_id === album.id || p.to_album_id === album.id,
  );
  if (!firstPath) throw new Error(`no path found for ${album.id}`);
  const otherAlbumId =
    firstPath.from_album_id === album.id
      ? firstPath.to_album_id
      : firstPath.from_album_id;
  const otherAlbum = albumById.get(otherAlbumId);
  if (!otherAlbum)
    throw new Error(`album ${otherAlbumId} missing from challenge.v2.json`);

  await page.goto(`/albums/${album.id}/`);
  const connectLink = page
    .locator(".play-path")
    .first()
    .getByRole("link", { name: /search this route in connect two records/i });
  await expect(connectLink).toHaveAttribute(
    "href",
    `/play/connect/?a=${album.id}&b=${otherAlbumId}`,
  );

  await connectLink.click();
  await expect(page).toHaveURL(
    new RegExp(`/play/connect/\\?a=${album.id}&b=${otherAlbumId}$`),
  );
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  await expect(
    page.locator('[data-picker="a"] [data-picker-selected]'),
  ).toContainText(album.title);
  await expect(
    page.locator('[data-picker="b"] [data-picker-selected]'),
  ).toContainText(otherAlbum.title);
});

// Dedicated hotlink-contract coverage (AGENTS.md: cover art is served from
// Discogs' own CDN, never downloaded/rehosted here), decoupled from the
// interaction test above -- this album is deterministically known to have
// real registry art, independent of path count or artifact ordering.
test("an album with registry art hotlinks its cover to the Discogs CDN", async ({
  page,
  request,
}) => {
  const { album } = await pickConnectedAlbumWithArt(request);
  await stubCoverArt(page);

  await page.goto(`/albums/${album.id}/`);
  await expect(page.locator(".play-header__cover")).toHaveAttribute(
    "src",
    /^https:\/\/i\.discogs\.com\//,
  );
});

test("cohorts index lists cohorts and links to a detail page", async ({
  page,
}) => {
  await page.goto("/cohorts/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "Browse cohorts",
  );
  await expect(
    page.getByText("Synthetic Example Cohort").first(),
  ).toBeVisible();

  const openCohortLink = page
    .getByRole("link", { name: "Open cohort" })
    .first();
  await expect(openCohortLink).toHaveAttribute(
    "href",
    "/cohorts/synthetic-example/",
  );
});

test("cohort detail page shows the synthetic notice and reveals a pair", async ({
  page,
}) => {
  await page.goto("/cohorts/synthetic-example/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "Synthetic Example Cohort",
  );
  await expect(page.locator("[data-synthetic-notice]")).toBeVisible();
  await expect(page.locator("[data-cohort-pair]").first()).toBeVisible();
  await expect(page.locator(".tag--status-synthetic")).toBeVisible();
  await expect(page.locator(".tag--difficulty").first()).toBeVisible();

  await expect(page.locator("[data-guess-target]:not([hidden])")).toHaveCount(
    0,
  );
  const firstReveal = page.locator("[data-reveal-button]").first();
  await expect(firstReveal).toHaveText("Reveal");
  await expect(firstReveal).toHaveAttribute("aria-expanded", "false");
  const controls = await firstReveal.getAttribute("aria-controls");
  if (!controls) throw new Error("Reveal button is missing aria-controls");
  await expect(page.locator(`#${controls}`)).toBeHidden();

  await firstReveal.click();
  await expect(firstReveal).toHaveText("Hide");
  await expect(firstReveal).toHaveAttribute("aria-expanded", "true");
  await expect(
    page.locator("[data-guess-target]:not([hidden])").first(),
  ).toBeVisible();
  await expect(page.locator(`#${controls}`)).toBeVisible();
  // Plan §12.7: cohort hops render through the shared evidence panel — the
  // playable-cohort contract ships no per-credit rows, so the quality-flags
  // line stands in.
  await expect(page.locator(`#${controls} .hop`).first()).toContainText(
    "reviewed as a whole",
  );

  await firstReveal.click();
  await expect(firstReveal).toHaveText("Reveal");
  await expect(firstReveal).toHaveAttribute("aria-expanded", "false");
  await expect(page.locator(`#${controls}`)).toBeHidden();

  // Plan §12.7: the page links onward into play.
  await expect(
    page.locator(
      "[data-testid='cohort-play-link'] a[href='/play/connection/']",
    ),
  ).toBeVisible();

  const bodyText = (await page.textContent("body"))?.toLowerCase() ?? "";
  expect(bodyText).not.toContain("worked with");
  expect(bodyText).not.toContain("collaborated with");
  expect(bodyText).not.toContain("influenced");
});

test("play hub lists mode cards with honest availability", async ({ page }) => {
  await page.goto("/play/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "Pick a game",
  );
  const cards = page.locator("[data-testid='mode-card']");
  await expect(cards.first()).toBeVisible();
  expect(await cards.count()).toBeGreaterThanOrEqual(4);
  // At least one live mode links onward; coming modes are never dead links.
  await expect(
    page.locator("a[data-mode-status='live']").first(),
  ).toHaveAttribute("href", /\/(play\/connection|albums|cohorts)\//);
  expect(await page.locator("a[data-mode-status='coming']").count()).toBe(0);
});

test("old /play/<album>/ URLs redirect to /albums/<album>/", async ({
  page,
  request,
}) => {
  const { album } = await pickBoundedConnectedAlbum(request);
  await stubCoverArt(page);

  await page.goto(`/play/${album.id}/`);
  // The meta refresh lands on the new home; the stub also carries a canonical.
  await page.waitForURL(`**/albums/${album.id}/`);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    album.title,
  );
});

test("primary nav marks the current section with aria-current", async ({
  page,
}) => {
  await page.goto("/albums/");
  await expect(
    page.locator("nav[aria-label='Primary'] a[aria-current='page']"),
  ).toHaveText("Browse");
  await page.goto("/play/daily/");
  await expect(
    page.locator("nav[aria-label='Primary'] a[aria-current='page']"),
  ).toHaveText("Today's Connection");
  await page.goto("/play/connection/");
  await expect(
    page.locator("nav[aria-label='Primary'] a[aria-current='page']"),
  ).toHaveText("Connection Guesser");
  await page.goto("/contributors/");
  await expect(
    page.locator("nav[aria-label='Primary'] a[aria-current='page']"),
  ).toHaveText("Contributors");
});

test("primary nav includes a real, working Contributors link", async ({
  page,
}) => {
  await page.goto("/");
  const navLink = page.locator(
    "nav[aria-label='Primary'] a[href='/contributors/']",
  );
  await expect(navLink).toBeVisible();
  await navLink.click();
  await page.waitForURL("**/contributors/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
});

test("the play hub is reachable from the homepage, not just by URL", async ({
  page,
}) => {
  await page.goto("/");
  const playHubLink = page.locator("a[href='/play/']").first();
  await expect(playHubLink).toBeVisible();
  await playHubLink.click();
  await page.waitForURL("**/play/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "Pick a game",
  );
});

test("the play hub lists Contributors as a real, live mode card", async ({
  page,
}) => {
  await page.goto("/play/");
  const contributorsCard = page.locator(
    "[data-testid='mode-card'][href='/contributors/']",
  );
  await expect(contributorsCard).toBeVisible();
  await expect(contributorsCard).toHaveAttribute("data-mode-status", "live");
});

test("the homepage features a real contributor, deterministically picked from the published index", async ({
  page,
  request,
}) => {
  const res = await request.get("/data/contributors/index.v1.json");
  const { contributors } = (await res.json()) as {
    contributors: Array<{
      artist_id: number;
      name: string;
      albums: string[];
      interesting_next_step: { artist_id: number } | null;
    }>;
  };
  const expected = contributors.find(
    (c) => c.interesting_next_step !== null && c.albums.length > 0,
  );
  test.skip(!expected, "no contributor in the real index qualifies today");

  await page.goto("/");
  const featuredLink = page.locator(
    `a.contributor-card[href='/contributors/${expected!.artist_id}/']`,
  );
  await expect(featuredLink).toBeVisible();
  await expect(featuredLink).toContainText(expected!.name);
  await featuredLink.click();
  await page.waitForURL(`**/contributors/${expected!.artist_id}/`);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    expected!.name,
  );
});

test("sitemap includes every play mode, including record routes", async ({
  request,
}) => {
  const res = await request.get("/sitemap.xml");
  const body = await res.text();
  for (const path of [
    "/play/",
    "/play/connection/",
    "/play/daily/",
    "/play/routes/",
  ]) {
    expect(body).toContain(`<loc>`);
    expect(body).toContain(path);
  }
});

test.describe("mobile layout", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("an album page's new discovery modules don't cause sideways scroll on a phone-sized screen", async ({
    page,
    request,
  }) => {
    const { album } = await pickBoundedConnectedAlbum(request);
    await stubCoverArt(page);
    await page.goto(`/albums/${album.id}/`);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test("the album shelf's search/sort controls don't cause sideways scroll on a phone-sized screen", async ({
    page,
  }) => {
    await page.goto("/albums/");
    await expect(page.locator("[data-albums-search]")).toBeVisible();

    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });
});
