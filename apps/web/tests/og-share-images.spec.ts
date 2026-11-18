// P5c: text-only per-record share images.

import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { cardMarkup, collectStrings } from "../src/og/card";
import { albumCard, albumOgAlt } from "../src/og/cards";
import type { ChallengeV2 } from "../src/data/challenge";

const challenge = JSON.parse(
  readFileSync("public/data/challenge.v3.json", "utf8"),
) as ChallengeV2;
const album = challenge.albums[0];

test("card markup contains only text and vector shapes, no remote URLs or images", () => {
  const tree = cardMarkup(albumCard(album), "Networked Players");
  const json = JSON.stringify(tree);
  expect(json).not.toMatch(/https?:|\/\/|data:|url\(/i);
  expect(json).not.toContain('"type":"img"');
  expect(json).not.toContain("discogs");
  const strings = collectStrings(tree).filter((s) => /[A-Za-z0-9]/.test(s));
  expect(strings).toContain(album.title);
  expect(strings).toContain("Networked Players");
});

test("og:image alt describes the record", () => {
  expect(albumOgAlt(album)).toContain(album.title);
  expect(albumOgAlt(album)).toContain(album.artist);
});

for (const path of [`/albums/${album.id}/`, `/explore/${album.id}/`]) {
  test(`${path} og:image resolves to a 1200x630 PNG`, async ({
    page,
    request,
  }) => {
    await page.goto(path);
    const og = await page
      .locator('meta[property="og:image"]')
      .getAttribute("content");
    const twitter = await page
      .locator('meta[name="twitter:image"]')
      .getAttribute("content");
    expect(og).toBe(twitter);
    expect(
      await page
        .locator('meta[property="og:image:alt"]')
        .getAttribute("content"),
    ).toContain(album.title);
    const url = new URL(og!);
    expect(url.pathname).toBe(`/og/albums/${album.id}.png`);
    const res = await request.get(url.pathname);
    expect(res.ok()).toBe(true);
    expect(res.headers()["content-type"]).toContain("image/png");
    const body = await res.body();
    expect(body.subarray(1, 4).toString()).toBe("PNG");
    expect(body.readUInt32BE(16)).toBe(1200);
    expect(body.readUInt32BE(20)).toBe(630);
    expect(body.length).toBeLessThan(80_000);
  });
}
