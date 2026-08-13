// Album cover art is hotlinked straight from Discogs' CDN (i.discogs.com) in
// <img src>; the repo never downloads, stores, or rehosts image bytes (see
// apps/web/AGENTS.md). That is the right production behavior, but it makes
// any test that navigates an album page depend on an uncontrolled third-party
// CDN: the eager header cover blocks page.goto's default `load` wait, so a
// slow Discogs response is charged directly against the test timeout.
//
// Fulfilling those requests locally keeps the dependency deterministic while
// leaving the hotlink contract itself assertable in the DOM (the src still
// points at i.discogs.com, and specs assert that). Host-allowlist logic stays
// covered by game-albumart.spec.ts (APPROVED_HOSTS) and real registry-driven
// behavior by game-albumart-browser.spec.ts.

import { type Page } from "@playwright/test";

/** 1x1 transparent PNG. */
const TRANSPARENT_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
  "base64",
);

/** Serves every Discogs cover-art request locally and instantly. */
export async function stubCoverArt(page: Page): Promise<void> {
  await page.route("https://i.discogs.com/**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "image/png",
      body: TRANSPARENT_PNG,
    }),
  );
}
