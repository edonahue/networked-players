// Games link onward (Atlas P4): a resolved round in the Connection Guesser,
// Connection of the Day and Record Routes offers links to its records, the
// connecting player(s) and Connect. Rounds, dates and ids all come from the
// committed artifacts; no catalog name is written here.

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { readArtifact } from "./helpers/catalogFacts";
import { PINNED_DATE_A } from "./helpers/pinnedDates";

interface Ref {
  id: number;
  name: string;
}
interface GameRoundLite {
  id: string;
  kind: "one_hop" | "two_hop";
  endpoints: { id: string; title: string }[];
  answer_set: Ref[];
  middle?: { album: { id: string; title: string } };
}

const guesserRounds = readArtifact<{ rounds: GameRoundLite[] }>(
  "game/rounds.v1.json",
).rounds;
const oneHop = guesserRounds.find((r) => r.kind === "one_hop")!;
const twoHop = guesserRounds.find((r) => r.kind === "two_hop")!;

const manifest = readArtifact<{ schedule: { date: string }[] }>(
  "game/daily-manifest.v1.json",
);
const LAST_DATE = manifest.schedule[manifest.schedule.length - 1].date;

const contributorIds = new Set(
  readArtifact<{ contributors: { artist_id: number }[] }>(
    "contributors/index.v1.json",
  ).contributors.map((c) => c.artist_id),
);

const routesArtifact = readArtifact<{
  rounds: {
    id: string;
    kind: "one_hop" | "two_hop";
    from_album_id: string;
    to_album_id: string;
  }[];
}>("routes/rounds.v1.json");
const routeOne = routesArtifact.rounds.find((r) => r.kind === "one_hop")!;
const routeTwo = routesArtifact.rounds.find((r) => r.kind === "two_hop")!;

async function allowDateOverride(page: Page): Promise<void> {
  await page.addInitScript(() => {
    (window as unknown as Record<string, unknown>).__NP_ALLOW_DATE_OVERRIDE__ =
      true;
  });
}

async function resolveGuesser(page: Page): Promise<void> {
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "guessing",
  );
  await expect(page.getByTestId("onward")).toBeHidden();
  await expect(page.getByTestId("onward").locator("a")).toHaveCount(0);
  await page.getByTestId("give-up").click();
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "revealed",
  );
}

async function expectOnwardLinks(
  page: Page,
  scope: string,
  expected: { records: number; connect: boolean },
) {
  const onward = page.getByTestId(scope);
  await expect(onward).toBeVisible();
  await expect(onward.locator('a[data-onward="record"]')).toHaveCount(
    expected.records,
  );
  await expect(
    onward.locator('a[data-onward="explore"]').first(),
  ).toBeVisible();
  await expect(onward.locator('a[data-onward="connect"]')).toHaveCount(
    expected.connect ? 1 : 0,
  );
  // Every player page link points at a page that exists.
  const pageLinks = await onward
    .locator('a[data-onward="player"]')
    .evaluateAll((els) => els.map((e) => e.getAttribute("href")!));
  for (const href of pageLinks) {
    expect(contributorIds.has(Number(href.split("/")[2]))).toBe(true);
  }
  // 44px targets.
  for (const link of await onward.locator("a").all()) {
    const box = await link.boundingBox();
    expect(box!.height).toBeGreaterThanOrEqual(44);
  }
}

async function followRecordLink(page: Page, scope: string) {
  const link = page
    .getByTestId(scope)
    .locator('a[data-onward="record"]')
    .first();
  const title = (await link.textContent())!.trim();
  await link.click();
  await expect(page).toHaveURL(/\/albums\/[^/]+\/$/);
  await expect(page.locator("h1")).toHaveText(title);
}

test("Connection Guesser one-hop: onward row appears only once resolved", async ({
  page,
}) => {
  await page.goto(`/play/connection/?round=${oneHop.id}&motion=off`);
  await resolveGuesser(page);
  await expectOnwardLinks(page, "onward", { records: 2, connect: true });
  const connect = page
    .getByTestId("onward")
    .locator('a[data-onward="connect"]');
  await expect(connect).toHaveAttribute(
    "href",
    `/play/connect/?a=${oneHop.endpoints[0].id}&b=${oneHop.endpoints[1].id}`,
  );
  const explore = page
    .getByTestId("onward")
    .locator('a[data-onward="explore"]');
  await expect(explore.first()).toHaveAttribute(
    "href",
    new RegExp(`^/explore/[^/]+/\\?center=${oneHop.answer_set[0].id}$`),
  );
  // Focus stayed on the verdict.
  await expect(page.getByTestId("verdict-heading")).toBeFocused();
  await followRecordLink(page, "onward");
});

test("Connection Guesser: the explore link opens Explore centred on the player", async ({
  page,
}) => {
  await page.goto(`/play/connection/?round=${oneHop.id}&motion=off`);
  await resolveGuesser(page);
  await page
    .getByTestId("onward")
    .locator('a[data-onward="explore"]')
    .first()
    .click();
  await expect(page).toHaveURL(
    new RegExp(`/explore/[^/]+/\\?center=${oneHop.answer_set[0].id}`),
  );
  await expect(page.locator("[data-explorer-center-link]")).toBeVisible();
});

test("Connection Guesser: a player page link, when offered, loads that player", async ({
  page,
}) => {
  // The first answer (by rule) that has a player page.
  const round =
    guesserRounds.find(
      (r) => r.kind === "one_hop" && contributorIds.has(r.answer_set[0].id),
    ) ?? oneHop;
  await page.goto(`/play/connection/?round=${round.id}&motion=off`);
  await resolveGuesser(page);
  const link = page
    .getByTestId("onward")
    .locator(
      `a[data-onward="player"][href="/contributors/${round.answer_set[0].id}/"]`,
    );
  await expect(link).toBeVisible();
  await link.click();
  await expect(page).toHaveURL(`/contributors/${round.answer_set[0].id}/`);
  await expect(page.locator("h1")).toContainText(
    round.answer_set[0].name.replace(/\s+\(\d+\)$/, ""),
  );
});

test("Connection Guesser two-hop: names both records, the hidden record and the bridges", async ({
  page,
}) => {
  await page.goto(
    `/play/connection/?round=${twoHop.id}&kind=two_hop&motion=off`,
  );
  await resolveGuesser(page);
  await expectOnwardLinks(page, "onward", { records: 3, connect: true });
  await expect(
    page
      .getByTestId("onward")
      .locator(
        `a[data-onward="record"][href="/albums/${twoHop.middle!.album.id}/"]`,
      ),
  ).toBeVisible();
});

for (const [label, date] of [
  ["first scheduled date", PINNED_DATE_A],
  ["last scheduled date", LAST_DATE],
] as const) {
  test(`Connection of the Day (${label}): onward row after resolution, share string unchanged`, async ({
    page,
  }) => {
    await allowDateOverride(page);
    await page.goto(`/play/daily/?date=${date}&motion=off`);
    await resolveGuesser(page);
    await expectOnwardLinks(page, "onward", { records: 2, connect: true });
    // The share string never carries a link or an id.
    const share = (await page.getByTestId("share-string").textContent()) ?? "";
    expect(share).not.toMatch(/\/albums\/|\/explore\/|\/play\/connect|http/);
    await followRecordLink(page, "onward");
  });
}

test("Record Routes: no onward links before the reveal; records, player, Connect after (one hop)", async ({
  page,
}) => {
  await page.goto(`/play/routes/?route=${routeOne.id}&motion=off`);
  await expect(page.getByTestId("routes-stage")).toHaveAttribute(
    "data-phase",
    "guessing",
  );
  await expect(page.getByTestId("routes-onward")).toBeHidden();
  await expect(page.getByTestId("routes-onward").locator("a")).toHaveCount(0);
  await page
    .locator('[data-testid="routes-length-tray"] .chip[data-length="one_hop"]')
    .click();
  await expect(page.getByTestId("routes-stage")).toHaveAttribute(
    "data-phase",
    "revealed",
  );
  await expectOnwardLinks(page, "routes-onward", { records: 2, connect: true });
  await expect(
    page.getByTestId("routes-onward").locator('a[data-onward="connect"]'),
  ).toHaveAttribute(
    "href",
    `/play/connect/?a=${routeOne.from_album_id}&b=${routeOne.to_album_id}`,
  );
  await expect(page.getByTestId("routes-verdict-heading")).toBeFocused();
  await followRecordLink(page, "routes-onward");
});

test("Record Routes (two hops): the bridge player is offered once the route is revealed", async ({
  page,
}) => {
  await page.goto(`/play/routes/?route=${routeTwo.id}&motion=off`);
  await expect(page.getByTestId("routes-onward").locator("a")).toHaveCount(0);
  await page
    .locator('[data-testid="routes-length-tray"] .chip[data-length="two_hop"]')
    .click();
  await page.getByTestId("routes-skip-artist").click();
  await expect(page.getByTestId("routes-stage")).toHaveAttribute(
    "data-phase",
    "revealed",
  );
  await expectOnwardLinks(page, "routes-onward", { records: 2, connect: true });
  await expect(
    page.getByTestId("routes-onward").locator('a[data-onward="explore"]'),
  ).toHaveCount(1);
});

for (const theme of ["dark", "light"] as const) {
  test(`axe: resolved rounds with onward links, ${theme} theme`, async ({
    page,
  }) => {
    await page.addInitScript(
      (t) => window.localStorage.setItem("networked-players-theme", t),
      theme,
    );
    await page.goto(`/play/connection/?round=${oneHop.id}&motion=off`);
    await resolveGuesser(page);
    await expect(
      page.getByTestId("onward").locator('a[data-onward="explore"]').first(),
    ).toBeVisible();
    let results = await new AxeBuilder({ page }).analyze();
    expect(
      results.violations,
      JSON.stringify(results.violations.map((v) => v.id)),
    ).toEqual([]);

    await page.goto(`/play/routes/?route=${routeOne.id}&motion=off`);
    await page
      .locator(
        '[data-testid="routes-length-tray"] .chip[data-length="one_hop"]',
      )
      .click();
    await expect(page.getByTestId("routes-onward")).toBeVisible();
    results = await new AxeBuilder({ page }).analyze();
    expect(
      results.violations,
      JSON.stringify(results.violations.map((v) => v.id)),
    ).toEqual([]);
  });
}

test.describe("390px", () => {
  test.use({ viewport: { width: 390, height: 844 } });
  test("onward row fits the viewport without horizontal scroll", async ({
    page,
  }) => {
    await page.goto(
      `/play/connection/?round=${twoHop.id}&kind=two_hop&motion=off`,
    );
    await resolveGuesser(page);
    await expectOnwardLinks(page, "onward", { records: 3, connect: true });
    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth >
        document.documentElement.clientWidth,
    );
    expect(overflow).toBe(false);
  });
});
