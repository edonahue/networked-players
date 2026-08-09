// Network Explorer evidence drawer (ADR 0058 Slice 9): clicking, hovering,
// or keyboard-activating an edge shows real release/role evidence, joined
// against the evidence-release registry (ADR 0058 Slice 3) via the same
// renderEvidenceHop() Connect Two Records already uses. Real, committed
// data throughout -- master-107325 (Elvis Presley) is the same real,
// high-degree seed game-networkexplorer.spec.ts already uses.
//
// Real .click()/.hover()/.focus() throughout (post-Phase-4 cleanup audit
// F15): each edge used to be a single thin <line> with no wider hit-area,
// so the circular layout's first neighbor (directly above the center,
// networkExplorer.ts's neighborPosition) rendered as a perfect vertical
// with a zero-width bounding box -- genuinely hit-testable in a real
// browser (pointer-event hit-testing accounts for stroke width), but
// Playwright's actionability checks use getBoundingClientRect, which
// reflects only an SVG line's zero-width geometric path, forcing this
// file onto dispatchEvent/evaluate. Each edge is now a
// <g class="explorer-edge-group"> wrapping the visible line plus a wide
// invisible hit-area <rect> (explorerStage.ts's EDGE_HIT_AREA_WIDTH); a
// rect's own geometry always has real width/height, so the group's
// bounding box has real area regardless of the edge's angle, and real
// Playwright interaction methods work.

import { expect, test } from "@playwright/test";

async function waitForGraph(page: import("@playwright/test").Page) {
  await expect(
    page.locator("[data-explorer-nodes] .explorer-node").first(),
  ).toBeVisible({ timeout: 15000 });
}

function firstEdge(page: import("@playwright/test").Page) {
  return page.locator("[data-explorer-edges] .explorer-edge-group").first();
}

test("clicking an edge shows real evidence in the drawer", async ({ page }) => {
  await page.goto("/explore/master-107325/");
  await waitForGraph(page);
  await firstEdge(page).click();

  const drawer = page.locator("[data-explorer-evidence-drawer]");
  await expect(drawer).toBeVisible();
  const content = page.locator("[data-explorer-evidence-content]");
  await expect(content).toContainText(
    /co-credited on the same documented release/i,
  );
  await expect(
    content.locator("a[href*='discogs.com/release/']"),
  ).toBeVisible();
});

// Post-Phase-4 cleanup audit F17: a real click/keyboard activation must
// move real DOM focus into the drawer, not just make it visible.
test("clicking an edge moves real focus into the drawer", async ({ page }) => {
  await page.goto("/explore/master-107325/");
  await waitForGraph(page);
  await firstEdge(page).click();

  await expect(page.locator("[data-explorer-evidence-drawer]")).toBeFocused();
});

test("hovering an edge shows the drawer without a click", async ({ page }) => {
  await page.goto("/explore/master-107325/");
  await waitForGraph(page);
  await firstEdge(page).hover();

  await expect(page.locator("[data-explorer-evidence-drawer]")).toBeVisible();
  await expect(page.locator("[data-explorer-evidence-content]")).toContainText(
    /co-credited on the same documented release/i,
  );
});

// Post-Phase-4 cleanup audit F17: hovering only shows content -- it must
// never steal keyboard focus away from wherever it already was.
test("hovering an edge does not move focus into the drawer", async ({
  page,
}) => {
  await page.goto("/explore/master-107325/");
  await waitForGraph(page);
  await firstEdge(page).hover();

  await expect(page.locator("[data-explorer-evidence-drawer]")).toBeVisible();
  await expect(
    page.locator("[data-explorer-evidence-drawer]"),
  ).not.toBeFocused();
});

test("an edge is keyboard-reachable and Enter opens the same evidence", async ({
  page,
}) => {
  await page.goto("/explore/master-107325/");
  await waitForGraph(page);
  const edge = firstEdge(page);
  await expect(edge).toHaveAttribute("tabindex", "0");

  await edge.focus();
  await page.keyboard.press("Enter");

  await expect(page.locator("[data-explorer-evidence-drawer]")).toBeVisible();
  await expect(page.locator("[data-explorer-evidence-content]")).toContainText(
    /co-credited on the same documented release/i,
  );
});

// Post-Phase-4 cleanup audit F16: edges use one roving tabindex position,
// matching the node layer's own pattern -- only the first edge is a tab
// stop on a fresh render; arrow keys move both the roving position and
// real focus.
test("arrow keys move the roving tab stop between edges", async ({ page }) => {
  await page.goto("/explore/master-107325/");
  await waitForGraph(page);
  const edges = page.locator("[data-explorer-edges] .explorer-edge-group");
  const count = await edges.count();
  test.skip(count < 2, "this real center doesn't have a second edge");

  await expect(edges.nth(0)).toHaveAttribute("tabindex", "0");
  await expect(edges.nth(1)).toHaveAttribute("tabindex", "-1");

  await edges.nth(0).focus();
  await page.keyboard.press("ArrowRight");

  await expect(edges.nth(0)).toHaveAttribute("tabindex", "-1");
  await expect(edges.nth(1)).toHaveAttribute("tabindex", "0");
  await expect(edges.nth(1)).toBeFocused();
});

test("the close button hides the drawer", async ({ page }) => {
  await page.goto("/explore/master-107325/");
  await waitForGraph(page);
  await firstEdge(page).click();
  await expect(page.locator("[data-explorer-evidence-drawer]")).toBeVisible();

  await page.locator("[data-explorer-evidence-close]").click();
  await expect(page.locator("[data-explorer-evidence-drawer]")).toBeHidden();
});

// Post-Phase-4 cleanup audit F17: closing the drawer restores focus to the
// edge that opened it, rather than leaving focus nowhere (on a removed/
// hidden element).
test("the close button restores focus to the triggering edge", async ({
  page,
}) => {
  await page.goto("/explore/master-107325/");
  await waitForGraph(page);
  const edge = firstEdge(page);
  await edge.click();
  await expect(page.locator("[data-explorer-evidence-drawer]")).toBeVisible();

  await page.locator("[data-explorer-evidence-close]").click();
  await expect(edge).toBeFocused();
});

test("Escape hides the drawer", async ({ page }) => {
  await page.goto("/explore/master-107325/");
  await waitForGraph(page);
  await firstEdge(page).click();
  await expect(page.locator("[data-explorer-evidence-drawer]")).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(page.locator("[data-explorer-evidence-drawer]")).toBeHidden();
});

test("recentering the graph closes the drawer", async ({ page }) => {
  await page.goto("/explore/master-107325/");
  await waitForGraph(page);
  await firstEdge(page).click();
  await expect(page.locator("[data-explorer-evidence-drawer]")).toBeVisible();

  const neighbor = page
    .locator("[data-explorer-nodes] .explorer-node[data-is-center='false']")
    .first();
  await neighbor.click();

  await expect(page.locator("[data-explorer-evidence-drawer]")).toBeHidden();
});

test("a different edge's evidence replaces the previous edge's content", async ({
  page,
}) => {
  await page.goto("/explore/master-107325/");
  await waitForGraph(page);
  const edges = page.locator("[data-explorer-edges] .explorer-edge-group");
  const count = await edges.count();
  test.skip(
    count < 2,
    "this real center doesn't have a second edge to compare against",
  );

  await edges.nth(0).click();
  const firstContent = await page
    .locator("[data-explorer-evidence-content]")
    .innerHTML();

  await edges.nth(1).click();
  await expect
    .poll(() => page.locator("[data-explorer-evidence-content]").innerHTML())
    .not.toBe(firstContent);
});

test("the drawer degrades gracefully when the evidence registry fetch fails", async ({
  page,
}) => {
  await page.route("**/data/evidence/release-registry.v1.json", (route) =>
    route.abort(),
  );
  await page.goto("/explore/master-107325/");
  await waitForGraph(page);
  await firstEdge(page).click();

  // Still shows names/roles/source link even without title/year/cover.
  const content = page.locator("[data-explorer-evidence-content]");
  await expect(
    content.locator("a[href*='discogs.com/release/']"),
  ).toBeVisible();
  await expect(content).toContainText(
    /co-credited on the same documented release/i,
  );
});
