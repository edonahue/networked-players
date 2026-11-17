// Default Explore artist-star view: labels must never overlap each other or
// any node circle, at desktop and phone widths, including after "Show 24
// more". Records are the densest by rule (denseExplorerAlbums), never named.

import { expect, test, type Page } from "@playwright/test";
import { denseExplorerAlbums } from "./helpers/catalogFacts";

interface Box {
  text: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

function overlaps(a: Box, b: Box) {
  return (
    a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h
  );
}

async function boxes(page: Page) {
  return page.$$eval("[data-explorer-nodes] .explorer-node", (nodes) => {
    const rect = (e: Element, text: string) => {
      const r = e.getBoundingClientRect();
      return { text, x: r.x, y: r.y, w: r.width, h: r.height };
    };
    return nodes.map((n) => ({
      label: rect(n.querySelector("text")!, n.textContent?.trim() ?? ""),
      circle: rect(n.querySelector("circle")!, "circle"),
    }));
  });
}

async function assertClean(page: Page, id: string, phase: string) {
  const all = await boxes(page);
  const svg = (await page.locator("[data-explorer-svg]").boundingBox())!;
  for (let i = 0; i < all.length; i++) {
    const { label } = all[i];
    expect(
      label.x,
      `${id} ${phase}: "${label.text}" left of svg`,
    ).toBeGreaterThanOrEqual(svg.x - 1);
    expect(
      label.x + label.w,
      `${id} ${phase}: "${label.text}" right of svg`,
    ).toBeLessThanOrEqual(svg.x + svg.width + 1);
    for (let j = 0; j < all.length; j++) {
      if (j > i) {
        expect(
          overlaps(label, all[j].label),
          `${id} ${phase}: "${label.text}" overlaps label "${all[j].label.text}"`,
        ).toBe(false);
      }
      expect(
        overlaps(label, all[j].circle),
        `${id} ${phase}: "${label.text}" overlaps circle of "${all[j].label.text}"`,
      ).toBe(false);
    }
  }
}

for (const [name, viewport] of [
  ["1280", { width: 1280, height: 900 }],
  ["390", { width: 390, height: 844 }],
] as const) {
  test(`default Explore labels never collide (${name}px)`, async ({ page }) => {
    test.setTimeout(120000);
    const albums = await denseExplorerAlbums(3);
    expect(albums).toHaveLength(3);
    await page.setViewportSize(viewport);
    for (const album of albums) {
      await page.goto(`/explore/${album.id}/`);
      const nodes = page.locator(
        "[data-explorer-nodes] .explorer-node[data-is-center='false']",
      );
      await expect(nodes.first()).toBeVisible({ timeout: 20000 });
      expect(await nodes.count()).toBeGreaterThanOrEqual(20);
      await assertClean(page, album.id, "initial");

      const before = await nodes.count();
      await page.locator("[data-explorer-show-more]").click();
      await expect.poll(() => nodes.count()).toBeGreaterThan(before);
      await assertClean(page, album.id, "after show more");

      const noHScroll = await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      );
      expect(noHScroll).toBe(true);
    }
  });
}
