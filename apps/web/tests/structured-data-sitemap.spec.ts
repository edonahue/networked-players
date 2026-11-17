// P5a: JSON-LD, canonical URLs, sitemap contents and the retired /demo/.

import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import {
  jsonLdScript,
  musicAlbumJsonLd,
  personJsonLd,
} from "../src/data/structuredData";
import type { ChallengeV2 } from "../src/data/challenge";

const challenge = JSON.parse(
  readFileSync("public/data/challenge.v3.json", "utf8"),
) as ChallengeV2;
const album = challenge.albums[0];

test("jsonLdScript can never close the script element", () => {
  const out = jsonLdScript({ name: "</script><script>alert(1)</script><!--" });
  expect(out).not.toContain("<");
  expect(JSON.parse(out).name).toBe("</script><script>alert(1)</script><!--");
});

test("MusicAlbum JSON-LD omits datePublished without a year and has no image", () => {
  const ld = musicAlbumJsonLd({ ...album, year: null });
  expect(ld["@type"]).toBe("MusicAlbum");
  expect("datePublished" in ld).toBe(false);
  expect(JSON.stringify(ld)).not.toContain("discogs.com");
  expect(personJsonLd(1, "X")["@type"]).toBe("Person");
});

test("sitemap lists records but not /demo/ or synthetic cohort pages", async ({
  request,
}) => {
  const xml = await (await request.get("/sitemap.xml")).text();
  expect(xml).toContain(`/albums/${album.id}/`);
  expect(xml).not.toContain("/demo/");
  expect(xml).not.toContain("/cohorts/");
});

test("album and explore pages emit canonical trailing-slash URLs and album JSON-LD", async ({
  page,
}) => {
  await page.goto(`/albums/${album.id}/`);
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
    "href",
    `https://networked-players.com/albums/${album.id}/`,
  );
  const blocks = await page
    .locator('script[type="application/ld+json"]')
    .allTextContents();
  const parsed = blocks.map((b) => JSON.parse(b));
  const music = parsed.find((b) => b["@type"] === "MusicAlbum");
  expect(music.name).toBe(album.title);
  expect(music.byArtist.name).toBe(album.artist);

  await page.goto(`/explore/${album.id}/`);
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
    "href",
    `https://networked-players.com/explore/${album.id}/`,
  );
});

test("/demo/ is retired and the 404 offers search", async ({ page }) => {
  const res = await page.goto("/demo/");
  expect(res?.status()).toBe(404);
  await expect(
    page.getByRole("link", { name: "Search records" }).first(),
  ).toBeVisible();
});
