// Album shelf search/sort unit + integration specs (PR G): searchAlbums
// pure logic, and a real end-to-end run against the committed catalog.

import { expect, test } from "@playwright/test";
import { searchAlbums, type DirectoryAlbum } from "../src/game/albumsDirectory";

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

test("a real search against the committed catalog finds a real album by title", async ({
  request,
}) => {
  const challenge = await (await request.get("/data/challenge.v2.json")).json();
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

test("the real /albums/ page: sorting by year actually reorders the grid", async ({
  page,
}) => {
  // `.first()`/DOM order does not reflect CSS `order` -- reading the
  // computed order values directly is what proves the sort actually did
  // something, matching how the wiring itself decides render order.
  await page.goto("/albums/");
  await page.locator("[data-albums-sort]").selectOption("year-asc");

  const orderedYears = await page.evaluate(() => {
    const cards = [
      ...document.querySelectorAll<HTMLElement>(".album-card:not([hidden])"),
    ];
    cards.sort((a, b) => Number(a.style.order) - Number(b.style.order));
    return cards
      .map((c) => c.dataset.albumYear)
      .filter((year): year is string => Boolean(year))
      .map(Number);
  });

  expect(orderedYears.length).toBeGreaterThan(1);
  const sorted = [...orderedYears].sort((a, b) => a - b);
  expect(orderedYears).toEqual(sorted);
});
