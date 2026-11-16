// Automated accessibility scan (axe-core, post-Phase-4 cleanup audit §7) --
// a real, repeatable complement to the manual VoiceOver/200%-zoom/device
// pass, not a replacement for it. axe-core's default ruleset (WCAG 2.0/2.1
// A/AA plus best-practice checks) catches a real, meaningful subset of
// accessibility defects (missing labels, contrast, invalid ARIA, focus
// order structure) automatically on every run; it cannot verify a screen
// reader's actual spoken output, real zoom reflow, or physical touch-target
// behavior, all of which still need a human. Scans real committed data at
// both static and dynamic (post-interaction) states, since a defect that
// only exists after a search/click would be invisible to a static-only scan.

import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { selectAlbumById } from "./helpers/connectPicker";
import { pickBoundedConnectedAlbum } from "./helpers/challengeAlbums";
import { catalogFacts, pickScanContributorId } from "./helpers/catalogFacts";

// Albums are derived from the committed artifacts by rule (see
// helpers/catalogFacts.ts), never named here.
const facts = await catalogFacts();
const EXPLORER = facts.explorer;
const CONNECTED = facts.connected;

async function expectNoViolations(page: import("@playwright/test").Page) {
  const results = await new AxeBuilder({ page }).analyze();
  expect(
    results.violations,
    results.violations
      .map(
        (v) =>
          `[${v.impact}] ${v.id}: ${v.description} -- ${v.nodes
            .map((n) => n.target.join(" "))
            .join(", ")}`,
      )
      .join("\n"),
  ).toEqual([]);
}

test("home has no automated accessibility violations", async ({ page }) => {
  await page.goto("/");
  await expectNoViolations(page);
});

test("about has no automated accessibility violations", async ({ page }) => {
  await page.goto("/about/");
  await expectNoViolations(page);
});

test("connect has no automated accessibility violations before a search", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await expectNoViolations(page);
});

test("connect has no automated accessibility violations after a real search", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbumById(page, "a", CONNECTED.a);
  await selectAlbumById(page, "b", CONNECTED.b);
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  await expectNoViolations(page);
});

test("explore has no automated accessibility violations", async ({ page }) => {
  await page.goto(`/explore/${EXPLORER.album.id}/`);
  await expect(
    page.locator("[data-explorer-nodes] .explorer-node").first(),
  ).toBeVisible({ timeout: 15000 });
  await expectNoViolations(page);
});

// The drawer un-hides synchronously and only THEN fetches the 3.3MB evidence
// registry, so waiting on visibility alone scanned "<p>Loading evidence…</p>"
// -- measured as the drawer's content in 3/3 runs, with the real card landing
// 216-305ms later. That silently excluded exactly the markup this test exists
// to audit: the Discogs release link's accessible name, the cover image's
// alt text, and the muted-contrast role/source text. Gate on the drawer's
// real settled state plus the final content itself.
test("explore has no automated accessibility violations with the evidence drawer open", async ({
  page,
}) => {
  await page.goto(`/explore/${EXPLORER.album.id}/`);
  await expect(
    page.locator("[data-explorer-nodes] .explorer-node").first(),
  ).toBeVisible({ timeout: 15000 });
  await page
    .locator("[data-explorer-edges] .explorer-edge-group")
    .first()
    .click();

  const drawer = page.locator("[data-explorer-evidence-drawer]");
  await expect(drawer).toHaveAttribute(
    "data-evidence-state",
    /^(ready|unavailable)$/,
    { timeout: 15000 },
  );
  await expect(drawer).toHaveAttribute("aria-busy", "false");

  // The final evidence card, not the placeholder it replaced.
  const content = page.locator("[data-explorer-evidence-content]");
  await expect(content.locator(".connect-hop")).toBeVisible();
  await expect(
    content.locator("a[href*='discogs.com/release/']"),
  ).toBeVisible();

  // Still open, and focus transferred on activation survived the async
  // content swap rather than being dropped back to <body>.
  await expect(drawer).toBeVisible();
  await expect(drawer).toBeFocused();

  await expectNoViolations(page);
});

// Additive, not a substitute for the settled-state scan above: the loading
// state is a real state a visitor can be in, and holding the registry
// response open makes it deterministically reachable.
test("explore has no automated accessibility violations while evidence is loading", async ({
  page,
}) => {
  let releaseRegistry!: () => void;
  const registryGate = new Promise<void>((resolve) => {
    releaseRegistry = resolve;
  });
  await page.route(
    "**/data/evidence/release-registry.v1.json",
    async (route) => {
      await registryGate;
      await route.continue();
    },
  );

  await page.goto(`/explore/${EXPLORER.album.id}/`);
  await expect(
    page.locator("[data-explorer-nodes] .explorer-node").first(),
  ).toBeVisible({ timeout: 15000 });
  await page
    .locator("[data-explorer-edges] .explorer-edge-group")
    .first()
    .click();

  const drawer = page.locator("[data-explorer-evidence-drawer]");
  await expect(drawer).toHaveAttribute("data-evidence-state", "loading");
  await expect(drawer).toHaveAttribute("aria-busy", "true");
  await expectNoViolations(page);

  releaseRegistry();
  await expect(drawer).toHaveAttribute(
    "data-evidence-state",
    /^(ready|unavailable)$/,
    { timeout: 15000 },
  );
});

test("contributors directory has no automated accessibility violations", async ({
  page,
}) => {
  await page.goto("/contributors/");
  await expectNoViolations(page);
});

// Invariant: a LARGE contributor page has no axe violations. The page is
// chosen by rule (pickScanContributorId: most albums among contributors at or
// under SCAN_ALBUM_CAP), so it is always a heavy page but its size is bounded
// as the index grows -- a full axe analyze() on such a page is dominated by
// per-element color-contrast/region work (~27s at ~3,100 elements), inside
// the default 30s budget in isolation but over it under full-suite CPU
// load. A heavy page for the scanner, not a page regression, so both
// contributor-page scans get the 3x `test.slow()` budget.
test("a contributor page has no automated accessibility violations", async ({
  page,
}) => {
  test.slow();
  await page.goto(`/contributors/${pickScanContributorId()}/`);
  await expectNoViolations(page);
});

// A real review finding: the default dark-theme scan above can pass while
// the same page fails WCAG AA contrast after a visitor switches to light
// theme -- --ink/--ink-strong composited over --surface has a different
// real contrast ratio per theme, and the automated suite otherwise only
// ever renders the default theme. This used to be pinned to a specific
// contributor who rendered a muted card (2026-08-31,
// background-engineering-only connections); ADR 0068 retired that muting
// entirely, so the scan now uses the same generic index-derived pick the
// dark-theme scan above does -- the per-theme contrast coverage this test
// exists for is unchanged.
test("a contributor page has no automated accessibility violations in light theme", async ({
  page,
}) => {
  test.slow(); // see the dark-theme scan above for the measured reason
  await page.goto(`/contributors/${pickScanContributorId()}/`);
  await page.locator("[data-theme-toggle]").click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expectNoViolations(page);
});

test("albums grid has no automated accessibility violations", async ({
  page,
}) => {
  await page.goto("/albums/");
  await expectNoViolations(page);
});

test("an album page with the new discovery modules has no automated accessibility violations", async ({
  page,
  request,
}) => {
  const { album } = await pickBoundedConnectedAlbum(request);
  await page.goto(`/albums/${album.id}/`);
  await expectNoViolations(page);
});
