// Network Explorer evidence drawer (ADR 0058 Slice 9): clicking, hovering,
// or keyboard-activating an edge shows real release/role evidence, joined
// against the evidence-release registry (ADR 0058 Slice 3) via the same
// renderEvidenceHop() Connect Two Records already uses. Real, committed
// data throughout -- master-107325 (Elvis Presley) is the same real,
// high-degree seed game-networkexplorer.spec.ts already uses.
//
// Edges are dispatched to directly (dispatchEvent/evaluate), not clicked
// via Playwright's normal actionability-gated .click()/.hover(): the
// circular layout (networkExplorer.ts's neighborPosition) places the first
// neighbor directly above the center, making that edge's <line> a perfect
// vertical with a zero-width bounding box -- genuinely rendered and
// hit-testable in a real browser (SVG stroke hit-testing isn't limited to
// the geometric bbox), but Playwright's toBeVisible()/click() require a
// non-empty bounding box. dispatchEvent fires the exact same DOM event the
// real delegated listener on `edgesLayer` handles either way.

import { expect, test } from "@playwright/test";

async function waitForGraph(page: import("@playwright/test").Page) {
  await expect(
    page.locator("[data-explorer-nodes] .explorer-node").first(),
  ).toBeVisible({ timeout: 15000 });
}

function firstEdge(page: import("@playwright/test").Page) {
  return page.locator("[data-explorer-edges] .explorer-edge").first();
}

test("clicking an edge shows real evidence in the drawer", async ({ page }) => {
  await page.goto("/explore/master-107325/");
  await waitForGraph(page);
  await firstEdge(page).dispatchEvent("click");

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

test("hovering an edge shows the drawer without a click", async ({ page }) => {
  await page.goto("/explore/master-107325/");
  await waitForGraph(page);
  await firstEdge(page).dispatchEvent("mouseover");

  await expect(page.locator("[data-explorer-evidence-drawer]")).toBeVisible();
  await expect(page.locator("[data-explorer-evidence-content]")).toContainText(
    /co-credited on the same documented release/i,
  );
});

test("an edge is keyboard-reachable and Enter opens the same evidence", async ({
  page,
}) => {
  await page.goto("/explore/master-107325/");
  await waitForGraph(page);
  const edge = firstEdge(page);
  await expect(edge).toHaveAttribute("tabindex", "0");

  await edge.evaluate((el) =>
    (el as SVGElement & { focus: () => void }).focus(),
  );
  await page.keyboard.press("Enter");

  await expect(page.locator("[data-explorer-evidence-drawer]")).toBeVisible();
  await expect(page.locator("[data-explorer-evidence-content]")).toContainText(
    /co-credited on the same documented release/i,
  );
});

test("the close button hides the drawer", async ({ page }) => {
  await page.goto("/explore/master-107325/");
  await waitForGraph(page);
  await firstEdge(page).dispatchEvent("click");
  await expect(page.locator("[data-explorer-evidence-drawer]")).toBeVisible();

  await page.locator("[data-explorer-evidence-close]").click();
  await expect(page.locator("[data-explorer-evidence-drawer]")).toBeHidden();
});

test("Escape hides the drawer", async ({ page }) => {
  await page.goto("/explore/master-107325/");
  await waitForGraph(page);
  await firstEdge(page).dispatchEvent("click");
  await expect(page.locator("[data-explorer-evidence-drawer]")).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(page.locator("[data-explorer-evidence-drawer]")).toBeHidden();
});

test("recentering the graph closes the drawer", async ({ page }) => {
  await page.goto("/explore/master-107325/");
  await waitForGraph(page);
  await firstEdge(page).dispatchEvent("click");
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
  const edges = page.locator("[data-explorer-edges] .explorer-edge");
  const count = await edges.count();
  test.skip(
    count < 2,
    "this real center doesn't have a second edge to compare against",
  );

  await edges.nth(0).dispatchEvent("click");
  const firstContent = await page
    .locator("[data-explorer-evidence-content]")
    .innerHTML();

  await edges.nth(1).dispatchEvent("click");
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
  await firstEdge(page).dispatchEvent("click");

  // Still shows names/roles/source link even without title/year/cover.
  const content = page.locator("[data-explorer-evidence-content]");
  await expect(
    content.locator("a[href*='discogs.com/release/']"),
  ).toBeVisible();
  await expect(content).toContainText(
    /co-credited on the same documented release/i,
  );
});
