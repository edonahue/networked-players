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
  const firstReveal = page.locator("[data-reveal-button]").first();
  await expect(firstReveal).toHaveText("Reveal");
  await expect(firstReveal).toHaveAttribute("aria-expanded", "false");
  const controls = await firstReveal.getAttribute("aria-controls");
  if (!controls) throw new Error("Reveal button is missing aria-controls");
  await expect(page.locator(`#${controls}`)).toBeHidden();

  await firstReveal.click();
  await expect(firstReveal).toHaveText("Hide");
  await expect(firstReveal).toHaveAttribute("aria-expanded", "true");
  await expect(
    page.locator(".evidence-card:not([hidden]) .evidence table").first(),
  ).toBeVisible();
  await expect(page.locator(`#${controls}`)).toBeVisible();

  await firstReveal.click();
  await expect(firstReveal).toHaveText("Reveal");
  await expect(firstReveal).toHaveAttribute("aria-expanded", "false");
  await expect(page.locator(`#${controls}`)).toBeHidden();

  // "Reveal every path" unhides every evidence card on the page.
  await page.getByRole("button", { name: "Reveal every path" }).click();
  const totalPaths = await page.locator("[data-play-path]").count();
  await expect(page.locator(".evidence-card:not([hidden])")).toHaveCount(
    totalPaths,
  );
  await expect(
    page.getByRole("button", { name: "Hide" }).first(),
  ).toHaveAttribute("aria-expanded", "true");

  await page.getByRole("button", { name: "Find the connection" }).click();
  await expect(page.locator(".evidence-card:not([hidden])")).toHaveCount(0);
  await expect(page.locator("[data-reveal-button]").first()).toHaveAttribute(
    "aria-expanded",
    "false",
  );
});

test("static game artifacts are reachable and real", async ({ request }) => {
  const universeRes = await request.get("/data/game/universe.v1.json");
  expect(universeRes.ok()).toBeTruthy();
  const universe = await universeRes.json();
  expect(universe.schema_version).toBe(1);
  expect(universe.provenance.generated_by).not.toContain("synthetic");
  expect(Array.isArray(universe.albums)).toBe(true);

  const roundsRes = await request.get("/data/game/rounds.v1.json");
  expect(roundsRes.ok()).toBeTruthy();
  const rounds = await roundsRes.json();
  expect(rounds.schema_version).toBe(1);
  expect(rounds.pool_version).toBe(universe.pool_version);
  expect(Array.isArray(rounds.rounds)).toBe(true);
  expect(rounds.rounds.length).toBeGreaterThan(0);

  const dailyRes = await request.get("/data/game/daily-manifest.v1.json");
  expect(dailyRes.ok()).toBeTruthy();
  const daily = await dailyRes.json();
  expect(daily.pool_version).toBe(universe.pool_version);
  expect(Array.isArray(daily.schedule)).toBe(true);
});

test("guess page loads a real round and reveals evidence without leaking the answer first", async ({
  page,
}) => {
  await page.goto("/guess/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "Guess the connection",
  );

  const round = page.locator("[data-round-container] article.evidence-card");
  await expect(round).toBeVisible({ timeout: 15000 });

  const reveal = page.locator("[data-round-reveal-button]");
  await expect(reveal).toHaveAttribute("aria-expanded", "false");
  const evidence = page.locator(".round-evidence");
  // Same established pattern as EvidenceCard/CohortPairCard: evidence is
  // present in the DOM but under the `hidden` attribute (browser-default
  // `display: none`) until revealed -- not literally absent from markup,
  // consistent with every other reveal mechanic already shipped and tested
  // in this codebase (cohort-manifest.spec.ts, the existing guess-page test).
  await expect(evidence).toBeHidden();

  await reveal.click();
  await expect(reveal).toHaveAttribute("aria-expanded", "true");
  await expect(evidence).toBeVisible();
  await expect(evidence.locator(".hop").first()).toBeVisible();
  await expect(evidence.locator("table").first()).toBeVisible();

  // "Next round" swaps in a different real round.
  const firstRoundId = await round.getAttribute("data-round-id");
  await page.getByRole("button", { name: "Next round" }).click();
  await expect(round).toBeVisible({ timeout: 15000 });
  // Not asserted to differ (the pool could be small enough to repeat), but
  // must still be a real, evidence-bearing round either way.
  await expect(page.locator(".round-evidence")).toBeHidden();
  expect(await round.getAttribute("data-round-id")).toBeTruthy();
  void firstRoundId;
});

test("daily page resolves today's exact round from the frozen manifest", async ({
  page,
  request,
}) => {
  const dailyRes = await request.get("/data/game/daily-manifest.v1.json");
  const daily = await dailyRes.json();
  const today = new Date().toISOString().slice(0, 10);
  const entry = daily.schedule.find(
    (e: { date: string; round_id: string }) => e.date === today,
  );
  test.skip(!entry, "today's date is outside the generated schedule");

  await page.goto("/daily/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(today);

  const round = page.locator("[data-round-container] article.evidence-card");
  await expect(round).toBeVisible({ timeout: 15000 });
  await expect(round).toHaveAttribute("data-round-id", entry.round_id);

  // Reloading the same real date must resolve to the exact same round --
  // the frozen-manifest stability guarantee, checked end to end through the
  // actual page, not just the artifact.
  await page.reload();
  await expect(round).toBeVisible({ timeout: 15000 });
  await expect(round).toHaveAttribute("data-round-id", entry.round_id);
});

test("cohorts index lists cohorts and links to a detail page", async ({
  page,
}) => {
  await page.goto("/cohorts/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "Browse reviewed cohorts",
  );
  await expect(
    page.getByText("Synthetic Example Cohort").first(),
  ).toBeVisible();

  const openCohortLink = page
    .getByRole("link", { name: "Open cohort" })
    .first();
  await expect(openCohortLink).toHaveAttribute(
    "href",
    "/cohorts/synthetic-example/",
  );
});

test("cohort detail page shows the synthetic notice and reveals a pair", async ({
  page,
}) => {
  await page.goto("/cohorts/synthetic-example/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "Synthetic Example Cohort",
  );
  await expect(page.locator("[data-synthetic-notice]")).toBeVisible();
  await expect(page.locator("[data-cohort-pair]").first()).toBeVisible();
  await expect(page.locator(".tag--status-synthetic")).toBeVisible();
  await expect(page.locator(".tag--difficulty").first()).toBeVisible();

  await expect(page.locator("[data-guess-target]:not([hidden])")).toHaveCount(
    0,
  );
  const firstReveal = page.locator("[data-reveal-button]").first();
  await expect(firstReveal).toHaveText("Reveal");
  await expect(firstReveal).toHaveAttribute("aria-expanded", "false");
  const controls = await firstReveal.getAttribute("aria-controls");
  if (!controls) throw new Error("Reveal button is missing aria-controls");
  await expect(page.locator(`#${controls}`)).toBeHidden();

  await firstReveal.click();
  await expect(firstReveal).toHaveText("Hide");
  await expect(firstReveal).toHaveAttribute("aria-expanded", "true");
  await expect(
    page.locator("[data-guess-target]:not([hidden])").first(),
  ).toBeVisible();
  await expect(page.locator(`#${controls}`)).toBeVisible();

  await firstReveal.click();
  await expect(firstReveal).toHaveText("Reveal");
  await expect(firstReveal).toHaveAttribute("aria-expanded", "false");
  await expect(page.locator(`#${controls}`)).toBeHidden();

  const bodyText = (await page.textContent("body"))?.toLowerCase() ?? "";
  expect(bodyText).not.toContain("worked with");
  expect(bodyText).not.toContain("collaborated with");
  expect(bodyText).not.toContain("influenced");
});
