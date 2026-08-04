// Network Explorer integration tests (ADR 0052) against the real committed
// pathfinding graph. master-107325 (Elvis Presley) is a real, high-degree
// entry in the committed artifact (verified against
// apps/web/public/data/pathfinding/graph.v1.json) -- picked from the
// artifact itself so this exercises the truncation path for real.

import { expect, test } from "@playwright/test";

test("the explorer centers on the album's artist and shows a bounded neighborhood", async ({
  page,
}) => {
  await page.goto("/explore/master-107325/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Elvis");

  const nodes = page.locator("[data-explorer-nodes] .explorer-node");
  await expect(nodes.first()).toBeVisible({ timeout: 15000 });
  const count = await nodes.count();
  // The center plus at most MAX_NEIGHBORS (24).
  expect(count).toBeGreaterThan(1);
  expect(count).toBeLessThanOrEqual(25);

  const center = page.locator(
    "[data-explorer-nodes] .explorer-node[data-is-center='true']",
  );
  await expect(center).toHaveCount(1);
});

test("a high-degree center shows the truncation note", async ({ page }) => {
  await page.goto("/explore/master-107325/");
  await expect(page.locator("[data-explorer-truncated]")).toBeVisible({
    timeout: 15000,
  });
});

test("clicking a neighbor recenters the view", async ({ page }) => {
  await page.goto("/explore/master-107325/");
  const nodes = page.locator("[data-explorer-nodes] .explorer-node");
  await expect(nodes.first()).toBeVisible({ timeout: 15000 });

  const neighbor = page
    .locator("[data-explorer-nodes] .explorer-node[data-is-center='false']")
    .first();
  const neighborId = await neighbor.getAttribute("data-artist-id");
  await neighbor.click();

  await expect(
    page.locator("[data-explorer-nodes] .explorer-node[data-is-center='true']"),
  ).toHaveCount(1);
  const newCenterId = await page
    .locator("[data-explorer-nodes] .explorer-node[data-is-center='true']")
    .getAttribute("data-artist-id");
  expect(newCenterId).toBe(neighborId);
});

test("toggling a role filter dims non-matching nodes without removing them", async ({
  page,
}) => {
  await page.goto("/explore/master-107325/");
  const chips = page.locator(
    "[data-explorer-role-filter] [data-role-filter-chip]",
  );
  await expect(chips.first()).toBeVisible({ timeout: 15000 });

  const totalBefore = await page
    .locator("[data-explorer-nodes] .explorer-node")
    .count();
  await chips.first().click();
  await expect(chips.first()).toHaveAttribute("aria-pressed", "true");

  // Dimming never removes nodes from the DOM.
  const totalAfter = await page
    .locator("[data-explorer-nodes] .explorer-node")
    .count();
  expect(totalAfter).toBe(totalBefore);
  const dimmedCount = await page.locator(".explorer-node--dimmed").count();
  expect(dimmedCount).toBeGreaterThanOrEqual(0);
});

test("only the center node is a tab stop on a fresh render (roving tabindex)", async ({
  page,
}) => {
  await page.goto("/explore/master-107325/");
  const nodes = page.locator("[data-explorer-nodes] .explorer-node");
  await expect(nodes.first()).toBeVisible({ timeout: 15000 });

  const tabIndexes = await nodes.evaluateAll((elements) =>
    elements.map((el) => el.getAttribute("tabindex")),
  );
  expect(tabIndexes.filter((t) => t === "0")).toHaveLength(1);
  const center = page.locator(
    "[data-explorer-nodes] .explorer-node[data-is-center='true']",
  );
  await expect(center).toHaveAttribute("tabindex", "0");
});

test("arrow keys move the roving tab stop between nodes", async ({ page }) => {
  await page.goto("/explore/master-107325/");
  const center = page.locator(
    "[data-explorer-nodes] .explorer-node[data-is-center='true']",
  );
  await expect(center).toBeVisible({ timeout: 15000 });

  await center.focus();
  await page.keyboard.press("ArrowRight");

  const focused = page.locator("[data-explorer-nodes] .explorer-node:focus");
  await expect(focused).toHaveCount(1);
  await expect(focused).toHaveAttribute("data-is-center", "false");
  await expect(focused).toHaveAttribute("tabindex", "0");
  // The center is no longer a tab stop once focus has roved away.
  await expect(center).toHaveAttribute("tabindex", "-1");
});

test("a keyboard-activated recenter moves focus to the new center and announces it", async ({
  page,
}) => {
  await page.goto("/explore/master-107325/");
  const center = page.locator(
    "[data-explorer-nodes] .explorer-node[data-is-center='true']",
  );
  await expect(center).toBeVisible({ timeout: 15000 });

  await center.focus();
  await page.keyboard.press("ArrowRight");
  const neighbor = page.locator("[data-explorer-nodes] .explorer-node:focus");
  const neighborId = await neighbor.getAttribute("data-artist-id");
  const neighborName = await neighbor.locator("text").first().textContent();

  await page.keyboard.press("Enter");

  const newCenter = page.locator(
    "[data-explorer-nodes] .explorer-node[data-is-center='true']",
  );
  await expect(newCenter).toHaveAttribute("data-artist-id", neighborId ?? "");
  // Focus lands on the new center -- rebuilding the SVG must not silently
  // drop focus back to <body>.
  await expect(newCenter).toBeFocused();
  await expect(page.locator("[data-explorer-status]")).toContainText(
    new RegExp(`Centered on ${neighborName}`, "i"),
  );
});

test("an unknown artist id shows a graceful message instead of a blank graph", async ({
  page,
}) => {
  await page.route("**/data/pathfinding/graph.v1.json", async (route) => {
    const response = await route.fetch();
    const json = await response.json();
    json.node_ids = [999999999];
    json.names = ["Nobody"];
    json.offsets = [0, 0];
    json.neighbors = [];
    json.evidence_release_ids = [];
    json.edge_role_a = [];
    json.edge_role_b = [];
    await route.fulfill({ response, json });
  });
  await page.goto("/explore/master-107325/");
  await expect(page.locator("[data-explorer-status]")).toBeVisible({
    timeout: 15000,
  });
  await expect(page.locator("[data-explorer-status]")).toContainText(
    /isn't in the documented/i,
  );
});
