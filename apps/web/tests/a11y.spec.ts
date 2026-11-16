// Automated accessibility coverage (Phase 2 follow-up slice, issue #53):
// an axe-core scan across the app's key surfaces. This closes the
// automatable, code-level gaps only -- issue #53's manual-human items
// (VoiceOver, 200% zoom, image-failure fallback) stay explicitly out of
// scope and unexercised here, same as the Phase 2 final report's own
// "not exercised" list.

import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { catalogFacts, pickScanContributorId } from "./helpers/catalogFacts";

// Invariant: key surfaces have no WCAG 2 A/AA violations. The album and
// contributor pages are chosen by rule from the committed artifacts
// (helpers/catalogFacts.ts), never named here.
const facts = await catalogFacts();

const PAGES = [
  "/",
  `/albums/${facts.connected.a.id}/`,
  "/play/connection/",
  "/play/daily/",
  "/play/routes/",
  `/explore/${facts.explorer.album.id}/`,
  `/contributors/${pickScanContributorId()}/`,
];

for (const path of PAGES) {
  test(`${path} has no automatically-detectable accessibility violations`, async ({
    page,
  }) => {
    // Large contributor/explore pages make axe's per-element work exceed the
    // default budget under suite load (a heavy page, not a regression).
    if (path.startsWith("/contributors/") || path.startsWith("/explore/")) {
      test.slow();
    }
    await page.goto(path);
    // Let each page's async data fetch (pathfinding graph, contributor
    // index, etc) finish rendering before scanning -- a mid-fetch DOM
    // isn't the state worth auditing.
    await page.waitForLoadState("networkidle");

    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa"])
      .analyze();

    expect(
      results.violations,
      JSON.stringify(results.violations, null, 2),
    ).toEqual([]);
  });
}
