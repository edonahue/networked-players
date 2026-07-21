// Connection of the Day (docs/WEB_PRODUCT_PLAN.md §5, §12.6): a frozen,
// append-only date -> round resolution via daily-manifest.v1.json (ADR
// 0043's corrective-slice-4.6 addendum) -- never a date-seeded derivation.
// Tests pin ?date= to real dates already committed in the published
// manifest (2026-08-01 .. 2026-10-29) so nothing here depends on the real
// wall-clock date.

import { expect, test, type Page } from "@playwright/test";

const PINNED_DATE_A = "2026-08-01";
const PINNED_DATE_B = "2026-08-02";
const OUT_OF_RANGE_DATE = "2020-01-01";

interface DailyManifestEntry {
  date: string;
  round_id: string;
  round_fingerprint: string;
}

interface DailyManifest {
  mode: string;
  start_date: string;
  schedule: DailyManifestEntry[];
}

interface RoundLite {
  id: string;
  kind: string;
  answer_set: { id: number; name: string }[];
  distractors: { id: number; name: string }[];
}

async function fetchManifest(page: Page): Promise<DailyManifest> {
  const res = await page.request.get("/data/game/daily-manifest.v1.json");
  return (await res.json()) as DailyManifest;
}

async function fetchRounds(page: Page): Promise<RoundLite[]> {
  const res = await page.request.get("/data/game/rounds.v1.json");
  const { rounds } = (await res.json()) as { rounds: RoundLite[] };
  return rounds;
}

async function entryFor(page: Page, date: string): Promise<DailyManifestEntry> {
  const manifest = await fetchManifest(page);
  const entry = manifest.schedule.find((e) => e.date === date);
  if (!entry) throw new Error(`fixture date ${date} is not in the committed manifest`);
  return entry;
}

async function gotoDaily(page: Page, date: string): Promise<void> {
  await page.goto(`/play/daily/?date=${date}&motion=off`);
}

test("the manifest is real, one-hop only, and covers the documented range", async ({
  page,
}) => {
  const manifest = await fetchManifest(page);
  const rounds = await fetchRounds(page);
  const byId = new Map(rounds.map((r) => [r.id, r]));
  expect(manifest.mode).toBe("connection_guesser_one_hop");
  expect(manifest.start_date).toBe("2026-08-01");
  expect(manifest.schedule.length).toBeGreaterThanOrEqual(60);
  for (const entry of manifest.schedule) {
    expect(byId.get(entry.round_id)?.kind, `${entry.date} -> ${entry.round_id}`).toBe(
      "one_hop",
    );
  }
});

test("a pinned scheduled date resolves exactly to its manifest entry", async ({ page }) => {
  const entry = await entryFor(page, PINNED_DATE_A);
  await gotoDaily(page, PINNED_DATE_A);
  await expect(page.getByTestId("stage")).toHaveAttribute("data-round", entry.round_id);
  await expect(page.getByTestId("stage")).toHaveAttribute("data-phase", "guessing");
  await expect(page.getByTestId("stage")).toHaveAttribute("data-kind", "one_hop");
  await expect(page.getByTestId("set-progress")).toHaveText(
    `Connection of the Day · ${PINNED_DATE_A}`,
  );
});

test("two different scheduled dates resolve to their own declared entries", async ({
  page,
}) => {
  const entryA = await entryFor(page, PINNED_DATE_A);
  const entryB = await entryFor(page, PINNED_DATE_B);
  expect(entryA.round_id).not.toBe(entryB.round_id);

  await gotoDaily(page, PINNED_DATE_A);
  await expect(page.getByTestId("stage")).toHaveAttribute("data-round", entryA.round_id);

  await gotoDaily(page, PINNED_DATE_B);
  await expect(page.getByTestId("stage")).toHaveAttribute("data-round", entryB.round_id);
});

test("reloading the same date never changes the resolved round", async ({ page }) => {
  const entry = await entryFor(page, PINNED_DATE_A);
  await gotoDaily(page, PINNED_DATE_A);
  await expect(page.getByTestId("stage")).toHaveAttribute("data-round", entry.round_id);
  await page.reload();
  await expect(page.getByTestId("stage")).toHaveAttribute("data-round", entry.round_id);
});

test("a later scheduled date still resolves to its own frozen round (no drift)", async ({
  page,
}) => {
  const manifest = await fetchManifest(page);
  const laterEntry = manifest.schedule[manifest.schedule.length - 1];
  await gotoDaily(page, laterEntry.date);
  await expect(page.getByTestId("stage")).toHaveAttribute("data-round", laterEntry.round_id);
  await expect(page.getByTestId("stage")).toHaveAttribute("data-phase", "guessing");
});

test("solving the daily records a streak and builds a spoiler-free share string", async ({
  page,
}) => {
  const entry = await entryFor(page, PINNED_DATE_A);
  const rounds = await fetchRounds(page);
  const round = rounds.find((r) => r.id === entry.round_id)!;

  await gotoDaily(page, PINNED_DATE_A);
  await expect(page.getByTestId("stage")).toHaveAttribute("data-phase", "guessing");
  await page.locator(`.chip[data-chip="${round.answer_set[0].id}"]`).click();
  await expect(page.getByTestId("stage")).toHaveAttribute("data-phase", "revealed");

  const share = page.getByTestId("share-string");
  await expect(share).toContainText(`Connection of the Day ${PINNED_DATE_A}`);
  await expect(share).toContainText("●");
  const shareText = (await share.textContent()) ?? "";
  for (const person of [...round.answer_set, ...round.distractors]) {
    expect(shareText).not.toContain(person.name);
  }

  await expect(page.getByTestId("streak-line")).toContainText("Streak: 1 day");
  await expect(page.getByTestId("share-copy")).toBeVisible();
  await expect(page.getByTestId("next-round")).toBeHidden();

  const stored = JSON.parse(
    (await page.evaluate(() => window.localStorage.getItem("np.game.v1"))) ?? "{}",
  );
  expect(stored.daily[PINNED_DATE_A]).toContain(PINNED_DATE_A);
  expect(stored.streak.current).toBe(1);
});

test("the daily refuses a second play and shows the recorded result instead", async ({
  page,
}) => {
  const entry = await entryFor(page, PINNED_DATE_A);
  const rounds = await fetchRounds(page);
  const round = rounds.find((r) => r.id === entry.round_id)!;

  await gotoDaily(page, PINNED_DATE_A);
  await page.locator(`.chip[data-chip="${round.answer_set[0].id}"]`).click();
  await expect(page.getByTestId("stage")).toHaveAttribute("data-phase", "revealed");
  const firstShare = await page.getByTestId("share-string").textContent();

  await page.reload();
  await expect(page.getByTestId("stage")).toHaveAttribute("data-phase", "played");
  await expect(page.getByTestId("chip-tray")).toBeHidden();
  await expect(page.getByTestId("clue-button")).toBeHidden();
  await expect(page.getByTestId("daily-panel")).toBeVisible();
  await expect(page.getByTestId("daily-panel")).toContainText("Already in the crate");
  await expect(page.getByTestId("share-string")).toHaveText(firstShare ?? "");
  for (const person of round.answer_set) {
    await expect(page.getByTestId("daily-panel")).not.toContainText(person.name);
  }
});

test("a streak breaks across a missed date", async ({ page }) => {
  const entryA = await entryFor(page, PINNED_DATE_A);
  const roundsA = await fetchRounds(page);
  const roundA = roundsA.find((r) => r.id === entryA.round_id)!;

  await gotoDaily(page, PINNED_DATE_A);
  await page.locator(`.chip[data-chip="${roundA.answer_set[0].id}"]`).click();
  await expect(page.getByTestId("stage")).toHaveAttribute("data-phase", "revealed");
  await expect(page.getByTestId("streak-line")).toContainText("Streak: 1 day");

  // Skip a date (not the immediately following calendar day) -- the streak
  // must reset to 1 on the next solve, not continue from 1.
  const laterDate = "2026-08-10";
  const laterEntry = await entryFor(page, laterDate);
  const rounds = await fetchRounds(page);
  const laterRound = rounds.find((r) => r.id === laterEntry.round_id)!;
  await gotoDaily(page, laterDate);
  await page.locator(`.chip[data-chip="${laterRound.answer_set[0].id}"]`).click();
  await expect(page.getByTestId("stage")).toHaveAttribute("data-phase", "revealed");
  await expect(page.getByTestId("streak-line")).toContainText("Streak: 1 day");
});

test("the hub daily card is live and links to /play/daily/", async ({ page }) => {
  await page.goto("/play/");
  const card = page.locator("a[data-mode-status='live']", {
    hasText: "Connection of the Day",
  });
  await expect(card).toHaveAttribute("href", "/play/daily/");
});

test("a date outside the committed schedule fails gracefully, never a derived fallback", async ({
  page,
}) => {
  await gotoDaily(page, OUT_OF_RANGE_DATE);
  await expect(page.getByTestId("stage")).toHaveAttribute("data-phase", "error");
  await expect(page.getByTestId("question")).toContainText(
    "has not been scheduled yet",
  );
  await expect(page.getByTestId("chip-tray")).toBeHidden();
});

test("a missing daily-manifest fetch fails gracefully", async ({ page }) => {
  await page.route("**/data/game/daily-manifest.v1.json", (route) =>
    route.fulfill({ status: 500, body: "boom" }),
  );
  await gotoDaily(page, PINNED_DATE_A);
  await expect(page.getByTestId("stage")).toHaveAttribute("data-phase", "error");
  await expect(page.getByTestId("question")).toContainText("Could not load today's schedule");
});

test("a manifest entry referencing a missing round is an integrity error, not a crash", async ({
  page,
}) => {
  const entry = await entryFor(page, PINNED_DATE_A);
  await page.route("**/data/game/rounds.v1.json", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.rounds = body.rounds.filter((r: { id: string }) => r.id !== entry.round_id);
    await route.fulfill({ response, json: body });
  });
  await gotoDaily(page, PINNED_DATE_A);
  await expect(page.getByTestId("stage")).toHaveAttribute("data-phase", "error");
  await expect(page.getByTestId("question")).toContainText("record set is missing");
});

test("a round whose content silently changed is an integrity error, not a spoofed round", async ({
  page,
}) => {
  const entry = await entryFor(page, PINNED_DATE_A);
  await page.route("**/data/game/rounds.v1.json", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    const round = body.rounds.find((r: { id: string }) => r.id === entry.round_id);
    // Tamper with a real published field without changing the id -- exactly
    // the case round_content_fingerprint exists to catch.
    round.distractors = [
      { id: 999999999, name: "Tampered Name", role_category: "guitar" },
      ...round.distractors,
    ];
    await route.fulfill({ response, json: body });
  });
  await gotoDaily(page, PINNED_DATE_A);
  await expect(page.getByTestId("stage")).toHaveAttribute("data-phase", "error");
  await expect(page.getByTestId("question")).toContainText("changed unexpectedly");
});

test("pre-existing daily results in storage survive the manifest migration untouched", async ({
  page,
}) => {
  // Simulate a user with stored results from before this change -- storage
  // is keyed by ISO date and was never touched by this migration, so old
  // entries (including a date this manifest doesn't even cover) must
  // survive a fresh page load unmodified.
  await page.goto("/play/");
  await page.evaluate(() => {
    window.localStorage.setItem(
      "np.game.v1",
      JSON.stringify({
        version: 1,
        totals: { played: 3, solved: 2, clean: 1, revealed: 1 },
        streak: { current: 2, best: 4, lastDailyDate: "2026-01-05" },
        seenRounds: ["conn-old-example"],
        daily: { "2026-01-04": "old share text", "2026-01-05": "old share text 2" },
      }),
    );
  });
  await gotoDaily(page, PINNED_DATE_A);
  await expect(page.getByTestId("stage")).toHaveAttribute("data-phase", "guessing");
  const stored = JSON.parse(
    (await page.evaluate(() => window.localStorage.getItem("np.game.v1"))) ?? "{}",
  );
  expect(stored.daily["2026-01-04"]).toBe("old share text");
  expect(stored.daily["2026-01-05"]).toBe("old share text 2");
  expect(stored.streak.best).toBe(4);
});

test("an error state announces to the assertive live region", async ({ page }) => {
  await gotoDaily(page, OUT_OF_RANGE_DATE);
  await expect(page.getByTestId("live-assertive")).toContainText("has not been scheduled yet");
});
