// Browser tests for album-art resolution on the game surface (slice 7A). The
// game fetches /data/catalog/album-art.v1.json at init and resolves real
// sleeves by canonical album id; every failure mode falls back to the
// placeholder and never blocks play. The committed site ships with NO
// registry yet (7B enriches it), so these drive the registry via route
// interception.

import { expect, test, type Page } from "@playwright/test";

const CATALOG_VERSION = "catalog-v1-20260601-0e7ec70fbb7e";

interface RoundLite {
  id: string;
  kind: string;
  endpoints: { id: string; title: string }[];
}

async function firstOneHop(page: Page): Promise<RoundLite> {
  const res = await page.request.get("/data/game/rounds.v1.json");
  const { rounds } = (await res.json()) as { rounds: RoundLite[] };
  return rounds.find((r) => r.kind === "one_hop")!;
}

async function routeRegistry(
  page: Page,
  body: unknown,
  status = 200,
): Promise<void> {
  await page.route("**/data/catalog/album-art.v1.json", (route) =>
    route.fulfill({
      status,
      contentType: "application/json",
      body: typeof body === "string" ? body : JSON.stringify(body),
    }),
  );
}

function registryFor(albumIds: string[], catalogVersion = CATALOG_VERSION) {
  return {
    schema_version: 1,
    catalog_version: catalogVersion,
    art_version: "album-art-v1-20260601-000000000000",
    generated_at: "2026-07-22T00:00:00+00:00",
    source: "test",
    license: "test",
    albums: albumIds.map((id) => ({
      album_id: id,
      main_release_id: 1,
      uri150: `https://i.discogs.com/${id}/150.jpg`,
      uri: `https://i.discogs.com/${id}/full.jpg`,
    })),
  };
}

// A 1x1 transparent PNG so intercepted cover requests actually load (200)
// and the <img> stays in the DOM (the error→placeholder handler must not
// race the assertion).
const PNG_1x1 = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
  "base64",
);

async function serveImages(page: Page): Promise<void> {
  await page.route("https://i.discogs.com/**", (route) =>
    route.fulfill({ status: 200, contentType: "image/png", body: PNG_1x1 }),
  );
}

test("a resolvable registry renders real cover art in the sleeves", async ({
  page,
}) => {
  const round = await firstOneHop(page);
  await routeRegistry(page, registryFor(round.endpoints.map((e) => e.id)));
  await serveImages(page);
  await page.goto(`/play/connection/?round=${round.id}&motion=off`);
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "guessing",
  );
  const img = page.locator('[data-testid="sleeve-a"] img');
  await expect(img).toBeVisible();
  await expect(img).toHaveAttribute(
    "src",
    `https://i.discogs.com/${round.endpoints[0].id}/150.jpg`,
  );
});

test("a missing registry (404) falls back to placeholders, gameplay unaffected", async ({
  page,
}) => {
  const round = await firstOneHop(page);
  await routeRegistry(page, "not found", 404);
  await page.goto(`/play/connection/?round=${round.id}&motion=off`);
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "guessing",
  );
  await expect(page.locator('[data-testid="sleeve-a"] img')).toHaveCount(0);
  await expect(
    page.locator('[data-testid="sleeve-a"] .album-card__placeholder-disc'),
  ).toBeVisible();
});

test("a malformed registry falls back to placeholders, no crash", async ({
  page,
}) => {
  const round = await firstOneHop(page);
  await routeRegistry(page, "{ not valid json");
  await page.goto(`/play/connection/?round=${round.id}&motion=off`);
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "guessing",
  );
  await expect(page.locator('[data-testid="sleeve-a"] img')).toHaveCount(0);
});

test("a catalog-version-mismatched registry is ignored (placeholders)", async ({
  page,
}) => {
  const round = await firstOneHop(page);
  await routeRegistry(
    page,
    registryFor(
      round.endpoints.map((e) => e.id),
      "catalog-v1-20260601-DIFFERENT",
    ),
  );
  await page.goto(`/play/connection/?round=${round.id}&motion=off`);
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "guessing",
  );
  await expect(page.locator('[data-testid="sleeve-a"] img')).toHaveCount(0);
});

test("an upstream image error swaps the cover for the placeholder", async ({
  page,
}) => {
  const round = await firstOneHop(page);
  await routeRegistry(page, registryFor(round.endpoints.map((e) => e.id)));
  // Fail the actual image request so the <img> error listener fires.
  await page.route("https://i.discogs.com/**", (route) =>
    route.fulfill({ status: 404, body: "gone" }),
  );
  await page.goto(`/play/connection/?round=${round.id}&motion=off`);
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "guessing",
  );
  await expect(
    page.locator('[data-testid="sleeve-a"] .album-card__placeholder-disc'),
  ).toBeVisible();
});
