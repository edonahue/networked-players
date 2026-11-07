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
  // The drawer reports settled state only once the real card is in the DOM.
  await expect(drawer).toHaveAttribute("data-evidence-state", "ready", {
    timeout: 15000,
  });
  await expect(drawer).toHaveAttribute("aria-busy", "false");
  const content = page.locator("[data-explorer-evidence-content]");
  await expect(content).toContainText(
    /documented performing on the same release/i,
  );
  await expect(
    content.locator("a[href*='discogs.com/release/']"),
  ).toBeVisible();
});

// Phase 6 PR 6-06: the drawer's two hop names link to their own contributor
// page when one is published -- shared logic with Connect
// (enhanceHopContributorLinks), general property test against the real
// contributor index rather than a hardcoded name.
test("evidence drawer hop names link to their own contributor page when one is published", async ({
  page,
  request,
}) => {
  const res = await request.get("/data/contributors/index.v1.json");
  const { contributors } = (await res.json()) as {
    contributors: { artist_id: number }[];
  };
  const contributorIds = new Set(contributors.map((c) => c.artist_id));

  await page.goto("/explore/master-107325/");
  await waitForGraph(page);
  // Root cause of this test's long-running intermittent CI failure
  // ("Expected: 0, Received: 1" on a hop-name link), found 2026-11-07: the
  // first edge renders below the fold, and click()'s own scroll-into-view
  // moves the graph under the cursor, so Chromium's hover handling could
  // open a DIFFERENT edge (instrumented: neighbor 293221 instead of the
  // clicked 52833 in 5 of 8 runs) and swap the drawer content between the
  // per-name reads below. Never a dead link: every rendered link was on a
  // real contributor. Scroll first, wait for the settled drawer, prove it
  // shows the edge that was clicked, and read names + links in one
  // atomic snapshot.
  const edge = firstEdge(page);
  await edge.scrollIntoViewIfNeeded();
  const neighborId = await edge.getAttribute("data-neighbor-id");
  await edge.click();

  const drawer = page.locator("[data-explorer-evidence-drawer]");
  await expect(drawer).toHaveAttribute("data-evidence-state", "ready", {
    timeout: 15000,
  });
  const content = page.locator("[data-explorer-evidence-content]");
  await expect(content).toContainText(
    /documented performing on the same release/i,
  );
  await expect(
    content.locator(`[data-hop-artist-id="${neighborId}"]`),
  ).toHaveCount(1);

  const names = await content
    .locator("[data-hop-artist-id]")
    .evaluateAll((els) =>
      els.map((el) => ({
        artistId: Number(el.getAttribute("data-hop-artist-id")),
        hrefs: [...el.querySelectorAll("a")].map((a) => a.getAttribute("href")),
      })),
    );
  expect(names).toHaveLength(2);

  let linkedAtLeastOne = false;
  for (const { artistId, hrefs } of names) {
    if (contributorIds.has(artistId)) {
      expect(hrefs).toEqual([`/contributors/${artistId}/`]);
      linkedAtLeastOne = true;
    } else {
      expect(hrefs).toEqual([]);
    }
  }
  // Elvis (the center, artist_id 27518) is always one of the two names on
  // his own high-degree first edge, and always has a real contributor page
  // -- this pair genuinely exercises the linking behavior, not a vacuous
  // "nothing had a page" pass.
  expect(linkedAtLeastOne).toBe(true);
});

async function hopArtistIds(page: import("@playwright/test").Page) {
  return page
    .locator("[data-explorer-evidence-content] [data-hop-artist-id]")
    .evaluateAll((els) =>
      els.map((el) => el.getAttribute("data-hop-artist-id")),
    );
}

// Regression for the root cause above: after a click, focus moving into the
// drawer scrolls the page, and whatever edge then slides under the UNMOVED
// cursor must not replace the evidence that was explicitly chosen. Made
// deterministic by scrolling until a different edge sits exactly under the
// click point, instead of relying on the focus scroll happening to land one
// there.
test("an edge scrolled under a stationary cursor never replaces clicked evidence", async ({
  page,
}) => {
  await page.goto("/explore/master-107325/");
  await waitForGraph(page);
  const edge = firstEdge(page);
  await edge.scrollIntoViewIfNeeded();
  const clickedId = await edge.getAttribute("data-neighbor-id");
  const box = (await edge.boundingBox())!;
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await page.mouse.click(x, y);
  const drawer = page.locator("[data-explorer-evidence-drawer]");
  await expect(drawer).toHaveAttribute("data-evidence-state", "ready", {
    timeout: 15000,
  });
  expect(await hopArtistIds(page)).toContain(clickedId);

  // Find a scroll offset that puts some OTHER edge directly under (x, y).
  const dy = await page.evaluate(
    ([px, py, clicked]) => {
      for (let d = -600; d <= 600; d += 4) {
        const yy = py + d;
        if (yy < 0 || yy >= window.innerHeight) continue;
        const g = document
          .elementFromPoint(px, yy)
          ?.closest<HTMLElement>(".explorer-edge-group");
        if (g && g.dataset.neighborId !== clicked) return d;
      }
      return null;
    },
    [x, y, clickedId] as const,
  );
  expect(dy, "some other edge must be reachable by scrolling").not.toBeNull();
  await page.evaluate((d) => window.scrollBy(0, d), dy!);
  await expect
    .poll(() =>
      page.evaluate(
        ([px, py]) =>
          document
            .elementFromPoint(px, py)
            ?.closest<HTMLElement>(".explorer-edge-group")?.dataset.neighborId,
        [x, y] as const,
      ),
    )
    .not.toBe(clickedId);
  // Chromium's hover update for the scroll lands asynchronously; give it
  // real time to (wrongly) fire before asserting it was ignored.
  await page.waitForTimeout(500);
  expect(await hopArtistIds(page)).toContain(clickedId);
});

// The fix above must not cost real hover-to-preview: after a click, actually
// moving the pointer onto a different edge still previews that edge.
test("hovering a different edge after a click still previews it", async ({
  page,
}) => {
  await page.goto("/explore/master-107325/");
  await waitForGraph(page);
  const edges = page.locator("[data-explorer-edges] .explorer-edge-group");
  const first = edges.first();
  await first.scrollIntoViewIfNeeded();
  await first.click();
  const drawer = page.locator("[data-explorer-evidence-drawer]");
  await expect(drawer).toHaveAttribute("data-evidence-state", "ready", {
    timeout: 15000,
  });

  const firstId = await first.getAttribute("data-neighbor-id");
  // Pick another edge whose hit-area centre really is that edge (not hidden
  // under an overlapping neighbour), then genuinely move the pointer to it.
  await first.scrollIntoViewIfNeeded();
  const target = await edges.evaluateAll((els, skip) => {
    for (const el of els as HTMLElement[]) {
      if (el.dataset.neighborId === skip) continue;
      const r = el.getBoundingClientRect();
      const cx = r.x + r.width / 2;
      const cy = r.y + r.height / 2;
      if (cy < 0 || cy >= window.innerHeight) continue;
      const hit = document
        .elementFromPoint(cx, cy)
        ?.closest<HTMLElement>(".explorer-edge-group");
      if (hit === el) return { id: el.dataset.neighborId!, cx, cy };
    }
    return null;
  }, firstId);
  expect(target, "another directly hoverable edge must exist").not.toBeNull();
  await page.mouse.move(target!.cx, target!.cy, { steps: 5 });
  await expect
    .poll(() => hopArtistIds(page), { timeout: 15000 })
    .toContain(target!.id);
});

// The drawer's advertised state must distinguish "open but still fetching"
// from "open and settled" -- a visitor (and a screen reader, via aria-busy)
// otherwise cannot tell a slow load from an empty result.
test("the drawer reports loading state until the evidence registry resolves", async ({
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
  await waitForGraph(page);
  await firstEdge(page).click();

  const drawer = page.locator("[data-explorer-evidence-drawer]");
  await expect(drawer).toBeVisible();
  await expect(drawer).toHaveAttribute("data-evidence-state", "loading");
  await expect(drawer).toHaveAttribute("aria-busy", "true");
  await expect(page.locator("[data-explorer-evidence-content]")).toContainText(
    /loading evidence/i,
  );

  releaseRegistry();
  await expect(drawer).toHaveAttribute("data-evidence-state", "ready", {
    timeout: 15000,
  });
  await expect(drawer).toHaveAttribute("aria-busy", "false");
});

// Request invalidation on close (P2 follow-up after #109). Closing the
// drawer while its evidence fetch is still in flight must make that fetch's
// eventual resolution a no-op -- otherwise a slow registry response that
// lands after dismissal resurrects data-evidence-state/aria-busy/content on
// a drawer the visitor already closed. Each case gates the registry fetch,
// performs the invalidating action, and only THEN releases the response, so
// releasing after closure is what proves the guard actually holds.
async function gateEvidenceRegistry(
  page: import("@playwright/test").Page,
): Promise<{
  // Releases the gate AND waits for the real network response plus one real
  // round-trip through the page's own event loop (a live CDP `evaluate`,
  // not a fixed sleep) -- so by the time this resolves, showEdgeEvidence's
  // suspended continuation has genuinely had its one chance to run its
  // requestId guard and either write to the DOM or return early. Checking
  // the terminal state immediately after `release()` with no such wait
  // would pass even on the unfixed code, since the continuation's DOM
  // write is itself async and might not have happened yet.
  releaseAndSettle: () => Promise<void>;
}> {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  // Awaited, not fire-and-forget: page.route()'s own promise resolves once
  // interception is actually installed. A caller that navigated before that
  // completed could have its request race ahead of the gate -- the registry
  // fetch resolving immediately instead of staying pending, silently
  // defeating every assertion downstream.
  await page.route(
    "**/data/evidence/release-registry.v1.json",
    async (route) => {
      await gate;
      await route.continue();
    },
  );
  return {
    async releaseAndSettle() {
      release();
      const response = await page.waitForResponse(
        "**/data/evidence/release-registry.v1.json",
      );
      // Read the full ~3.3MB body, not just headers -- `waitForResponse`
      // alone resolves once the response starts arriving, well before the
      // page's own fetch()+response.json() has finished parsing it, and
      // showEdgeEvidence's continuation (guard check + DOM write) doesn't
      // run until that parse completes.
      await response.json();
      // Flush the page's own microtask queue: a macrotask scheduled from
      // inside the page is guaranteed to run only after every microtask
      // already queued there (including that fetch/parse/guard-check
      // continuation) has drained.
      await page.evaluate(
        () => new Promise((resolve) => setTimeout(resolve, 0)),
      );
    },
  };
}

async function assertDrawerClosedAndUntouched(
  page: import("@playwright/test").Page,
): Promise<void> {
  const drawer = page.locator("[data-explorer-evidence-drawer]");
  await expect(drawer).toBeHidden();
  await expect(drawer).not.toHaveAttribute("data-evidence-state", /.*/);
  await expect(drawer).not.toHaveAttribute("aria-busy", /.*/);
  await expect(page.locator("[data-explorer-evidence-content]")).toBeEmpty();
}

test("closing via the close button during loading discards the pending evidence", async ({
  page,
}) => {
  const { releaseAndSettle } = await gateEvidenceRegistry(page);
  await page.goto("/explore/master-107325/");
  await waitForGraph(page);
  const edge = firstEdge(page);
  await edge.click();

  const drawer = page.locator("[data-explorer-evidence-drawer]");
  await expect(drawer).toHaveAttribute("data-evidence-state", "loading");

  await page.locator("[data-explorer-evidence-close]").click();
  await expect(edge).toBeFocused();

  await releaseAndSettle();
  await assertDrawerClosedAndUntouched(page);
  await expect(edge).toBeFocused();
});

test("dismissing via Escape during loading discards the pending evidence", async ({
  page,
}) => {
  const { releaseAndSettle } = await gateEvidenceRegistry(page);
  await page.goto("/explore/master-107325/");
  await waitForGraph(page);
  const edge = firstEdge(page);
  await edge.click();

  const drawer = page.locator("[data-explorer-evidence-drawer]");
  await expect(drawer).toHaveAttribute("data-evidence-state", "loading");

  await page.keyboard.press("Escape");
  await expect(edge).toBeFocused();

  await releaseAndSettle();
  await assertDrawerClosedAndUntouched(page);
  await expect(edge).toBeFocused();
});

test("recentering during loading discards the pending evidence for the old view", async ({
  page,
}) => {
  const { releaseAndSettle } = await gateEvidenceRegistry(page);
  await page.goto("/explore/master-107325/");
  await waitForGraph(page);
  await firstEdge(page).click();

  const drawer = page.locator("[data-explorer-evidence-drawer]");
  await expect(drawer).toHaveAttribute("data-evidence-state", "loading");

  // Move the mouse off the graph, and activate the neighbor via keyboard
  // (not .click()), BEFORE the recentering mutation happens. Recentering
  // rebuilds the whole SVG; per this file's own header note on Chromium
  // redelivering a synthetic mouseover for whatever's under the cursor's
  // last known position after a DOM mutation, that synthetic event fires
  // based on where the cursor was AT THE MOMENT OF the mutation -- moving
  // the mouse away only after clicking (and thus only after triggering the
  // mutation) is too late, since the browser already captured the old
  // position. A stray hover landing on a real edge in the new view would
  // legitimately (if noisily) open it, which isn't a bug this test should
  // catch; route around the same Chromium quirk the edge-B test documents,
  // this time by keeping the mouse off the graph for the entire action.
  await page.mouse.move(0, 0);
  const neighbor = page
    .locator("[data-explorer-nodes] .explorer-node[data-is-center='false']")
    .first();
  await neighbor.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("[data-explorer-status]")).toContainText(
    /^centered on /i,
  );

  await releaseAndSettle();
  // The old edge's evidence must never appear on the new, recentered view.
  await assertDrawerClosedAndUntouched(page);
});

test("a newer edge's open invalidates an older edge's still-pending evidence", async ({
  page,
}) => {
  const { releaseAndSettle } = await gateEvidenceRegistry(page);
  await page.goto("/explore/master-107325/");
  await waitForGraph(page);
  const edges = page.locator("[data-explorer-edges] .explorer-edge-group");
  const count = await edges.count();
  // master-107325 is documented (this file's own header) as a real,
  // high-degree center -- 1696 real edges in the committed graph.v3.json,
  // capped at 24 in the DOM. A hard precondition, not a skip: if this ever
  // drops below 2, the fixture itself has changed and this test's premise
  // needs revisiting, not a silently-skipped CI run.
  expect(count).toBeGreaterThanOrEqual(2);

  await edges.nth(0).click();
  const drawer = page.locator("[data-explorer-evidence-drawer]");
  await expect(drawer).toHaveAttribute("data-evidence-state", "loading");

  // Move the mouse off the graph before activating edge B. Opening the
  // drawer shifts layout; per this file's own earlier note on Chromium
  // redelivering a synthetic mouseover for whatever's now under a
  // stationary cursor's last known position, leaving the mouse resting at
  // edge A's old screen coordinates can make a real post-shift synthetic
  // hover land on a completely unrelated edge and win the race against our
  // own explicit activation below -- not a real user gesture, and not
  // anything Finding A's fix governs, just a Chromium quirk to route
  // around. .focus() + Enter (not .click()) for edge B itself, since
  // .focus() never dispatches mouse events at all, so Enter deterministically
  // activates edges.nth(1) specifically rather than whatever a mouse click's
  // approach path happened to cross.
  await page.mouse.move(0, 0);
  const expectedReleaseId = await edges.nth(1).getAttribute("data-release-id");
  await edges.nth(1).focus();
  await page.keyboard.press("Enter");
  await expect(drawer).toHaveAttribute("data-evidence-state", "loading");

  // Both edges share one gated registry fetch; releasing it resolves A's
  // and B's continuations together -- only B's request id is still current.
  await releaseAndSettle();
  await expect(drawer).toHaveAttribute("data-evidence-state", "ready", {
    timeout: 15000,
  });
  const content = page.locator("[data-explorer-evidence-content]");
  // Exactly one hop -- not a mix of A's and B's content.
  await expect(content.locator(".connect-hop")).toHaveCount(1);
  await expect(
    content.locator(`a[href*='discogs.com/release/${expectedReleaseId}']`),
  ).toBeVisible();
});

test("a fresh explicit open works after a previous pending request was invalidated by a close", async ({
  page,
}) => {
  const { releaseAndSettle } = await gateEvidenceRegistry(page);
  await page.goto("/explore/master-107325/");
  await waitForGraph(page);
  const edge = firstEdge(page);
  await edge.click();
  await expect(page.locator("[data-explorer-evidence-drawer]")).toHaveAttribute(
    "data-evidence-state",
    "loading",
  );

  await page.locator("[data-explorer-evidence-close]").click();
  await releaseAndSettle();
  await assertDrawerClosedAndUntouched(page);

  // A genuinely new explicit activation must still work -- the registry
  // promise is cached and already resolved, so this settles immediately.
  await edge.click();
  const drawer = page.locator("[data-explorer-evidence-drawer]");
  await expect(drawer).toHaveAttribute("data-evidence-state", "ready", {
    timeout: 15000,
  });
  await expect(
    page.locator("[data-explorer-evidence-content] .connect-hop"),
  ).toBeVisible();
});

// Closing the drawer clears the state entirely -- `hidden` already means
// closed, so a stale "ready" must not linger on a dismissed drawer.
test("closing the drawer clears its evidence state", async ({ page }) => {
  await page.goto("/explore/master-107325/");
  await waitForGraph(page);
  await firstEdge(page).click();

  const drawer = page.locator("[data-explorer-evidence-drawer]");
  await expect(drawer).toHaveAttribute("data-evidence-state", "ready", {
    timeout: 15000,
  });

  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await expect(drawer).not.toHaveAttribute("data-evidence-state", /.*/);
  await expect(drawer).not.toHaveAttribute("aria-busy", /.*/);
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
    /documented performing on the same release/i,
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
    /documented performing on the same release/i,
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

// Regression test for the fix to the flake above: the suppression that
// stops a recenter's own synthetic mouseover from reopening the drawer
// clears on the next macrotask (a one-shot `setTimeout(0)`), not on the
// next real mouse movement specifically -- either way, a visitor who
// recenters and then genuinely hovers a new edge must still see
// hover-to-preview work, immediately, without needing an intervening
// click/Enter.
test("hovering a new edge after recentering still opens the drawer", async ({
  page,
}) => {
  await page.goto("/explore/master-107325/");
  await waitForGraph(page);
  await firstEdge(page).click();
  await expect(page.locator("[data-explorer-evidence-drawer]")).toBeVisible();

  const neighbor = page
    .locator("[data-explorer-nodes] .explorer-node[data-is-center='false']")
    .first();
  await neighbor.click();
  await expect(page.locator("[data-explorer-evidence-drawer]")).toBeHidden();

  await firstEdge(page).hover();
  await expect(page.locator("[data-explorer-evidence-drawer]")).toBeVisible();
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

  // Still shows names/roles/source link even without title/year/cover, and
  // says so honestly: settled, but without release metadata.
  const drawer = page.locator("[data-explorer-evidence-drawer]");
  await expect(drawer).toHaveAttribute("data-evidence-state", "unavailable", {
    timeout: 15000,
  });
  await expect(drawer).toHaveAttribute("aria-busy", "false");
  const content = page.locator("[data-explorer-evidence-content]");
  await expect(
    content.locator("a[href*='discogs.com/release/']"),
  ).toBeVisible();
  await expect(content).toContainText(
    /documented performing on the same release/i,
  );
});
