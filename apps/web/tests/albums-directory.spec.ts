// Album shelf search/sort unit + integration specs (PR G): searchAlbums
// pure logic, and a real end-to-end run against the committed catalog.

import { expect, test } from "@playwright/test";
import {
  availableDecades,
  decadeOf,
  searchAlbums,
  type DirectoryAlbum,
} from "../src/game/albumsDirectory";

function fixture(): DirectoryAlbum[] {
  return [
    { id: "master-1", title: "Zebra Songs", artist: "Alice Ray", year: 1990 },
    { id: "master-2", title: "Ambient Fields", artist: "Bob Ray", year: 1985 },
    { id: "master-3", title: "Middle Ground", artist: "Cara Lane", year: 2001 },
    { id: "master-4", title: "Another Angle", artist: "Alice Ray", year: null },
  ];
}

test("searchAlbums with an empty query and title sort returns everything, alphabetically", () => {
  const result = searchAlbums(fixture(), "", "title");
  expect(result.map((a) => a.title)).toEqual([
    "Ambient Fields",
    "Another Angle",
    "Middle Ground",
    "Zebra Songs",
  ]);
});

test("searchAlbums matches a case-insensitive substring in the title", () => {
  const result = searchAlbums(fixture(), "amb", "title");
  expect(result.map((a) => a.title)).toEqual(["Ambient Fields"]);
});

test("searchAlbums matches a case-insensitive substring in the artist", () => {
  const result = searchAlbums(fixture(), "cara", "title");
  expect(result.map((a) => a.title)).toEqual(["Middle Ground"]);
});

test("searchAlbums with no matches returns an empty array, not an error", () => {
  expect(searchAlbums(fixture(), "no such album", "title")).toEqual([]);
});

test("searchAlbums sorts by artist, ties broken by title", () => {
  const result = searchAlbums(fixture(), "", "artist");
  expect(result.map((a) => a.title)).toEqual([
    "Another Angle", // Alice Ray, "Another Angle" < "Zebra Songs"
    "Zebra Songs",
    "Ambient Fields", // Bob Ray
    "Middle Ground", // Cara Lane
  ]);
});

test("searchAlbums sorts by year, newest first, with unknown years always last", () => {
  const result = searchAlbums(fixture(), "", "year-desc");
  expect(result.map((a) => a.title)).toEqual([
    "Middle Ground", // 2001
    "Zebra Songs", // 1990
    "Ambient Fields", // 1985
    "Another Angle", // null -- last regardless of direction
  ]);
});

test("searchAlbums sorts by year, oldest first, with unknown years still last", () => {
  const result = searchAlbums(fixture(), "", "year-asc");
  expect(result.map((a) => a.title)).toEqual([
    "Ambient Fields", // 1985
    "Zebra Songs", // 1990
    "Middle Ground", // 2001
    "Another Angle", // null -- last regardless of direction
  ]);
});

test("decadeOf buckets a year to its decade, and null to the unknown bucket", () => {
  expect(decadeOf(1985)).toBe("1980s");
  expect(decadeOf(1990)).toBe("1990s");
  expect(decadeOf(2001)).toBe("2000s");
  expect(decadeOf(null)).toBe("unknown");
});

test("availableDecades lists only decades actually present, newest first, unknown last", () => {
  expect(availableDecades(fixture())).toEqual([
    "2000s",
    "1990s",
    "1980s",
    "unknown",
  ]);
});

test("availableDecades never lists a decade with zero real matches", () => {
  const noUnknowns = fixture().filter((a) => a.year !== null);
  expect(availableDecades(noUnknowns)).toEqual(["2000s", "1990s", "1980s"]);
});

test("searchAlbums narrows by decade", () => {
  const result = searchAlbums(fixture(), "", "title", "1980s");
  expect(result.map((a) => a.title)).toEqual(["Ambient Fields"]);
});

test("searchAlbums combines a decade filter with a text query", () => {
  const result = searchAlbums(fixture(), "ray", "title", "1990s");
  expect(result.map((a) => a.title)).toEqual(["Zebra Songs"]);
});

test("searchAlbums's unknown-year bucket only matches albums with no year", () => {
  const result = searchAlbums(fixture(), "", "title", "unknown");
  expect(result.map((a) => a.title)).toEqual(["Another Angle"]);
});

test("a real search against the committed catalog finds a real album by title", async ({
  request,
}) => {
  const challenge = await (await request.get("/data/challenge.v3.json")).json();
  const albums: DirectoryAlbum[] = challenge.albums;
  const target = albums[Math.floor(albums.length / 2)];
  const needle = target.title.slice(0, 5);

  const result = searchAlbums(albums, needle, "title");
  expect(result.some((a) => a.id === target.id)).toBe(true);
});

test("the real /albums/ page: searching narrows the grid and announces the count", async ({
  page,
}) => {
  await page.goto("/albums/");
  const status = page.locator("[data-albums-status]");
  const totalCards = await page.locator(".album-card").count();
  await expect(status).toHaveText(
    `Showing ${totalCards} of ${totalCards} albums.`,
  );

  const targetTitle = await page
    .locator(".album-card")
    .first()
    .getAttribute("data-album-title");
  expect(targetTitle).toBeTruthy();

  await page.locator("[data-albums-search]").fill(targetTitle!.slice(0, 4));
  await expect(page.locator(".album-card:not([hidden])")).toHaveCount(1);
  await expect(page.locator(".album-card:not([hidden])")).toHaveAttribute(
    "data-album-title",
    targetTitle!,
  );

  await page
    .locator("[data-albums-search]")
    .fill("zzz-no-real-album-matches-this");
  await expect(status).toHaveText("No albums match your search.");
  await expect(page.locator(".album-card:not([hidden])")).toHaveCount(0);
});

// A real, independently-confirmed Codex-review finding (PR #163, never
// fixed at the time): `.album-card` sets `display: flex` unconditionally
// in motif.css, which outranks the UA stylesheet's bare
// `[hidden] { display: none }` rule -- a filtered-out card kept the
// `hidden` ATTRIBUTE (which the searching test above already covers) but
// stayed visually painted. `:not([hidden])` locators only ever check the
// attribute, never actual visibility, so this needed its own real
// computed-style assertion to catch.
test("the real /albums/ page: a filtered-out card is actually visually hidden, not just marked hidden", async ({
  page,
}) => {
  await page.goto("/albums/");
  const targetTitle = await page
    .locator(".album-card")
    .first()
    .getAttribute("data-album-title");
  expect(targetTitle).toBeTruthy();

  await page
    .locator("[data-albums-search]")
    .fill("zzz-no-real-album-matches-this");
  await expect(page.locator("[data-albums-status]")).toHaveText(
    "No albums match your search.",
  );

  const anyCardVisuallyShown = await page.evaluate(() => {
    return [...document.querySelectorAll<HTMLElement>(".album-card")].some(
      (card) => getComputedStyle(card).display !== "none",
    );
  });
  expect(anyCardVisuallyShown).toBe(false);
});

test("the real /albums/ page: sorting by year actually reorders the grid's real DOM order", async ({
  page,
}) => {
  // Reads document order directly (no more sorting by a CSS `order`
  // side-channel) -- this is now the real, load-bearing proof that a
  // filtered/sorted view produces the correct keyboard tab order and
  // screen-reader reading order, not just the correct on-screen position.
  await page.goto("/albums/");
  await page.locator("[data-albums-sort]").selectOption("year-asc");

  const orderedYears = await page.evaluate(() => {
    return [
      ...document.querySelectorAll<HTMLElement>(".album-card:not([hidden])"),
    ]
      .map((c) => c.dataset.albumYear)
      .filter((year): year is string => Boolean(year))
      .map(Number);
  });

  expect(orderedYears.length).toBeGreaterThan(1);
  const sorted = [...orderedYears].sort((a, b) => a - b);
  expect(orderedYears).toEqual(sorted);
});

test("the real /albums/ page: the decade filter narrows the grid to that decade only", async ({
  page,
}) => {
  await page.goto("/albums/");
  const decadeSelect = page.locator("[data-albums-decade]");
  const options = await decadeSelect.locator("option").allTextContents();
  expect(options).toContain("All decades");
  expect(options.length).toBeGreaterThan(1);

  const targetDecade = await decadeSelect
    .locator("option")
    .nth(1)
    .getAttribute("value");
  await decadeSelect.selectOption(targetDecade!);

  const visibleYears = await page
    .locator(".album-card:not([hidden])")
    .evaluateAll((cards) =>
      cards.map((c) => (c as HTMLElement).dataset.albumYear),
    );
  expect(visibleYears.length).toBeGreaterThan(0);
  if (targetDecade !== "unknown") {
    const decadeStart = Number.parseInt(targetDecade!, 10);
    for (const year of visibleYears) {
      expect(Number(year)).toBeGreaterThanOrEqual(decadeStart);
      expect(Number(year)).toBeLessThan(decadeStart + 10);
    }
  } else {
    expect(visibleYears.every((year) => !year)).toBe(true);
  }
});

test("the real /albums/ page: search/sort/decade state round-trips through the URL", async ({
  page,
}) => {
  await page.goto("/albums/");
  const targetTitle = await page
    .locator(".album-card")
    .first()
    .getAttribute("data-album-title");
  const needle = targetTitle!.slice(0, 4);

  await page.locator("[data-albums-search]").fill(needle);
  await page.locator("[data-albums-sort]").selectOption("year-desc");
  await expect(page).toHaveURL(
    new RegExp(`[?&]q=${encodeURIComponent(needle)}(&|$)`),
  );
  await expect(page).toHaveURL(/[?&]sort=year-desc(&|$)/);

  // Reloading a bookmarked/shared URL with state in it restores that exact
  // state -- the actual point of making it URL-addressable, not just that
  // the URL happens to change.
  const url = page.url();
  await page.goto(url);
  await expect(page.locator("[data-albums-search]")).toHaveValue(needle);
  await expect(page.locator("[data-albums-sort]")).toHaveValue("year-desc");
  await expect(
    page.locator(".album-card:not([hidden])").first(),
  ).toHaveAttribute("data-album-title", targetTitle!);
});

test("the real /albums/ page: clearing the search removes q from the URL rather than leaving it empty", async ({
  page,
}) => {
  await page.goto("/albums/");
  const searchInput = page.locator("[data-albums-search]");
  await searchInput.fill("something");
  await expect(page).toHaveURL(/[?&]q=something(&|$)/);
  await searchInput.fill("");
  await expect(page).not.toHaveURL(/[?&]q=/);
});

test("the real /albums/ page: back navigation past an earlier same-document entry re-syncs the controls and grid", async ({
  page,
}) => {
  // State only ever reaches the URL via `replaceState`, so this page never
  // pushes its OWN history entry -- but an earlier same-document entry can
  // still exist (e.g. the "#main" skip link), and a back step through THAT
  // fires `popstate` with a URL these controls never wrote themselves.
  // Without a `popstate` handler, the address bar changes but the search
  // input and grid silently keep showing the just-filtered state.
  await page.goto("/albums/");
  const totalCards = await page.locator(".album-card").count();

  // Simulate the skip-link's same-document jump: a real earlier history
  // entry with no query state, distinct from the one the search below
  // will `replaceState` on top of.
  await page.evaluate(() => {
    window.history.pushState(null, "", `${location.pathname}#main`);
  });

  const targetTitle = await page
    .locator(".album-card")
    .first()
    .getAttribute("data-album-title");
  const needle = targetTitle!.slice(0, 4);
  await page.locator("[data-albums-search]").fill(needle);
  await expect(page).toHaveURL(
    new RegExp(`[?&]q=${encodeURIComponent(needle)}(&|$)`),
  );
  await expect(page.locator(".album-card:not([hidden])")).not.toHaveCount(
    totalCards,
  );

  await page.goBack();
  await expect(page).not.toHaveURL(/[?&]q=/);
  await expect(page.locator("[data-albums-search]")).toHaveValue("");
  await expect(page.locator(".album-card:not([hidden])")).toHaveCount(
    totalCards,
  );
});

test("the real /albums/ page: an invalid decade in the URL falls back to All decades rather than breaking", async ({
  page,
}) => {
  await page.goto("/albums/?decade=not-a-real-decade");
  await expect(page.locator("[data-albums-decade]")).toHaveValue("all");
  const totalCards = await page.locator(".album-card").count();
  await expect(page.locator(".album-card:not([hidden])")).toHaveCount(
    totalCards,
  );
});
