import { expect, test } from "@playwright/test";
import {
  pickBoundedConnectedAlbum,
  pickConnectedAlbumWithArt,
} from "./helpers/challengeAlbums";
import { stubCoverArt } from "./helpers/coverArt";

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
    "Browse reviewed cohorts",
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
  // contract ships no per-credit rows, so the quality-flags line stands in.
  await expect(page.locator(`#${controls} .hop`).first()).toContainText(
    "playable-cohort contract",
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
  ).toHaveText("Find a Connection");
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
