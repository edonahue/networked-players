import { expect, test } from "@playwright/test";

test("home renders hero, nav, and the album grid", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "Pick an album",
  );
  await expect(
    page.getByRole("link", { name: "Browse the albums" }).first(),
  ).toBeVisible();
  await expect(page.locator(".album-card").first()).toBeVisible();
});

test("about page renders", async ({ page }) => {
  await page.goto("/about/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
});

test("demo renders a path with evidence and switches paths", async ({
  page,
  request,
}) => {
  // Path labels are real, curated Discogs data and change whenever the artifact is
  // regenerated -- read them from the artifact itself rather than hardcoding names.
  const res = await request.get("/data/challenge.v1.json");
  const { paths } = await res.json();
  test.skip(paths.length < 2, "need at least two paths to test switching");

  await page.goto("/demo/");
  // First path visible by default with an evidence table.
  await expect(page.locator(".path-card:not([hidden])")).toHaveCount(1);
  await expect(
    page.locator(".path-card:not([hidden]) .evidence table").first(),
  ).toBeVisible();

  // Switch to another path via the picker.
  const secondPath = paths[1];
  await page.getByRole("button", { name: secondPath.label }).click();
  const visibleCard = page.locator(".path-card:not([hidden])");
  await expect(visibleCard).toHaveCount(1);
  await expect(visibleCard).toHaveAttribute("data-path-id", secondPath.id);
});

test("theme toggle persists", async ({ page }) => {
  await page.goto("/");
  const html = page.locator("html");
  await expect(html).toHaveAttribute("data-theme", "dark");
  await page.locator("[data-theme-toggle]").click();
  await expect(html).toHaveAttribute("data-theme", "light");
  await page.reload();
  await expect(html).toHaveAttribute("data-theme", "light");
});

test("static demo artifact is reachable", async ({ request }) => {
  const res = await request.get("/data/challenge.v1.json");
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.schema_version).toBe(1);
  expect(Array.isArray(body.paths)).toBe(true);
});

test("static challenge.v2 artifact is reachable", async ({ request }) => {
  const res = await request.get("/data/challenge.v2.json");
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.schema_version).toBe(2);
  expect(Array.isArray(body.albums)).toBe(true);
  expect(Array.isArray(body.paths)).toBe(true);
});

test("a play page renders mode controls and reveals evidence", async ({
  page,
  request,
}) => {
  const res = await request.get("/data/challenge.v2.json");
  const { albums, paths } = await res.json();
  const connectedIds = new Set(
    paths.flatMap((p: { from_album_id: string; to_album_id: string }) => [
      p.from_album_id,
      p.to_album_id,
    ]),
  );
  const album = albums.find((a: { id: string }) => connectedIds.has(a.id));
  test.skip(!album, "need at least one connected album to test the play view");

  await page.goto(`/play/${album.id}/`);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    album.title,
  );
  await expect(
    page.getByRole("button", { name: "Find the connection" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Reveal every path" }),
  ).toBeVisible();

  // Evidence starts hidden (guess mode); revealing one path shows its evidence table.
  await expect(page.locator(".evidence-card:not([hidden])")).toHaveCount(0);
  await page.getByRole("button", { name: "Reveal" }).first().click();
  await expect(
    page.locator(".evidence-card:not([hidden]) .evidence table").first(),
  ).toBeVisible();

  // "Reveal every path" unhides every evidence card on the page.
  await page.getByRole("button", { name: "Reveal every path" }).click();
  const totalPaths = await page.locator("[data-play-path]").count();
  await expect(page.locator(".evidence-card:not([hidden])")).toHaveCount(
    totalPaths,
  );
});

test("cohorts page loads, shows the synthetic notice, and reveals a pair", async ({
  page,
}) => {
  await page.goto("/cohorts/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "Guess the connection",
  );
  await expect(page.getByText("Synthetic Example Cohort").first()).toBeVisible();
  await expect(page.locator("[data-synthetic-notice]")).toBeVisible();
  await expect(page.locator("[data-cohort-pair]").first()).toBeVisible();

  await expect(page.locator("[data-guess-target]:not([hidden])")).toHaveCount(
    0,
  );
  await page.getByRole("button", { name: "Reveal" }).first().click();
  await expect(
    page.locator("[data-guess-target]:not([hidden])").first(),
  ).toBeVisible();

  const bodyText = (await page.textContent("body"))?.toLowerCase() ?? "";
  expect(bodyText).not.toContain("worked with");
  expect(bodyText).not.toContain("collaborated with");
  expect(bodyText).not.toContain("influenced");
});
