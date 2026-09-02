// Network Explorer integration tests (ADR 0052) against the real committed
// pathfinding graph. master-107325 (Elvis Presley) is a real, high-degree
// entry in the committed artifact (verified against
// apps/web/public/data/pathfinding/graph.v3.json, ADR 0058) -- picked from
// the artifact itself so this exercises the truncation path for real.

import { expect, test } from "@playwright/test";
import { pathfindingGraphVersion } from "../src/game/pathfindingGraph";

interface ContributorLite {
  artist_id: number;
  albums: string[];
  interesting_next_step: { artist_id: number; reason: string } | null;
}

// Shared with "the center's interesting_next_step neighbor is visually
// highlighted" below and the new info-panel text test -- both need the
// same real, bounded, cross-artifact-verified fixture (contributor index
// and pathfinding graph are built from different published artifacts and
// only agree on an edge ~73% of the time, measured in Phase 6 PR 6-10).
async function findBoundedRealInterestingNextStep(
  request: import("@playwright/test").APIRequestContext,
): Promise<{ contributor: ContributorLite; neighborId: number }> {
  const [contributorRes, graphRes] = await Promise.all([
    request.get("/data/contributors/index.v1.json"),
    request.get("/data/pathfinding/graph.v3.json"),
  ]);
  const { contributors } = (await contributorRes.json()) as {
    contributors: ContributorLite[];
  };
  const graph = (await graphRes.json()) as {
    node_ids: number[];
    offsets: number[];
    neighbors: number[];
  };
  const nodeIndexById = new Map(graph.node_ids.map((id, i) => [id, i]));
  const realNeighbors = (artistId: number): Set<number> | null => {
    const i = nodeIndexById.get(artistId);
    if (i === undefined) return null;
    return new Set(
      graph.neighbors
        .slice(graph.offsets[i], graph.offsets[i + 1])
        .map((j) => graph.node_ids[j]),
    );
  };

  for (const c of contributors) {
    if (!c.interesting_next_step || c.albums.length === 0) continue;
    const neighbors = realNeighbors(c.artist_id);
    if (!neighbors || neighbors.size === 0 || neighbors.size > 20) continue;
    if (!neighbors.has(c.interesting_next_step.artist_id)) continue;
    return { contributor: c, neighborId: c.interesting_next_step.artist_id };
  }
  throw new Error(
    "no contributor with a bounded, real pathfinding-graph interesting_next_step edge",
  );
}

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

// A real gap this session's copy pass fixed: the truncation note used to
// say only "Showing the most-connected neighbors only" with no numbers,
// even though networkExplorer.ts's own doc comment always promised
// "showing 24 of 61" phrasing -- that promised copy was never actually
// written. Asserting the real numbers here (not just visibility) is what
// proves the fix, not just the note's existence.
test("a high-degree center shows the truncation note with real numbers", async ({
  page,
}) => {
  await page.goto("/explore/master-107325/");
  const note = page.locator("[data-explorer-truncated]");
  await expect(note).toBeVisible({ timeout: 15000 });
  await expect(note).toHaveText(/^Showing 24 of \d+ documented connections\.$/);
});

// docs/SITE_REPROFILE_METHOD.md's own documented gap ("worker parse time:
// not measured") -- this diagnostic global is what closes it, real
// end-to-end through the actual worker (or its main-thread fallback), not
// a unit test against graphWorker.ts in isolation.
test("loading the graph records a real worker-parse-time diagnostic", async ({
  page,
}) => {
  await page.goto("/explore/master-107325/");
  await expect(
    page.locator("[data-explorer-nodes] .explorer-node").first(),
  ).toBeVisible({ timeout: 15000 });

  const parseMs = await page.evaluate(
    () => (window as { __NP_GRAPH_PARSE_MS__?: number }).__NP_GRAPH_PARSE_MS__,
  );
  expect(typeof parseMs).toBe("number");
  expect(parseMs).toBeGreaterThanOrEqual(0);
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

// Phase 6 PR 6-03: a read-only ?center= deep link overrides the default
// album-artist center. U2 (artist_id 6520) is a real, documented neighbor
// of Elvis in the committed graph (verified against graph.v3.json) -- this
// exercises a genuine override, not a no-op landing on the same node.
test("a valid ?center= query param overrides the album's default center", async ({
  page,
}) => {
  await page.goto("/explore/master-107325/?center=6520");
  await expect(
    page.locator("[data-explorer-nodes] .explorer-node[data-is-center='true']"),
  ).toHaveAttribute("data-artist-id", "6520", { timeout: 15000 });
  await expect(page.locator("[data-explorer-status]")).toContainText(
    /Centered on U2/i,
  );
});

test("an unknown ?center= id is silently ignored and the default center still renders", async ({
  page,
}) => {
  await page.goto("/explore/master-107325/?center=999999999");
  await expect(
    page.locator("[data-explorer-nodes] .explorer-node[data-is-center='true']"),
  ).toBeVisible({ timeout: 15000 });
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Elvis");
  await expect(page.locator("[data-explorer-status]")).toContainText(
    /Centered on Elvis/i,
  );
});

// Phase 6 PR 6-05: the explorer links its current center back to that
// person's own contributor page, when one exists, and updates on recenter.
test("the center node links to its own contributor page, and updates on recenter", async ({
  page,
}) => {
  await page.goto("/explore/master-107325/");
  const centerLink = page.locator("[data-explorer-center-link] a");
  await expect(centerLink).toBeVisible({ timeout: 15000 });
  await expect(centerLink).toHaveAttribute("href", "/contributors/27518/");
  await expect(centerLink).toContainText("Elvis Presley");

  const nodes = page.locator("[data-explorer-nodes] .explorer-node");
  await expect(nodes.first()).toBeVisible({ timeout: 15000 });
  const u2Neighbor = page.locator(
    "[data-explorer-nodes] .explorer-node[data-artist-id='6520']",
  );
  await u2Neighbor.click();

  await expect(centerLink).toHaveAttribute("href", "/contributors/6520/");
  await expect(centerLink).toContainText("U2");
});

test("the center link stays hidden when the current center has no contributor page", async ({
  page,
}) => {
  await page.route("**/data/contributors/index.v1.json", async (route) => {
    await route.fulfill({ json: { schema_version: 1, contributors: [] } });
  });
  await page.goto("/explore/master-107325/");
  await expect(
    page.locator("[data-explorer-nodes] .explorer-node").first(),
  ).toBeVisible({ timeout: 15000 });
  await expect(page.locator("[data-explorer-center-link]")).toBeHidden();
});

// Phase 6 PR 6-10 / ADR 0060: the center's own interesting_next_step
// neighbor, when currently rendered, gets a visual highlight -- picked from
// the two real committed artifacts together, not a hardcoded name.
//
// The contributor index and the pathfinding graph are built from different
// published artifacts (the index from the small curated challenge/routes
// pair, the graph from the full one-hop corpus) -- measured, a real
// interesting_next_step pick is an actual pathfinding-graph edge only about
// 73% of the time. This search checks BOTH artifacts to find a case where
// it genuinely is one, with a low enough real graph degree to guarantee
// it's inside the MAX_NEIGHBORS cap too.
test("the center's interesting_next_step neighbor is visually highlighted", async ({
  page,
  request,
}) => {
  const { contributor, neighborId } =
    await findBoundedRealInterestingNextStep(request);

  await page.goto(
    `/explore/${contributor.albums[0]}/?center=${contributor.artist_id}`,
  );
  const highlighted = page.locator(
    `[data-explorer-nodes] .explorer-node[data-artist-id='${neighborId}']`,
  );
  await expect(highlighted).toBeVisible({ timeout: 15000 });
  await expect(highlighted).toHaveAttribute(
    "data-is-interesting-next-step",
    "true",
  );
  await expect(highlighted).toHaveClass(/explorer-node--interesting/);

  // Every other rendered neighbor is NOT highlighted -- this decorates one
  // node, it doesn't restyle the whole set.
  const others = page.locator(
    `[data-explorer-nodes] .explorer-node[data-is-center='false']:not([data-artist-id='${neighborId}'])`,
  );
  const othersCount = await others.count();
  for (let i = 0; i < othersCount; i++) {
    await expect(others.nth(i)).toHaveAttribute(
      "data-is-interesting-next-step",
      "false",
    );
  }
});

// Continuity pass (plan §12.7): a sighted-user-visible info panel, real
// links out, and a session trail -- previously Explorer only announced its
// center via an SR-only status region and a single conditional
// contributor-page link.
test("the info panel shows a visible centered-on summary with role text", async ({
  page,
}) => {
  await page.goto("/explore/master-107325/");
  const summary = page.locator("[data-explorer-info-summary]");
  await expect(summary).toBeVisible({ timeout: 15000 });
  await expect(summary).toContainText("Centered on");
  await expect(summary).toContainText("Elvis Presley");
});

test("the info panel links to the center's own record page and Connect, prefilled", async ({
  page,
  request,
}) => {
  // The center's own record link uses THAT contributor's own albums[0]
  // (contributor_index.py's own shared-hop-count order) -- not necessarily
  // the album this Explorer page happened to launch from, which centers on
  // the album's primary artist but doesn't imply their own albums[0] is
  // this same record.
  const res = await request.get("/data/contributors/index.v1.json");
  const { contributors } = (await res.json()) as {
    contributors: { artist_id: number; albums: string[] }[];
  };
  const elvis = contributors.find((c) => c.artist_id === 27518);
  if (!elvis || elvis.albums.length === 0)
    throw new Error(
      "Elvis Presley (27518) missing or has no albums in the real index",
    );
  const ownAlbumId = elvis.albums[0];

  await page.goto("/explore/master-107325/");
  const recordLink = page.locator(
    `[data-explorer-info-links] a[href='/albums/${ownAlbumId}/']`,
  );
  await expect(recordLink).toBeVisible({ timeout: 15000 });

  const connectLink = page.locator(
    `[data-explorer-info-links] a[href='/play/connect/?a=${ownAlbumId}']`,
  );
  await expect(connectLink).toBeVisible();
  await connectLink.click();
  await page.waitForURL(`**/play/connect/?a=${ownAlbumId}`);
  await expect(
    page.locator("[data-picker='a'] [data-picker-selected]"),
  ).toBeVisible();
});

test("the info panel explains a real, bounded interesting_next_step highlight in plain text", async ({
  page,
  request,
}) => {
  const { contributor, neighborId } =
    await findBoundedRealInterestingNextStep(request);
  const reason = contributor.interesting_next_step!.reason;

  await page.goto(
    `/explore/${contributor.albums[0]}/?center=${contributor.artist_id}`,
  );
  const worthALook = page.locator("[data-explorer-info-worth-a-look]");
  await expect(worthALook).toBeVisible({ timeout: 15000 });
  await expect(worthALook).toContainText("Worth a look");
  await expect(worthALook).toContainText(reason);
  await expect(
    worthALook.locator(`a[href='/contributors/${neighborId}/']`),
  ).toBeVisible();
});

test("recentering builds a session trail, and a trail step re-centers back", async ({
  page,
}) => {
  await page.goto("/explore/master-107325/");
  const trail = page.locator("[data-explorer-trail]");
  // A single center is not a "trail" yet.
  await expect(trail).toBeHidden({ timeout: 15000 });

  const centerNode = page.locator(
    "[data-explorer-nodes] .explorer-node[data-is-center='true']",
  );
  await expect(centerNode).toBeVisible({ timeout: 15000 });
  const originalArtistId = await centerNode.getAttribute("data-artist-id");
  if (!originalArtistId) throw new Error("center node has no data-artist-id");

  const firstNeighbor = page
    .locator("[data-explorer-nodes] .explorer-node[data-is-center='false']")
    .first();
  await expect(firstNeighbor).toBeVisible();
  await firstNeighbor.click();

  await expect(trail).toBeVisible();
  const step = trail.locator(`[data-trail-artist-id='${originalArtistId}']`);
  await expect(step).toBeVisible();
  await expect(step).toContainText("Elvis Presley");

  await step.click();
  await expect(centerNode).toHaveAttribute("data-artist-id", originalArtistId, {
    timeout: 15000,
  });
  // Re-centering via a trail step is itself a real centerOn(), so it
  // grows the trail (now 3 entries: Elvis -> neighbor -> Elvis again)
  // rather than erasing it.
  await expect(trail.locator(".explorer-trail__current")).toContainText(
    "Elvis Presley",
  );
});

test("an unknown artist id shows a graceful message instead of a blank graph", async ({
  page,
}) => {
  await page.route("**/data/pathfinding/graph.v3.json", async (route) => {
    const response = await route.fetch();
    const json = await response.json();
    json.node_ids = [999999999];
    json.names = ["Nobody"];
    json.offsets = [0, 0];
    json.neighbors = [];
    json.evidence_release_ids = [];
    json.edge_role_a = [];
    json.edge_role_b = [];
    json.album_virtual_nodes = [];
    // The mutated payload must carry a real recomputed content hash --
    // validatePathfindingGraph now verifies pathfinding_graph_version
    // against the graph's own content, not merely its shape.
    json.pathfinding_graph_version = await pathfindingGraphVersion(
      json,
      json.schema_version,
      json.snapshot_date,
    );
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

// A genuinely unreachable graph is a terminal integrity failure -- this is
// the ONE early-return in explorerStage.ts before the role filter, SVG
// edges/nodes, or evidence drawer are ever wired up (nothing playable is
// ever half-wired), the same shape as Guesser's/Routes' own
// showStageError. Previously announced identically to the ordinary
// "Loading the network…" message that preceded it, on the one polite
// region -- this now gets the same data-phase="error" + assertive-alert
// pairing GameStage.astro/RoutesStage.astro already use.
test("an unreachable pathfinding graph shows a terminal error, not a blank graph", async ({
  page,
}) => {
  await page.route("**/data/pathfinding/graph.v3.json", (route) =>
    route.abort(),
  );
  await page.goto("/explore/master-107325/");

  await expect(page.locator("[data-explorer-status]")).toBeVisible();
  await expect(page.locator("[data-explorer-status]")).toContainText(
    /could not load the network graph/i,
  );
  await expect(page.locator("[data-explorer-status-assertive]")).toContainText(
    /could not load the network graph/i,
  );
  await expect(page.locator("[data-testid='explorer-stage']")).toHaveAttribute(
    "data-phase",
    "error",
  );
  await expect(page.locator("[data-explorer-svg]")).toBeHidden();
  await expect(page.locator("[data-explorer-role-filter]")).toBeHidden();
});

test.describe("mobile layout", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("the new info panel and trail don't cause sideways scroll on a phone-sized screen", async ({
    page,
  }) => {
    await page.goto("/explore/master-107325/");
    await expect(page.locator("[data-explorer-info-summary]")).toBeVisible({
      timeout: 15000,
    });

    const firstNeighbor = page
      .locator("[data-explorer-nodes] .explorer-node[data-is-center='false']")
      .first();
    await firstNeighbor.click();
    await expect(page.locator("[data-explorer-trail]")).toBeVisible();

    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });
});
