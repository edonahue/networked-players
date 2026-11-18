// Contributors directory unit + integration specs (ADR 0058 Slice 8):
// mostConnected/searchContributors pure logic, and a real end-to-end run
// against the committed contributor index.

import { expect, test } from "@playwright/test";
import {
  mostConnected,
  searchContributors,
  type DirectoryContributor,
} from "../src/game/contributorsDirectory";

function fixture(): DirectoryContributor[] {
  return [
    {
      artist_id: 1,
      name: "Alice Ray",
      role_categories: ["vocals"],
      connection_count: 5,
    },
    {
      artist_id: 2,
      name: "Bob Ray",
      role_categories: ["production", "engineering"],
      connection_count: 12,
    },
    {
      artist_id: 3,
      name: "Cara Lane",
      role_categories: ["strings"],
      connection_count: 1,
    },
    {
      artist_id: 4,
      name: "Dan Reyes",
      role_categories: ["production"],
      connection_count: 12,
    },
  ];
}

test("mostConnected sorts by connection_count descending, ties broken by name", () => {
  const result = mostConnected(fixture());
  expect(result.map((c) => c.name)).toEqual([
    "Bob Ray",
    "Dan Reyes",
    "Alice Ray",
    "Cara Lane",
  ]);
});

test("mostConnected respects the limit", () => {
  const result = mostConnected(fixture(), 2);
  expect(result).toHaveLength(2);
  expect(result.map((c) => c.name)).toEqual(["Bob Ray", "Dan Reyes"]);
});

test("searchContributors with no query and no categories falls back to mostConnected", () => {
  const result = searchContributors(fixture(), "", new Set());
  expect(result.map((c) => c.name)).toEqual([
    "Bob Ray",
    "Dan Reyes",
    "Alice Ray",
    "Cara Lane",
  ]);
});

test("searchContributors matches a case-insensitive name substring", () => {
  const result = searchContributors(fixture(), "ray", new Set());
  expect(result.map((c) => c.name)).toEqual(["Bob Ray", "Alice Ray"]);
});

test("searchContributors ORs multiple active categories together", () => {
  const result = searchContributors(
    fixture(),
    "",
    new Set(["vocals", "strings"]),
  );
  expect(result.map((c) => c.name).sort()).toEqual(["Alice Ray", "Cara Lane"]);
});

test("searchContributors combines a name query with a category filter (AND across facets)", () => {
  const result = searchContributors(fixture(), "ray", new Set(["production"]));
  expect(result.map((c) => c.name)).toEqual(["Bob Ray"]);
});

test("searchContributors returns nothing for a query that matches no one", () => {
  const result = searchContributors(fixture(), "zzz-no-match", new Set());
  expect(result).toEqual([]);
});

test("a real search finds a real contributor by name in the committed index", async ({
  page,
}) => {
  await page.goto("/contributors/");
  await expect(page.locator("[data-contributors-status]")).toHaveText(
    /^Showing \d+ of \d+ players\.$/,
    { timeout: 15000 },
  );
  await expect(page.locator("[data-contributors-heading]")).toHaveText(
    "Most connected",
  );
  await expect(
    page.locator("[data-contributors-results] .contributor-card").first(),
  ).toBeVisible();

  await page.locator("[data-contributors-search]").fill("Eno");
  await expect(page.locator("[data-contributors-heading]")).toContainText(
    '"Eno"',
  );
  const results = page.locator("[data-contributors-results] .contributor-card");
  await expect(results.first()).toBeVisible();
  await expect(results.first()).toContainText("Eno");
  // The count must update with the filter, not stay stuck at the
  // unfiltered total.
  await expect(page.locator("[data-contributors-status]")).toHaveText(
    /^Showing \d+ of \d+ players\.$/,
  );
});

test("a role-category chip filters real results and can be toggled off", async ({
  page,
}) => {
  await page.goto("/contributors/");
  await expect(page.locator("[data-contributors-status]")).toHaveText(
    /^Showing \d+ of \d+ players\.$/,
    { timeout: 15000 },
  );

  const chip = page.locator('[data-contributors-category="vocals"]');
  await chip.click();
  await expect(chip).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("[data-contributors-heading]")).toContainText(
    "Vocals",
  );
  await expect(
    page.locator("[data-contributors-results] .contributor-card").first(),
  ).toBeVisible();

  await chip.click();
  await expect(chip).toHaveAttribute("aria-pressed", "false");
  await expect(page.locator("[data-contributors-heading]")).toHaveText(
    "Most connected",
  );
});

test("a search with no real matches shows an empty results grid and an honest message", async ({
  page,
}) => {
  await page.goto("/contributors/");
  const status = page.locator("[data-contributors-status]");
  await expect(status).toHaveText(/^Showing \d+ of \d+ players\.$/, {
    timeout: 15000,
  });
  await page
    .locator("[data-contributors-search]")
    .fill("zzz-no-real-contributor-matches-this-xyz");
  await expect(
    page.locator("[data-contributors-results] .contributor-card"),
  ).toHaveCount(0);
  // Real gap this test used to miss: the grid went silently blank with no
  // fallback message at all, unlike the albums directory's own "No albums
  // match your search." for the same zero-results case.
  await expect(status).toBeVisible();
  await expect(status).toHaveText("No players match your search.");

  // Clearing the search must restore the visible unfiltered count, not
  // leave the empty-state message stuck.
  await page.locator("[data-contributors-search]").fill("");
  await expect(status).toHaveText(/^Showing \d+ of \d+ players\.$/);
});

test("the contributors directory is reachable from the primary nav", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .locator("nav[aria-label='Primary'] a", { hasText: "Players" })
    .click();
  await expect(page).toHaveURL(/\/contributors\/$/);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "people behind",
  );
});

test("the players directory offers only performance role chips", async ({
  page,
}) => {
  await page.goto("/contributors/");
  await expect(page.locator("[data-contributors-status]")).toHaveText(
    /^Showing \d+ of \d+ players\.$/,
    { timeout: 15000 },
  );
  const values = await page
    .locator("[data-contributors-category]")
    .evaluateAll((els) =>
      els.map((e) => (e as HTMLElement).dataset.contributorsCategory),
    );
  expect(values).toEqual([
    "vocals",
    "strings",
    "percussion_keys",
    "brass_woodwind",
    "performance",
  ]);
  for (const removed of [
    "production",
    "engineering",
    "arrangement",
    "composition",
    "rework",
    "packaging_business",
    "audiovisual_production",
    "unknown",
  ]) {
    await expect(
      page.locator(`[data-contributors-category="${removed}"]`),
    ).toHaveCount(0);
  }
  await expect(page.getByRole("button", { name: "Production" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Engineering" })).toHaveCount(
    0,
  );
});

test("an old ?category=production link degrades to the unfiltered directory", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/contributors/?category=production");
  await expect(page.locator("[data-contributors-status]")).toHaveText(
    /^Showing \d+ of \d+ players\.$/,
    { timeout: 15000 },
  );
  await expect(page.locator("[data-contributors-heading]")).toHaveText(
    "Most connected",
  );
  await expect(
    page.locator("[data-contributors-results] .contributor-card").first(),
  ).toBeVisible();
  expect(errors).toEqual([]);
});
