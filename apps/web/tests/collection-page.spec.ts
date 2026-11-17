// Renders the Collection pages against a SYNTHETIC collection (Atlas S3).
//
// Runs its own isolated build (NP_TEST_OUT_DIR=dist-test-collections, never
// the real dist/) with NP_COLLECTIONS_DIR pointing at a collection generated
// at test time (helpers/collectionFixture.ts), plus its own preview server on
// port 4323. See src/data/collections.ts for the seam and its production guard.

import AxeBuilder from "@axe-core/playwright";
import { execSync, spawn, type ChildProcess } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { collectionsDirectory } from "../src/data/collections";
import {
  generateCollectionFixture,
  SYNTHETIC_COLLECTION_ID,
  SYNTHETIC_INTRO,
  SYNTHETIC_TITLE,
  type CollectionFixture,
} from "./helpers/collectionFixture";

const webRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const PORT = 4323;
const BASE_URL = `http://127.0.0.1:${PORT}`;
const OUT_DIR = "dist-test-collections";
const PAGE = `${BASE_URL}/collections/${SYNTHETIC_COLLECTION_ID}/`;

let previewProcess: ChildProcess | undefined;
let fixture: CollectionFixture;

async function waitForServer(url: string, timeoutMs: number): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let lastError: unknown;
  while (Date.now() < deadline) {
    try {
      if ((await fetch(url)).ok) return;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(`Server at ${url} never became ready: ${String(lastError)}`);
}

test.beforeAll(async () => {
  test.setTimeout(120_000);
  fixture = generateCollectionFixture(webRoot);
  execSync("npx astro build", {
    cwd: webRoot,
    env: {
      ...process.env,
      NP_TEST_OUT_DIR: OUT_DIR,
      NP_COLLECTIONS_DIR: fixture.dir,
    },
    stdio: "pipe",
  });
  previewProcess = spawn(
    "npx",
    ["astro", "preview", "--port", String(PORT), "--host", "127.0.0.1"],
    {
      cwd: webRoot,
      env: { ...process.env, NP_TEST_OUT_DIR: OUT_DIR },
      stdio: "pipe",
      detached: true,
    },
  );
  await waitForServer(PAGE, 30_000);
});

test.afterAll(async () => {
  if (!previewProcess || previewProcess.pid === undefined) return;
  const pid = previewProcess.pid;
  const exited = new Promise<void>((resolve) => {
    previewProcess!.once("exit", () => resolve());
  });
  try {
    process.kill(-pid, "SIGTERM");
  } catch {
    return;
  }
  await Promise.race([
    exited,
    new Promise((resolve) => setTimeout(resolve, 5_000)),
  ]);
  try {
    process.kill(-pid, 0);
    process.kill(-pid, "SIGKILL");
  } catch {
    // group already empty
  }
});

test("the collections directory override is refused without an isolated test output", () => {
  expect(() => collectionsDirectory({ NP_COLLECTIONS_DIR: "x" })).toThrow(
    /test-only/,
  );
  expect(collectionsDirectory({})).toMatch(/public\/data\/collections$/);
  expect(
    collectionsDirectory({ NP_COLLECTIONS_DIR: "x", NP_TEST_OUT_DIR: "y" }),
  ).toMatch(/x$/);
});

test("the collection page shows title, intro, records, bridge players, journey and pairs", async ({
  page,
}) => {
  await page.goto(PAGE);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    SYNTHETIC_TITLE,
  );
  await expect(page.locator("[data-collection-intro]")).toHaveText(
    SYNTHETIC_INTRO,
  );

  const cards = page.locator("[data-collection-records] .album-card");
  await expect(cards).toHaveCount(fixture.recordIds.length);
  for (const [i, id] of fixture.recordIds.entries()) {
    await expect(cards.nth(i)).toHaveAttribute("href", `/albums/${id}/`);
  }

  await expect(page.locator("[data-bridge-player]")).toHaveCount(2);
  await expect(
    page.locator(
      `[data-bridge-player='${fixture.linkedPlayerId}'] a[href='/contributors/${fixture.linkedPlayerId}/']`,
    ),
  ).toHaveText("Synthetic Player A");
  // A player with no page is plain text, never a dead link.
  await expect(
    page.locator(`[data-bridge-player='${fixture.unlinkedPlayerId}'] a`),
  ).toHaveCount(0);

  const hops = page.locator("[data-journey-hop]");
  await expect(hops).toHaveCount(3);
  await expect(hops.nth(0).locator("[data-evidence-link]")).toHaveAttribute(
    "href",
    `https://www.discogs.com/release/${fixture.evidenceIds[0]}`,
  );
  // A single shared performer has no evidence pair and says so.
  await expect(hops.nth(2)).toContainText("One player is credited on both");
  await expect(hops.nth(2).locator("[data-evidence-link]")).toHaveCount(0);
  // The first hop's first player is credited on the first record: role shown.
  await expect(
    hops
      .nth(0)
      .locator(
        `[data-journey-player='${fixture.linkedPlayerId}'] .journey-hop__role`,
      ),
  ).toBeVisible();

  await expect(page.locator("[data-pair-link]").first()).toHaveAttribute(
    "href",
    `/play/connect/?a=${fixture.recordIds[0]}&b=${fixture.recordIds[2]}`,
  );

  const text = (await page.locator("main").innerText()).toLowerCase();
  for (const phrase of [
    "my collection",
    "my records",
    "worked with",
    "collaborated with",
    "influenced",
  ]) {
    expect(text).not.toContain(phrase);
  }
});

test("the collections index lists the collection and the footer links to it", async ({
  page,
}) => {
  await page.goto(`${BASE_URL}/collections/`);
  await expect(
    page.locator(
      `[data-collection-id='${SYNTHETIC_COLLECTION_ID}'] a[href='/collections/${SYNTHETIC_COLLECTION_ID}/']`,
    ),
  ).toBeVisible();
  await expect(page.locator("footer a[href='/collections/']")).toBeVisible();
  const sitemap = await (await fetch(`${BASE_URL}/sitemap.xml`)).text();
  expect(sitemap).toContain(`/collections/${SYNTHETIC_COLLECTION_ID}/`);
});

test("the collection page works without JavaScript", async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  await page.goto(PAGE);
  await expect(page.locator("[data-journey-hop]")).toHaveCount(3);
  await expect(page.locator("[data-pair-link]").first()).toBeVisible();
  await context.close();
});

for (const theme of ["dark", "light"] as const) {
  test(`the collection page has no axe violations in the ${theme} theme`, async ({
    page,
  }) => {
    await page.addInitScript((t) => {
      try {
        window.localStorage.setItem("networked-players-theme", t);
      } catch {
        // storage unavailable: the default theme applies
      }
    }, theme);
    await page.goto(PAGE);
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa"])
      .analyze();
    expect(
      results.violations,
      JSON.stringify(results.violations, null, 2),
    ).toEqual([]);
  });
}

test("the collection page does not scroll horizontally at 390px", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await page.goto(PAGE);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});
