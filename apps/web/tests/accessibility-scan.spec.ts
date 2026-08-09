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
  await page.locator('[data-picker="a"] input').fill("Discovery");
  await page
    .locator('[data-picker="a"] [data-picker-results] button')
    .first()
    .click();
  await page.locator('[data-picker="b"] input').fill("Joshua Tree");
  await page
    .locator('[data-picker="b"] [data-picker-results] button')
    .first()
    .click();
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
  await expect(page.locator("[data-explorer-evidence-drawer]")).toBeVisible();
  await expectNoViolations(page);
});

test("contributors directory has no automated accessibility violations", async ({
  page,
}) => {
  await page.goto("/contributors/");
  await expectNoViolations(page);
});

test("albums grid has no automated accessibility violations", async ({
  page,
}) => {
  await page.goto("/albums/");
  await expectNoViolations(page);
});
