// Header navigation + site-wide search (Atlas P2/P3). Queries and expected
// destinations are derived from the published search index and contributor
// index, never hardcoded names.

import AxeBuilder from "@axe-core/playwright";
import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";

interface Entry {
  kind: "album" | "contributor";
  id: string;
  label: string;
  sublabel: string | null;
}

async function loadEntries(request: APIRequestContext): Promise<Entry[]> {
  const res = await request.get("/data/search/index.v1.json");
  return ((await res.json()) as { entries: Entry[] }).entries;
}

/** A label that is unique in the index and long enough to be selective. */
function uniqueEntry(entries: Entry[], kind: Entry["kind"]): Entry {
  const counts = new Map<string, number>();
  for (const e of entries)
    counts.set(
      e.label.toLowerCase(),
      (counts.get(e.label.toLowerCase()) ?? 0) + 1,
    );
  const found = entries.find(
    (e) =>
      e.kind === kind &&
      /^[A-Za-z0-9 ]{6,24}$/.test(e.label) &&
      counts.get(e.label.toLowerCase()) === 1,
  );
  if (!found) throw new Error(`no unique ${kind} entry`);
  return found;
}

const input = (page: Page) => page.locator("[data-search-input]");

async function focusSearchWithSlash(page: Page) {
  // Wait for the module script to have enhanced the control.
  await expect(page.locator("[data-site-search].is-ready")).toHaveCount(1);
  await page.locator("body").press("/");
  await expect(input(page)).toBeFocused();
}

test("the search index is not requested before the visitor engages search", async ({
  page,
}) => {
  const urls: string[] = [];
  page.on("request", (r) => urls.push(r.url()));
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  expect(
    urls.filter(
      (u) =>
        u.includes("search/index.v1.json") || u.includes("search/details.json"),
    ),
  ).toEqual([]);
  await focusSearchWithSlash(page);
  await expect
    .poll(() => urls.some((u) => u.includes("search/index.v1.json")))
    .toBe(true);
});

test("keyboard: / focuses search, typing finds a record, Enter opens its record page", async ({
  page,
  request,
}) => {
  const entries = await loadEntries(request);
  const album = uniqueEntry(entries, "album");
  await page.goto("/");
  await focusSearchWithSlash(page);
  await input(page).fill(album.label);
  const option = page.locator("[role=option][data-kind=album]").first();
  await expect(option).toContainText(album.label);
  await expect(page.locator("[data-search-status]")).toContainText(/record/);
  await page.keyboard.press("ArrowDown");
  await expect(input(page)).toHaveAttribute(
    "aria-activedescendant",
    /site-search-opt-0/,
  );
  await page.keyboard.press("Enter");
  await page.waitForURL(`**/albums/${album.id}/`);
});

test("choosing a player lands in Explore centred on them", async ({
  page,
  request,
}) => {
  const entries = await loadEntries(request);
  const player = uniqueEntry(entries, "contributor");
  const details = (await (
    await request.get("/search/details.json")
  ).json()) as {
    players: Record<string, { album: string }>;
  };
  const info = details.players[player.id];
  expect(info).toBeTruthy();
  await page.goto("/");
  await focusSearchWithSlash(page);
  await input(page).fill(player.label);
  const options = page.locator("[role=option]");
  const n = await options.count();
  let idx = -1;
  for (let i = 0; i < n; i++) {
    if (
      (await options.nth(i).getAttribute("data-kind")) === "contributor" &&
      (await options.nth(i).innerText()).includes(player.label)
    )
      idx = i;
  }
  expect(idx).toBeGreaterThanOrEqual(0);
  for (let i = 0; i <= idx; i++) await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await page.waitForURL(`**/explore/${info.album}/?center=${player.id}`);
  await expect(
    page.locator(`[data-artist-id='${player.id}'][data-is-center='true']`),
  ).toBeVisible();
});

test("an unmatched query shows an honest empty state with real counts", async ({
  page,
  request,
}) => {
  const entries = await loadEntries(request);
  const albums = entries.filter((e) => e.kind === "album").length;
  const players = entries.filter((e) => e.kind === "contributor").length;
  await page.goto("/");
  await focusSearchWithSlash(page);
  await input(page).fill("zzqxjv");
  const message = page.locator("[data-search-message]");
  await expect(message).toContainText(
    `${albums} records and ${players} players`,
  );
  await expect(message).toContainText("and nothing else");
  await expect(
    page.locator("[data-search-empty] a[href='/albums/']"),
  ).toBeVisible();
  await expect(
    page.locator("[data-search-empty] a[href='/contributors/']"),
  ).toBeVisible();
});

test("a failed index fetch says so instead of returning nothing", async ({
  page,
}) => {
  await page.route("**/data/search/index.v1.json", (r) => r.abort());
  await page.goto("/");
  await focusSearchWithSlash(page);
  await input(page).fill("abc");
  await expect(page.locator("[data-search-message]")).toContainText(
    "couldn't load",
  );
});

test("a slow index load does not reopen results the visitor dismissed", async ({
  page,
}) => {
  let release: () => void = () => {};
  const held = new Promise<void>((resolve) => (release = resolve));
  await page.route("**/data/search/index.v1.json", async (route) => {
    await held;
    await route.continue();
  });
  await page.goto("/");
  await focusSearchWithSlash(page);
  await input(page).pressSequentially("abc");
  await page.keyboard.press("Escape");
  const settled = page.waitForResponse("**/data/search/index.v1.json");
  release();
  await settled;
  await page.waitForTimeout(300);
  await expect(page.locator("[data-search-panel]")).toBeHidden();
  // Typing again is a fresh request for results.
  await input(page).pressSequentially("d");
  await expect(page.locator("[data-search-panel]")).toBeVisible();
});

test("returning to the field after a dismissed slow load shows the results", async ({
  page,
  request,
}) => {
  const album = uniqueEntry(await loadEntries(request), "album");
  let release: () => void = () => {};
  const held = new Promise<void>((resolve) => (release = resolve));
  await page.route("**/data/search/index.v1.json", async (route) => {
    await held;
    await route.continue();
  });
  await page.goto("/");
  await focusSearchWithSlash(page);
  await input(page).fill(album.label);
  await page.locator("h1").click(); // focus leaves search while loading
  const settled = page.waitForResponse("**/data/search/index.v1.json");
  release();
  await settled;
  await page.waitForTimeout(300);
  await expect(page.locator("[data-search-panel]")).toBeHidden();
  await input(page).focus();
  await expect(page.locator("[role=option]").first()).toContainText(
    album.label,
  );
});

test("Escape closes the results", async ({ page, request }) => {
  const album = uniqueEntry(await loadEntries(request), "album");
  await page.goto("/");
  await focusSearchWithSlash(page);
  await input(page).fill(album.label);
  await expect(page.locator("[role=option]").first()).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator("[data-search-panel]")).toBeHidden();
  await expect(input(page)).toHaveAttribute("aria-expanded", "false");
});

test("/explore/ has a visible search entry that opens the header search", async ({
  page,
}) => {
  await page.goto("/explore/");
  await expect(page.locator("[data-site-search].is-ready")).toHaveCount(1);
  await page.getByTestId("explore-search-entry").click();
  await expect(input(page)).toBeFocused();
});

test.describe("390px", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("header is one row; the menu works by keyboard; no horizontal scroll", async ({
    page,
  }) => {
    await page.goto("/");
    await expect(page.locator("[data-site-search].is-ready")).toHaveCount(1);
    const header = await page.locator(".site-header").boundingBox();
    expect(header!.height).toBeLessThan(80);
    const wordmark = (await page.locator(".wordmark").boundingBox())!;
    const trigger = (await page
      .locator("[data-search-trigger]")
      .boundingBox())!;
    const menu = (await page.locator("[data-menu-toggle]").boundingBox())!;
    for (const b of [trigger, menu]) {
      expect(
        Math.abs(b.y + b.height / 2 - (wordmark.y + wordmark.height / 2)),
      ).toBeLessThan(12);
      expect(b.width).toBeGreaterThanOrEqual(44);
      expect(b.height).toBeGreaterThanOrEqual(44);
    }
    const nav = page.locator("nav[aria-label='Primary']");
    await expect(nav).toBeHidden();
    await page.locator("[data-menu-toggle]").focus();
    await page.keyboard.press("Enter");
    await expect(nav).toBeVisible();
    await expect(page.locator("[data-menu-toggle]")).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    await expect(nav.locator("a")).toHaveText([
      "Explore",
      "Records",
      "Players",
      "Play",
    ]);
    await page.keyboard.press("Escape");
    await expect(nav).toBeHidden();
    await expect(page.locator("[data-menu-toggle]")).toBeFocused();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test("search opens from the trigger and finds a record", async ({
    page,
    request,
  }) => {
    const album = uniqueEntry(await loadEntries(request), "album");
    await page.goto("/");
    await expect(page.locator("[data-site-search].is-ready")).toHaveCount(1);
    await page.locator("[data-search-trigger]").click();
    await expect(input(page)).toBeFocused();
    await input(page).fill(album.label);
    await expect(page.locator("[role=option]").first()).toContainText(
      album.label,
    );
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test("opening the menu closes the search layer, and the reverse", async ({
    page,
  }) => {
    // Both disclosures occupy the strip under the header bar; left open
    // together the search field covers the first navigation link.
    await page.goto("/");
    await expect(page.locator("[data-site-search].is-ready")).toHaveCount(1);
    await page.locator("[data-search-trigger]").click();
    await expect(page.locator("[data-site-search]")).toHaveClass(/is-open/);
    await page.locator("[data-menu-toggle]").click();
    await expect(page.locator("[data-site-search]")).not.toHaveClass(/is-open/);
    const nav = page.locator("nav[aria-label='Primary']");
    await expect(nav.locator("a").first()).toBeVisible();
    await nav.locator("a").first().click({ trial: true }); // not covered
    await page.locator("[data-search-trigger]").click();
    await expect(page.locator("[data-menu-toggle]")).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });
});

test.describe("JavaScript disabled", () => {
  test.use({ javaScriptEnabled: false });

  test("nav links and a browse fallback are present", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("nav[aria-label='Primary'] a")).toHaveText([
      "Explore",
      "Records",
      "Players",
      "Play",
    ]);
    await expect(page.locator("nav[aria-label='Primary']")).toBeVisible();
    await expect(page.locator("[data-search-fallback]")).toBeVisible();
    await expect(page.locator("[data-search-fallback]")).toHaveAttribute(
      "href",
      "/albums/",
    );
    await expect(page.locator("[data-search-input]")).toBeHidden();
  });
});

for (const theme of ["dark", "light"] as const) {
  test(`axe: open search popover, ${theme} theme`, async ({
    page,
    request,
  }) => {
    const album = uniqueEntry(await loadEntries(request), "album");
    await page.addInitScript(
      (t) => window.localStorage.setItem("networked-players-theme", t),
      theme,
    );
    await page.goto("/");
    await focusSearchWithSlash(page);
    // A short query that yields both groups where possible.
    await input(page).fill(album.label.split(" ")[0]);
    await expect(page.locator("[role=option]").first()).toBeVisible();
    await page.keyboard.press("ArrowDown");
    const results = await new AxeBuilder({ page }).analyze();
    expect(
      results.violations,
      JSON.stringify(
        results.violations.map((v) => [v.id, v.nodes.map((n) => n.target)]),
      ),
    ).toEqual([]);
  });
}
