// With no Collection published (the state of every real build today) there is
// no /collections/ route and nothing links to one, and the retired synthetic
// /cohorts/ pages are gone. Runs against the normal production build.

import { existsSync, readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

const webRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const publishedDir = join(webRoot, "public/data/collections");
const published =
  existsSync(join(publishedDir, "index.v1.json")) &&
  JSON.parse(readFileSync(join(publishedDir, "index.v1.json"), "utf8"))
    .collections.length > 0;

test.describe("no collection published", () => {
  test.skip(published, "a real collection is published; absence not expected");

  test("the production build has no /collections/ or /cohorts/ routes", async ({
    request,
  }) => {
    for (const path of [
      "/collections/",
      "/cohorts/",
      "/cohorts/synthetic-example/",
    ]) {
      const response = await request.get(path, { maxRedirects: 0 });
      expect(response.status(), path).toBe(404);
    }
    const dist = join(webRoot, "dist");
    if (existsSync(dist)) {
      expect(readdirSync(dist)).not.toContain("collections");
      expect(readdirSync(dist)).not.toContain("cohorts");
    }
  });

  test("no page, sitemap or llms.txt links to /collections/ or /cohorts/", async ({
    page,
    request,
  }) => {
    for (const path of ["/", "/about/", "/play/", "/albums/"]) {
      await page.goto(path);
      await expect(
        page.locator("a[href*='/collections'], a[href*='/cohorts']"),
        path,
      ).toHaveCount(0);
    }
    for (const path of ["/sitemap.xml", "/llms.txt"]) {
      const body = await (await request.get(path)).text();
      expect(body, path).not.toMatch(/\/collections|\/cohorts/);
    }
  });
});
