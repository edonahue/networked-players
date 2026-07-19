// Connection of the Day (docs/WEB_PRODUCT_PLAN.md §5, §12.6): deterministic
// date-derived round, one play per day, streaks, spoiler-free share string.
// Tests pin ?date= and compute the expected round node-side with the same
// seeded PRNG the page uses, so determinism is asserted from first
// principles rather than by reloading twice.

import { expect, test, type Page } from "@playwright/test";
import { createRng, dailySeed } from "../src/game/prng";

const DATE = "2026-03-05";

interface RoundLite {
  id: string;
  kind: string;
  answer_set: { id: number; name: string }[];
  distractors: { id: number; name: string }[];
}

async function fetchOneHop(page: Page): Promise<RoundLite[]> {
  const res = await page.request.get("/data/game/rounds.v1.json");
  const { rounds } = (await res.json()) as { rounds: RoundLite[] };
  return rounds.filter((round) => round.kind === "one_hop");
}

function expectedDaily(rounds: RoundLite[], isoDate: string): RoundLite {
  const seed = dailySeed(new Date(`${isoDate}T12:00:00Z`));
  return createRng(seed).shuffle(rounds)[0];
}

async function gotoDaily(page: Page, date = DATE): Promise<void> {
  await page.goto(`/play/daily/?date=${date}&motion=off`);
}

test("the daily deals the same date-derived round the seeded PRNG predicts", async ({
  page,
}) => {
  const rounds = await fetchOneHop(page);
  const expected = expectedDaily(rounds, DATE);

  await gotoDaily(page);
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-round",
    expected.id,
  );
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "guessing",
  );
  await expect(page.getByTestId("set-progress")).toHaveText(
    `Connection of the Day · ${DATE}`,
  );
  // A different date deals a different round (true for this pool + dates).
  await gotoDaily(page, "2026-03-06");
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-round",
    expectedDaily(rounds, "2026-03-06").id,
  );
});

test("solving the daily records a streak and builds a spoiler-free share string", async ({
  page,
}) => {
  const rounds = await fetchOneHop(page);
  const expected = expectedDaily(rounds, DATE);

  await gotoDaily(page);
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "guessing",
  );
  await page.locator(`.chip[data-chip="${expected.answer_set[0].id}"]`).click();
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "revealed",
  );

  const share = page.getByTestId("share-string");
  await expect(share).toContainText(`Connection of the Day ${DATE}`);
  await expect(share).toContainText("●");
  // Spoiler-free: no contributor name from the round appears in the share text.
  const shareText = (await share.textContent()) ?? "";
  for (const person of [...expected.answer_set, ...expected.distractors]) {
    expect(shareText).not.toContain(person.name);
  }

  await expect(page.getByTestId("streak-line")).toContainText("Streak: 1 day");
  await expect(page.getByTestId("share-copy")).toBeVisible();
  // No next round on the daily — one connection per day.
  await expect(page.getByTestId("next-round")).toBeHidden();

  const stored = JSON.parse(
    (await page.evaluate(() => window.localStorage.getItem("np.game.v1"))) ??
      "{}",
  );
  expect(stored.daily[DATE]).toContain(DATE);
  expect(stored.streak.current).toBe(1);
});

test("the daily refuses a second play and shows the recorded result instead", async ({
  page,
}) => {
  const rounds = await fetchOneHop(page);
  const expected = expectedDaily(rounds, DATE);

  await gotoDaily(page);
  await page.locator(`.chip[data-chip="${expected.answer_set[0].id}"]`).click();
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "revealed",
  );
  const firstShare = await page.getByTestId("share-string").textContent();

  await page.reload();
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "played",
  );
  await expect(page.getByTestId("chip-tray")).toBeHidden();
  await expect(page.getByTestId("clue-button")).toBeHidden();
  await expect(page.getByTestId("daily-panel")).toBeVisible();
  await expect(page.getByTestId("daily-panel")).toContainText(
    "Already in the crate",
  );
  await expect(page.getByTestId("share-string")).toHaveText(firstShare ?? "");
  // The recorded card never re-reveals the answer.
  for (const person of expected.answer_set) {
    await expect(page.getByTestId("daily-panel")).not.toContainText(
      person.name,
    );
  }
});

test("the hub daily card is live and links to /play/daily/", async ({
  page,
}) => {
  await page.goto("/play/");
  const card = page.locator("a[data-mode-status='live']", {
    hasText: "Connection of the Day",
  });
  await expect(card).toHaveAttribute("href", "/play/daily/");
});
