// Browser tests for the flagship one-hop Connection Guesser
// (docs/WEB_PRODUCT_PLAN.md §5, §12.3). Rounds are pinned via ?round= and
// motion is disabled via ?motion=off so every flow is deterministic. The
// round pool is read from the served artifact rather than hardcoding
// contributor names.

import { expect, test, type Page } from "@playwright/test";

interface RoundLite {
  id: string;
  kind: string;
  pool: string;
  answer_set: { id: number; name: string }[];
  distractors: { id: number; name: string }[];
  clues: { kind: string; text: string }[];
  evidence: unknown[];
}

async function fetchRounds(page: Page): Promise<RoundLite[]> {
  const res = await page.request.get("/data/game/rounds.v1.json");
  const { rounds } = (await res.json()) as { rounds: RoundLite[] };
  return rounds.filter((round) => round.kind === "one_hop");
}

function playUrl(round: RoundLite): string {
  return `/play/connection/?round=${round.id}&motion=off`;
}

/** Navigate to a pinned round and wait until the engine accepts guesses. */
async function gotoRound(page: Page, round: RoundLite): Promise<void> {
  await page.goto(playUrl(round));
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "guessing",
  );
}

test("a pinned round deals, presents chips, and never marks the answer before reveal", async ({
  page,
}) => {
  const [round] = await fetchRounds(page);
  await page.goto(playUrl(round));

  // Motion off is honored (deal collapses, page is immediately playable).
  await expect(page.locator("html")).toHaveAttribute("data-motion", "off");
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "guessing",
  );

  // Both sleeves and captions render, and the tray holds every option.
  await expect(page.getByTestId("caption-a")).not.toBeEmpty();
  await expect(page.getByTestId("caption-b")).not.toBeEmpty();

  // The premise is performer-specific, not a bare "credited on both" claim
  // (a non-performer credit like producer/engineer wouldn't satisfy it --
  // see eligibility.py; corrective slice 4.6).
  await expect(page.getByTestId("question")).toContainText("eligible performer");
  const chips = page.locator(".chip");
  await expect(chips).toHaveCount(
    round.answer_set.length + round.distractors.length,
  );

  // Game integrity: nothing in the page distinguishes the correct chip
  // before the round resolves.
  await expect(page.locator("[data-chip-state='correct']")).toHaveCount(0);
  await expect(page.locator("[aria-checked='true']")).toHaveCount(0);
  await expect(page.getByTestId("verdict")).toBeHidden();
  await expect(page.getByTestId("evidence-sheet")).toBeHidden();
});

test("choosing the credited contributor solves the round and opens the liner notes", async ({
  page,
}) => {
  const [round] = await fetchRounds(page);
  await gotoRound(page, round);

  const answer = round.answer_set[0];
  await page.locator(`.chip[data-chip="${answer.id}"]`).click();

  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "revealed",
  );
  await expect(page.getByTestId("verdict-heading")).toContainText("Solved");
  await expect(page.getByTestId("verdict-heading")).toContainText(answer.name);
  await expect(page.getByTestId("verdict-rating")).toContainText("Clean");
  // Focus lands on the verdict for keyboard/screen-reader users.
  await expect(page.getByTestId("verdict-heading")).toBeFocused();

  // The liner notes open with an evidence table and an honest provenance line.
  const sheet = page.getByTestId("evidence-sheet");
  await expect(sheet).toBeVisible();
  expect(await sheet.locator("tbody tr").count()).toBeGreaterThanOrEqual(2);
  await expect(page.getByTestId("provenance-note")).not.toBeEmpty();

  // Local progression recorded under the versioned key.
  const stored = await page.evaluate(() =>
    window.localStorage.getItem("np.game.v1"),
  );
  expect(stored).not.toBeNull();
  const parsed = JSON.parse(stored ?? "{}");
  expect(parsed.totals.played).toBe(1);
  expect(parsed.totals.solved).toBe(1);
  expect(parsed.seenRounds).toContain(round.id);
});

test("two wrong picks resolve the round as revealed with the answer shown", async ({
  page,
}) => {
  const rounds = await fetchRounds(page);
  const round = rounds.find((r) => r.distractors.length >= 2);
  if (!round) throw new Error("no one-hop round with two distractors");
  await gotoRound(page, round);

  await page.locator(`.chip[data-chip="${round.distractors[0].id}"]`).click();
  await expect(
    page.locator(`.chip[data-chip="${round.distractors[0].id}"]`),
  ).toHaveAttribute("data-chip-state", "struck");
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "guessing",
  );

  await page.locator(`.chip[data-chip="${round.distractors[1].id}"]`).click();
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "revealed",
  );
  await expect(page.getByTestId("verdict-heading")).toContainText(
    "The answer was",
  );
  // Only now is the correct chip marked.
  await expect(page.locator("[data-chip-state='correct']")).toHaveCount(
    round.answer_set.length,
  );
});

test("the clue ladder reveals clues in order and downgrades the rating", async ({
  page,
}) => {
  const [round] = await fetchRounds(page);
  await gotoRound(page, round);

  const clueButton = page.getByTestId("clue-button");
  await clueButton.click();
  const clueItems = page.getByTestId("clue-list").locator("li");
  await expect(clueItems).toHaveCount(1);
  await expect(clueItems.first()).toContainText(round.clues[0].text);

  await page.locator(`.chip[data-chip="${round.answer_set[0].id}"]`).click();
  await expect(page.getByTestId("verdict-rating")).toContainText(
    "Solved with help",
  );
});

test("giving up reveals the answer honestly", async ({ page }) => {
  const [round] = await fetchRounds(page);
  await gotoRound(page, round);

  await page.getByTestId("give-up").click();
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "revealed",
  );
  await expect(page.getByTestId("verdict-rating")).toContainText("Revealed");
  await expect(page.getByTestId("evidence-sheet")).toBeVisible();
});

test("the chip tray is a keyboard radiogroup with roving focus", async ({
  page,
}) => {
  const [round] = await fetchRounds(page);
  await gotoRound(page, round);

  const tray = page.getByTestId("chip-tray");
  await expect(tray).toHaveAttribute("role", "radiogroup");
  const chips = tray.locator(".chip");
  await expect(chips.first()).toHaveAttribute("tabindex", "0");

  await chips.first().focus();
  await page.keyboard.press("ArrowRight");
  await expect(chips.nth(1)).toBeFocused();
  await expect(chips.nth(1)).toHaveAttribute("tabindex", "0");
  await expect(chips.first()).toHaveAttribute("tabindex", "-1");
  await page.keyboard.press("ArrowLeft");
  await expect(chips.first()).toBeFocused();

  // Enter/Space activates the focused chip like any button.
  const answerChip = tray.locator(
    `.chip[data-chip="${round.answer_set[0].id}"]`,
  );
  await answerChip.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "revealed",
  );
});

test("the hub card for the Connection Guesser is live and links here", async ({
  page,
}) => {
  await page.goto("/play/");
  const card = page.locator("a[data-mode-status='live']", {
    hasText: "Connection Guesser",
  });
  await expect(card).toHaveAttribute("href", "/play/connection/");
  await card.click();
  await expect(page).toHaveURL(/\/play\/connection\/$/);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "credited on both",
  );
});
