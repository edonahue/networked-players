// Browser tests for Record Routes (ADR 0046). The full pool is fetched at
// runtime like the Connection Guesser's; these tests intercept
// /data/routes/{universe,rounds}.v1.json with small hand-built fixtures so
// they don't depend on a real generation run, mirroring the pattern already
// used for game-albumart-browser.spec.ts.

import { expect, test, type Page } from "@playwright/test";

const PROVENANCE = {
  source: "Discogs monthly data dump (CC0), one-hop working set",
  license: "See docs/DATA_AND_RIGHTS.md.",
  snapshot_date: "20260601",
  generated_by: "test",
  graph_core_version: "0.1.0",
  note: "test",
  catalog_version: "catalog-v1-20260601-abc",
  artifact_version: "routes-artifact-v1-20260601-abc123abc123",
};

function album(id: string, artistId: number, title: string) {
  return {
    id,
    master_id: 1,
    main_release_id: 1,
    title,
    artist_id: artistId,
    artist: `Act ${artistId}`,
    year: 1990,
  };
}

const ONE_HOP_ROUTE = {
  id: "route-0000000001",
  kind: "one_hop",
  difficulty: "medium",
  from_album_id: "master-1",
  to_album_id: "master-2",
  from_artist_id: 100,
  to_artist_id: 200,
  hops: [
    {
      release_id: 500,
      artist_a_id: 100,
      artist_b_id: 200,
      role_a: "Guitar",
      role_b: "Bass",
      quality_flags: ["performer_credit", "same_recording"],
    },
  ],
  distractors: [{ album_id: "master-3", reason: "decoy" }],
};

const TWO_HOP_ROUTE = {
  id: "route-0000000002",
  kind: "two_hop",
  difficulty: "hard",
  from_album_id: "master-4",
  to_album_id: "master-5",
  from_artist_id: 400,
  to_artist_id: 500,
  hops: [
    {
      release_id: 501,
      artist_a_id: 400,
      artist_b_id: 999,
      role_a: "Guitar",
      role_b: "Producer",
      quality_flags: ["performer_credit", "same_recording"],
    },
    {
      release_id: 502,
      artist_a_id: 999,
      artist_b_id: 500,
      role_a: "Producer",
      role_b: "Vocals",
      quality_flags: ["performer_credit", "same_recording"],
    },
  ],
  distractors: [{ album_id: "master-3", reason: "decoy" }],
};

function universeFixture() {
  return {
    schema_version: 1,
    mode: "record_routes",
    pool_version: "routes-v1-20260601-abc123abc123",
    provenance: PROVENANCE,
    counts: { one_hop: 1, two_hop: 1, daily_eligible: 2 },
    albums: [
      album("master-1", 100, "First Light"),
      album("master-2", 200, "Second Wave"),
      album("master-3", 300, "Third Decoy"),
      album("master-4", 400, "Fourth Record"),
      album("master-5", 500, "Fifth Record"),
    ],
  };
}

function roundsFixture() {
  return {
    schema_version: 1,
    mode: "record_routes",
    pool_version: "routes-v1-20260601-abc123abc123",
    provenance: PROVENANCE,
    rounds: [ONE_HOP_ROUTE, TWO_HOP_ROUTE],
    releases: [
      {
        release_id: 500,
        title: "First Light",
        released: "1990",
        country: "US",
        source_url: "https://example.invalid/release/500",
        credits: [
          {
            snapshot_date: "20260601",
            release_id: 500,
            track_index: null,
            track_path: null,
            track_position: null,
            track_title: null,
            credit_scope: "release_artist",
            artist_id: 100,
            name: "Artist100",
            anv: null,
            join_text: null,
            role_text: "Guitar",
            credited_tracks_text: null,
            is_linked: true,
            playable_identity: true,
          },
          {
            snapshot_date: "20260601",
            release_id: 500,
            track_index: null,
            track_path: null,
            track_position: null,
            track_title: null,
            credit_scope: "release_artist",
            artist_id: 200,
            name: "Artist200",
            anv: null,
            join_text: null,
            role_text: "Bass",
            credited_tracks_text: null,
            is_linked: true,
            playable_identity: true,
          },
        ],
      },
      {
        release_id: 501,
        title: "Fourth Record",
        released: "1991",
        country: "US",
        source_url: "https://example.invalid/release/501",
        credits: [],
      },
      {
        release_id: 502,
        title: "Fifth Record",
        released: "1992",
        country: "US",
        source_url: "https://example.invalid/release/502",
        credits: [],
      },
    ],
    artists: [
      { artist_id: 100, name: "Artist100" },
      { artist_id: 200, name: "Artist200" },
      { artist_id: 400, name: "Artist400" },
      { artist_id: 500, name: "Artist500" },
      { artist_id: 999, name: "Bridge Artist" },
    ],
  };
}

async function routeFixtures(page: Page): Promise<void> {
  await page.route("**/data/routes/universe.v1.json", (route) =>
    route.fulfill({ status: 200, json: universeFixture() }),
  );
  await page.route("**/data/routes/rounds.v1.json", (route) =>
    route.fulfill({ status: 200, json: roundsFixture() }),
  );
}

test("a one-hop route deals, guesses length, and reveals with no artist step", async ({
  page,
}) => {
  await routeFixtures(page);
  await page.goto("/play/routes/?route=route-0000000001&motion=off");
  await expect(page.getByTestId("routes-stage")).toHaveAttribute(
    "data-phase",
    "guessing",
  );
  await expect(page.getByTestId("routes-caption-a")).toContainText(
    "First Light",
  );
  await expect(page.getByTestId("routes-caption-b")).toContainText(
    "Second Wave",
  );

  await page
    .locator('[data-testid="routes-length-tray"] .chip[data-length="one_hop"]')
    .click();
  // One-hop: nothing hidden to name, so it reveals immediately.
  await expect(page.getByTestId("routes-artist-step")).toBeHidden();
  await expect(page.getByTestId("routes-stage")).toHaveAttribute(
    "data-phase",
    "revealed",
  );
  await expect(page.getByTestId("routes-verdict-heading")).toContainText(
    "One documented hop",
  );
  await expect(page.getByTestId("routes-evidence-mount")).toContainText(
    "First Light",
  );
  // The one-hop verdict must name BOTH endpoint artists and the shared
  // release -- never single out one artist as if they alone "connect" the
  // pair (the corrected wording; see ADR 0046's slice-9 addendum).
  const rating = await page.getByTestId("routes-verdict-rating").textContent();
  expect(rating).toContain("Artist100");
  expect(rating).toContain("Artist200");
  expect(rating).toContain("First Light");
});

test("a two-hop route offers an optional connecting-artist guess before reveal", async ({
  page,
}) => {
  await routeFixtures(page);
  await page.goto("/play/routes/?route=route-0000000002&motion=off");
  await page
    .locator('[data-testid="routes-length-tray"] .chip[data-length="two_hop"]')
    .click();
  await expect(page.getByTestId("routes-artist-step")).toBeVisible();
  await expect(page.getByTestId("routes-stage")).toHaveAttribute(
    "data-phase",
    "guessing",
  );
  const bridgeChip = page.locator(
    '[data-testid="routes-artist-tray"] .chip[data-artist="999"]',
  );
  await expect(bridgeChip).toContainText("Bridge Artist");
  await bridgeChip.click();
  await expect(page.getByTestId("routes-stage")).toHaveAttribute(
    "data-phase",
    "revealed",
  );
  await expect(page.getByTestId("routes-verdict-heading")).toContainText(
    "Two documented hops",
  );
  await expect(page.getByTestId("routes-verdict-rating")).toContainText(
    "Clean",
  );
});

test("skipping the connecting-artist guess still reveals honestly", async ({
  page,
}) => {
  await routeFixtures(page);
  await page.goto("/play/routes/?route=route-0000000002&motion=off");
  await page
    .locator('[data-testid="routes-length-tray"] .chip[data-length="two_hop"]')
    .click();
  await expect(page.getByTestId("routes-artist-step")).toBeVisible();
  await page.getByTestId("routes-skip-artist").click();
  await expect(page.getByTestId("routes-stage")).toHaveAttribute(
    "data-phase",
    "revealed",
  );
  await expect(page.getByTestId("routes-evidence-mount")).toContainText(
    "Bridge Artist",
  );
});

test("a missing route pool fails gracefully, never a crash", async ({
  page,
}) => {
  await page.route("**/data/routes/universe.v1.json", (route) =>
    route.fulfill({ status: 500, body: "boom" }),
  );
  await page.route("**/data/routes/rounds.v1.json", (route) =>
    route.fulfill({ status: 500, body: "boom" }),
  );
  await page.goto("/play/routes/?motion=off");
  await expect(page.getByTestId("routes-stage")).toHaveAttribute(
    "data-phase",
    "error",
  );
  await expect(page.getByTestId("routes-question")).toContainText(
    "Could not load the route pool",
  );
  await expect(page.getByTestId("routes-length-tray")).toBeHidden();
});

test("the hub card for Record Routes is live and links here", async ({
  page,
}) => {
  await page.goto("/play/");
  const card = page.locator("a[data-mode-status='live']", {
    hasText: "Record Routes",
  });
  await expect(card).toHaveAttribute("href", "/play/routes/");
  await card.click();
  await expect(page).toHaveURL(/\/play\/routes\/$/);
});

// --- Runtime resolver integrity (routesResolver.ts) --------------------
// Every one of these serves a structurally malformed pool and asserts the
// page reaches the same typed error state as the "missing route pool" test
// above -- never a thrown exception, never a substituted route, never a
// gameplay control left interactive.

async function expectIntegrityError(page: Page): Promise<void> {
  await expect(page.getByTestId("routes-stage")).toHaveAttribute(
    "data-phase",
    "error",
  );
  await expect(page.getByTestId("routes-length-tray")).toBeHidden();
  await expect(page.getByTestId("routes-artist-step")).toBeHidden();
}

test("a wrong-mode artifact fails gracefully", async ({ page }) => {
  const universe = { ...universeFixture(), mode: "connection_guesser_one_hop" };
  await page.route("**/data/routes/universe.v1.json", (route) =>
    route.fulfill({ status: 200, json: universe }),
  );
  await page.route("**/data/routes/rounds.v1.json", (route) =>
    route.fulfill({ status: 200, json: roundsFixture() }),
  );
  await page.goto("/play/routes/?motion=off");
  await expectIntegrityError(page);
});

test("a universe/rounds version mismatch fails gracefully", async ({
  page,
}) => {
  const rounds = {
    ...roundsFixture(),
    pool_version: "routes-v1-20260601-different",
  };
  await page.route("**/data/routes/universe.v1.json", (route) =>
    route.fulfill({ status: 200, json: universeFixture() }),
  );
  await page.route("**/data/routes/rounds.v1.json", (route) =>
    route.fulfill({ status: 200, json: rounds }),
  );
  await page.goto("/play/routes/?motion=off");
  await expectIntegrityError(page);
});

test("an empty route pool (after filtering malformed members) fails gracefully", async ({
  page,
}) => {
  const rounds = { ...roundsFixture(), rounds: [null, "not a route", 42] };
  await page.route("**/data/routes/universe.v1.json", (route) =>
    route.fulfill({ status: 200, json: universeFixture() }),
  );
  await page.route("**/data/routes/rounds.v1.json", (route) =>
    route.fulfill({ status: 200, json: rounds }),
  );
  await page.goto("/play/routes/?motion=off");
  await expectIntegrityError(page);
});

test("a route whose endpoint album isn't in the universe fails gracefully", async ({
  page,
}) => {
  const universe = {
    ...universeFixture(),
    albums: universeFixture().albums.filter((a) => a.id !== "master-2"),
  };
  await page.route("**/data/routes/universe.v1.json", (route) =>
    route.fulfill({ status: 200, json: universe }),
  );
  await page.route("**/data/routes/rounds.v1.json", (route) =>
    route.fulfill({ status: 200, json: roundsFixture() }),
  );
  await page.goto("/play/routes/?route=route-0000000001&motion=off");
  await expectIntegrityError(page);
});

test("a route whose hop references an unpublished artist fails gracefully", async ({
  page,
}) => {
  const rounds = roundsFixture();
  rounds.artists = rounds.artists.filter((a) => a.artist_id !== 200);
  await page.route("**/data/routes/universe.v1.json", (route) =>
    route.fulfill({ status: 200, json: universeFixture() }),
  );
  await page.route("**/data/routes/rounds.v1.json", (route) =>
    route.fulfill({ status: 200, json: rounds }),
  );
  await page.goto("/play/routes/?route=route-0000000001&motion=off");
  await expectIntegrityError(page);
});

test("a two-hop route with an ambiguous (missing) bridge fails gracefully", async ({
  page,
}) => {
  const rounds = roundsFixture();
  // roundsFixture()'s `rounds` array holds references to the shared
  // module-level ONE_HOP_ROUTE/TWO_HOP_ROUTE constants -- deep-clone before
  // mutating a nested field, or this corrupts every later test in the file
  // that also deals route-0000000002.
  const broken = structuredClone(
    rounds.rounds.find((r) => r.id === "route-0000000002")!,
  );
  rounds.rounds = rounds.rounds.map((r) => (r.id === broken.id ? broken : r));
  // Both hops now share no artist at all with the other -- no bridge.
  broken.hops[1].artist_a_id = 12345;
  rounds.artists = [
    ...rounds.artists,
    { artist_id: 12345, name: "Disconnected" },
  ];
  await page.route("**/data/routes/universe.v1.json", (route) =>
    route.fulfill({ status: 200, json: universeFixture() }),
  );
  await page.route("**/data/routes/rounds.v1.json", (route) =>
    route.fulfill({ status: 200, json: rounds }),
  );
  await page.goto("/play/routes/?route=route-0000000002&motion=off");
  await expectIntegrityError(page);
});

// --- Accessibility ------------------------------------------------------

test("a one-hop round plays on a phone-sized screen without sideways scroll", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await routeFixtures(page);
  await page.goto("/play/routes/?route=route-0000000001&motion=off");
  await expect(page.getByTestId("routes-stage")).toHaveAttribute(
    "data-phase",
    "guessing",
  );
  const scrollWidth = await page.evaluate(
    () => document.documentElement.scrollWidth,
  );
  const clientWidth = await page.evaluate(
    () => document.documentElement.clientWidth,
  );
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1);
});

test("a full two-hop round is completable by keyboard only", async ({
  page,
}) => {
  await routeFixtures(page);
  await page.goto("/play/routes/?route=route-0000000002&motion=off");

  const lengthTray = page.getByTestId("routes-length-tray");
  const firstLengthChip = lengthTray.locator(".chip").first();
  await firstLengthChip.focus();
  await expect(firstLengthChip).toHaveAttribute("role", "radio");
  await page.keyboard.press("ArrowRight");
  const twoHopChip = lengthTray.locator('.chip[data-length="two_hop"]');
  await expect(twoHopChip).toBeFocused();
  await page.keyboard.press("Enter");

  await expect(page.getByTestId("routes-artist-step")).toBeVisible();
  const artistTray = page.getByTestId("routes-artist-tray");
  const bridgeChip = artistTray.locator('.chip[data-artist="999"]');
  await bridgeChip.focus();
  await page.keyboard.press("Enter");

  await expect(page.getByTestId("routes-stage")).toHaveAttribute(
    "data-phase",
    "revealed",
  );
  await expect(page.getByTestId("routes-verdict-rating")).toContainText(
    "Clean",
  );
});
