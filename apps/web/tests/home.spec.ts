// Homepage (Atlas P3). Everything asserted here is derived from the
// published artifacts, never from hardcoded album or person names.

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext } from "@playwright/test";
import { isPerformerRole } from "../src/game/roleTaxonomy";

interface Credit {
  artist_id: number;
  name: string;
  role_text: string | null;
  credit_scope: string;
}

async function membership(request: APIRequestContext) {
  const res = await request.get("/data/albums/credit-membership.v1.json");
  const body = (await res.json()) as {
    albums: { album_id: string; credits: Credit[] }[];
  };
  return new Map(body.albums.map((a) => [a.album_id, a.credits]));
}

function performers(credits: Credit[] | undefined): Set<number> {
  return new Set(
    (credits ?? [])
      .filter(
        (c) =>
          c.credit_scope !== "release_artist" &&
          isPerformerRole(c.role_text ?? ""),
      )
      .map((c) => c.artist_id),
  );
}

test("the primary action lands in Explore on a record that exists, and names it", async ({
  page,
  request,
}) => {
  const cta = page.getByTestId("home-explore-cta");
  await page.goto("/");
  const href = await cta.getAttribute("href");
  const match = /^\/explore\/([^/]+)\/$/.exec(href ?? "");
  expect(match).not.toBeNull();
  const id = match![1];

  const challenge = (await (
    await request.get("/data/challenge.v3.json")
  ).json()) as { albums: { id: string; title: string }[] };
  const album = challenge.albums.find((a) => a.id === id);
  expect(album).toBeTruthy();
  await expect(cta).toContainText(album!.title);

  await cta.click();
  await page.waitForURL(`**/explore/${id}/`);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    album!.title,
  );
});

test("the landing record has the most onward connections in the catalog", async ({
  page,
  request,
}) => {
  await page.goto("/");
  const id = /\/explore\/([^/]+)\//.exec(
    (await page.getByTestId("home-explore-cta").getAttribute("href")) ?? "",
  )![1];
  const challenge = (await (
    await request.get("/data/challenge.v3.json")
  ).json()) as { albums: { id: string; artist_id: number }[] };
  const credits = await membership(request);
  const perf = new Map(
    challenge.albums.map((a) => [a.id, performers(credits.get(a.id))]),
  );
  const count = (a: { id: string; artist_id: number }) =>
    challenge.albums.filter(
      (o) =>
        o.id !== a.id &&
        o.artist_id !== a.artist_id &&
        [...perf.get(a.id)!].some((p) => perf.get(o.id)!.has(p)),
    ).length;
  const best = Math.max(...challenge.albums.map(count));
  const chosen = challenge.albums.find((a) => a.id === id)!;
  expect(count(chosen)).toBe(best);
});

test("the featured pair's shared players are credited performers on both records", async ({
  page,
  request,
}) => {
  await page.goto("/");
  const example = page.getByTestId("home-example");
  await expect(example).toBeVisible();
  const cards = example.locator(".album-card");
  await expect(cards).toHaveCount(2);
  const ids = [
    await cards.nth(0).getAttribute("data-album-id"),
    await cards.nth(1).getAttribute("data-album-id"),
  ] as string[];

  const connect = example.locator("a[href^='/play/connect/']");
  await expect(connect).toHaveAttribute(
    "href",
    `/play/connect/?a=${ids[0]}&b=${ids[1]}`,
  );

  const credits = await membership(request);
  const a = performers(credits.get(ids[0]));
  const b = performers(credits.get(ids[1]));
  const sharedIds = [...a].filter((x) => b.has(x));
  expect(sharedIds.length).toBeGreaterThan(0);

  // Every named player is one of the real shared performers, and the
  // "and N more" count accounts for the rest.
  const names = new Map<number, string>();
  for (const id of ids)
    for (const c of credits.get(id) ?? [])
      names.set(c.artist_id, c.name.replace(/\s+\(\d+\)$/, ""));
  const sharedNames = new Set(sharedIds.map((x) => names.get(x)));
  const text = (await example.getByTestId("home-shared").innerText())
    .replace(/^Documented performing on both:\s*/, "")
    .replace(/\.$/, "");
  const more = /\s+and (\d+) more$/.exec(text);
  const shown = text
    .replace(/\s+and \d+ more$/, "")
    .split(", ")
    .filter(Boolean);
  for (const name of shown) expect(sharedNames).toContain(name);
  // The homepage counts only players credited outside the string section on
  // both records (data/homeFeatures.ts), so the displayed total can be smaller
  // than the full shared-performer set, never larger, and never empty.
  const displayedTotal = shown.length + (more ? Number(more[1]) : 0);
  expect(displayedTotal).toBeGreaterThan(0);
  expect(displayedTotal).toBeLessThanOrEqual(sharedIds.length);
});

test("the rule is stated once, near the top, and all four games are present", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByTestId("home-rule")).toContainText(
    "Producers and engineers appear in the credits, but don't make a connection.",
  );
  const play = page.getByTestId("home-play");
  for (const href of [
    "/play/daily/",
    "/play/connect/",
    "/play/routes/",
    "/play/connection/",
  ]) {
    await expect(play.locator(`a[href='${href}']`)).toHaveCount(1);
  }
});

for (const theme of ["dark", "light"] as const) {
  test(`axe: homepage, ${theme} theme`, async ({ page }) => {
    await page.addInitScript(
      (t) => window.localStorage.setItem("networked-players-theme", t),
      theme,
    );
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    const results = await new AxeBuilder({ page }).analyze();
    expect(
      results.violations,
      JSON.stringify(
        results.violations.map((v) => [v.id, v.nodes.map((n) => n.target)]),
      ),
    ).toEqual([]);
  });
}

test.describe("390px", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("the homepage has no horizontal scroll and the primary action is a 44px target", async ({
    page,
  }) => {
    await page.goto("/");
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
    const box = await page.getByTestId("home-explore-cta").boundingBox();
    expect(box!.height).toBeGreaterThanOrEqual(44);
    expect(box!.width).toBeLessThanOrEqual(390);
  });
});
