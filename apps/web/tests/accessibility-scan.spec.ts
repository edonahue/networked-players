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
import { selectAlbum } from "./helpers/connectPicker";

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
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  await expectNoViolations(page);
});

test("explore has no automated accessibility violations", async ({ page }) => {
  await page.goto("/explore/master-107325/");
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
  await page.goto("/explore/master-107325/");
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

  await page.goto("/explore/master-107325/");
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

test("a contributor page has no automated accessibility violations", async ({
  page,
  request,
}) => {
  const res = await request.get("/data/contributors/index.v1.json");
  const { contributors } = (await res.json()) as {
    contributors: { artist_id: number; albums: string[] }[];
  };
  const withAlbum = contributors.find((c) => c.albums.length > 0);
  if (!withAlbum) throw new Error("no contributor with an album in the index");

  await page.goto(`/contributors/${withAlbum.artist_id}/`);
  await expectNoViolations(page);
});

test("albums grid has no automated accessibility violations", async ({
  page,
}) => {
  await page.goto("/albums/");
  await expectNoViolations(page);
});
