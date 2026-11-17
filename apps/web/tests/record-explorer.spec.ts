// Record-centred Explore prototype (Campaign Atlas G2 / experiment E3), behind
// /explore/<album>/?mode=record. The gate: labelled nodes <= 24 and no
// overlapping label boxes on dense real records (picked by rule from the
// committed artifacts, never named), plus keyboard, evidence, recenter, theme
// and 390px checks. Recenter TIMINGS are measured locally only (ADR 0018) and
// written under local/benchmarks/, never asserted or committed.

import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { catalogAlbums, readArtifact } from "./helpers/catalogFacts";
import {
  buildRecordView,
  MAX_LABELLED_NODES,
  type RecordAlbum,
} from "../src/data/recordExplorer";
import type { Membership } from "../src/data/albumRecord";
import { catalogFacts } from "./helpers/catalogFacts";

const membership = readArtifact<Membership>("albums/credit-membership.v1.json");
const prominence = readArtifact<{ node_ids: number[]; rank: number[] }>(
  "pathfinding/prominence.v1.json",
);
const rank = new Map(
  prominence.node_ids.map((id, i) => [id, prominence.rank[i]]),
);
const albums = catalogAlbums as RecordAlbum[];

// Dense = most labelled nodes (players + records), then most ring-2 records;
// ties by album id (catalogAlbums is id-sorted). Picks 3 by rule.
const DENSE = albums
  .map((a) => ({ a, v: buildRecordView(membership, albums, rank, a.id)! }))
  .filter(({ v }) => v && v.players.length > 0 && v.records.length > 0)
  .sort(
    (x, y) =>
      y.v.players.length +
        y.v.records.length -
        (x.v.players.length + x.v.records.length) ||
      y.v.records.length - x.v.records.length,
  )
  .slice(0, 3)
  .map(({ a }) => a);

async function open(page: Page, id: string, extra = "") {
  await page.goto(`/explore/${id}/?mode=record${extra}`);
  await expect(page.locator("[data-record-explorer]")).toHaveAttribute(
    "data-phase",
    "ready",
    { timeout: 20000 },
  );
}

async function labelBoxes(page: Page) {
  return page.$$eval("[data-record-nodes] .record-label", (els) =>
    els.map((e) => {
      const r = e.getBoundingClientRect();
      return { text: e.textContent, x: r.x, y: r.y, w: r.width, h: r.height };
    }),
  );
}

function overlaps(
  a: { x: number; y: number; w: number; h: number },
  b: { x: number; y: number; w: number; h: number },
) {
  return (
    a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h
  );
}

test("the gate picks 3 dense records by rule", () => {
  expect(DENSE).toHaveLength(3);
});

for (const [label, viewport] of [
  ["desktop", { width: 1280, height: 900 }],
  ["390px", { width: 390, height: 844 }],
] as const) {
  test(`dense records: <= 24 labelled nodes, no overlapping labels (${label})`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    for (const album of DENSE) {
      await open(page, album.id);
      const nodes = await page
        .locator("[data-record-nodes] .record-node")
        .count();
      expect(nodes).toBeLessThanOrEqual(MAX_LABELLED_NODES);
      expect(nodes).toBeGreaterThan(10);
      const boxes = await labelBoxes(page);
      expect(boxes.length).toBe(nodes);
      for (let i = 0; i < boxes.length; i++) {
        for (let j = i + 1; j < boxes.length; j++) {
          expect(
            overlaps(boxes[i], boxes[j]),
            `${album.id}: "${boxes[i].text}" overlaps "${boxes[j].text}"`,
          ).toBe(false);
        }
      }
      // Labels stay inside the drawn graph, and at 390px no horizontal scroll.
      const svgBox = (await page.locator("[data-record-svg]").boundingBox())!;
      for (const b of boxes) {
        expect(b.x).toBeGreaterThanOrEqual(svgBox.x - 1);
        expect(b.x + b.w).toBeLessThanOrEqual(svgBox.x + svgBox.width + 1);
      }
      const noHScroll = await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      );
      expect(noHScroll).toBe(true);
      // Legible: rendered label font is at least 9px.
      const px = await page.$eval(
        "[data-record-nodes] .record-label",
        (e) => e.getBoundingClientRect().height,
      );
      expect(px).toBeGreaterThanOrEqual(9);
    }
  });
}

test("a player opens credit evidence; a record recenters with history; keyboard works", async ({
  page,
}) => {
  const album = DENSE[0];
  await open(page, album.id);

  // Keyboard: focus first player, Enter opens evidence, Escape returns focus.
  const firstPlayer = page.locator("[data-kind='player']").first();
  await firstPlayer.focus();
  await page.keyboard.press("Enter");
  const drawer = page.locator("[data-record-drawer]");
  await expect(drawer).toBeVisible();
  await expect(drawer).toBeFocused();
  await expect(
    drawer.locator("a[href*='discogs.com/release/']").first(),
  ).toBeVisible();
  await expect(drawer).toContainText(/documented performance credits/i);
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await expect(firstPlayer).toBeFocused();

  // Arrow keys move the roving focus.
  await page.keyboard.press("ArrowRight");
  await expect(
    page.locator("[data-kind='player'], [data-kind='record']").nth(1),
  ).toBeFocused();

  // Recenter on a ring-2 record.
  const record = page.locator("[data-kind='record']").first();
  const targetId = await record.getAttribute("data-album-id");
  await record.locator("circle").click();
  await expect(page.locator("[data-record-explorer]")).toHaveAttribute(
    "data-centre-album-id",
    targetId!,
  );
  expect(page.url()).toContain(`record=${targetId}`);
  expect(page.url()).toContain("mode=record");
  await page.goBack();
  await expect(page.locator("[data-record-explorer]")).toHaveAttribute(
    "data-centre-album-id",
    album.id,
  );
});

test("static fallback lists the same data without JavaScript", async ({
  browser,
}) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  await page.goto(`/explore/${DENSE[0].id}/?mode=record`);
  const html = await page.content();
  expect(html).toContain("Other records these players are documented on");
  await context.close();
});

for (const theme of ["dark", "light"] as const) {
  test(`record mode has no axe violations (${theme}, with drawer open)`, async ({
    page,
  }) => {
    await open(page, DENSE[0].id);
    if (theme === "light") {
      await page.locator("[data-theme-toggle]").click();
      await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    }
    await page.locator("[data-kind='player'] circle").first().click();
    await expect(page.locator("[data-record-drawer]")).toBeVisible();
    const results = await new AxeBuilder({ page }).analyze();
    expect(
      results.violations,
      results.violations
        .map(
          (v) =>
            `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`,
        )
        .join("\n"),
    ).toEqual([]);
  });
}

// Local-only measurement (ADR 0018): wall-clock from the click to the new
// centre being drawn, both modes, written to local/benchmarks/ (git-ignored).
// No timing is asserted.
test("local timing: recenter, record mode vs artist star", async ({ page }) => {
  test.setTimeout(120000);
  const facts = await catalogFacts();
  const samples: Record<string, number[]> = { record: [], artist: [] };
  for (let run = 0; run < 5; run++) {
    await open(page, DENSE[0].id);
    const target = page.locator("[data-kind='record']").first();
    const id = (await target.getAttribute("data-album-id"))!;
    const t0 = Date.now();
    await target.locator("circle").click();
    await expect(page.locator("[data-record-explorer]")).toHaveAttribute(
      "data-centre-album-id",
      id,
    );
    samples.record.push(Date.now() - t0);

    await page.goto(`/explore/${facts.explorer.album.id}/`);
    const node = page
      .locator(
        "[data-explorer-nodes] .explorer-node:not([data-is-center='true'])",
      )
      .first();
    await expect(node).toBeVisible({ timeout: 20000 });
    const before = await page
      .locator("[data-explorer-nodes] [data-is-center='true']")
      .getAttribute("data-artist-id");
    const t1 = Date.now();
    await node.click();
    await expect
      .poll(() =>
        page
          .locator("[data-explorer-nodes] [data-is-center='true']")
          .getAttribute("data-artist-id"),
      )
      .not.toBe(before);
    samples.artist.push(Date.now() - t1);
  }
  const dir = join(process.cwd(), "..", "..", "local", "benchmarks");
  mkdirSync(dir, { recursive: true });
  writeFileSync(
    join(dir, "g2-recenter-timing.json"),
    JSON.stringify(
      {
        measured: new Date().toISOString(),
        method: "click to centre drawn, 5 runs, local preview server, ms",
        samples,
      },
      null,
      2,
    ),
  );
});
