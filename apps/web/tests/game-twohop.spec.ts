// Browser tests for two-hop rounds (docs/WEB_PRODUCT_PLAN.md §5, §12.4):
// bridges-then-hidden-middle on the flagship stage. Rounds are pinned via
// ?round= and motion disabled via ?motion=off, with round material read from
// the served artifact rather than hardcoded.

import { expect, test, type Page } from "@playwright/test";

interface TwoHopRound {
  id: string;
  kind: string;
  endpoints: { id: string; title: string }[];
  middle: { album: { id: string; title: string }; choices: { id: string }[] };
  answer_set: { id: number; name: string }[];
  bridge_answer_sets: [
    { id: number; name: string }[],
    { id: number; name: string }[],
  ];
  distractors: { id: number; name: string }[];
}

async function fetchTwoHop(page: Page): Promise<TwoHopRound[]> {
  const res = await page.request.get("/data/game/rounds.v1.json");
  const { rounds } = (await res.json()) as { rounds: TwoHopRound[] };
  return rounds.filter((round) => round.kind === "two_hop");
}

async function gotoRound(page: Page, round: TwoHopRound): Promise<void> {
  await page.goto(`/play/connection/?round=${round.id}&motion=off`);
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "guessing",
  );
}

test("a two-hop round shows the face-down middle slot and never leaks the middle", async ({
  page,
}) => {
  const [round] = await fetchTwoHop(page);
  await gotoRound(page, round);

  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-kind",
    "two_hop",
  );
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-step",
    "bridge_a",
  );
  await expect(page.getByTestId("step-label")).toContainText("Step 1 of 3");
  const middleSlot = page.getByTestId("middle-slot");
  await expect(middleSlot).toBeVisible();
  await expect(page.getByTestId("caption-middle")).toHaveText("Hidden record");
  // The hidden record's title appears nowhere in the visible stage.
  await expect(page.getByTestId("stage")).not.toContainText(
    round.middle.album.title,
  );
  await expect(page.locator("[data-chip-state='correct']")).toHaveCount(0);
  await expect(page.locator("[aria-checked='true']")).toHaveCount(0);
});

test("walking bridge_a, bridge_b, then the middle solves the round", async ({
  page,
}) => {
  const [round] = await fetchTwoHop(page);
  await gotoRound(page, round);

  const [bridgeA, bridgeB] = round.bridge_answer_sets;
  await page.locator(`.chip[data-chip="${bridgeA[0].id}"]`).click();
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-step",
    "bridge_b",
  );
  await expect(page.getByTestId("step-label")).toContainText("Step 2 of 3");

  await page.locator(`.chip[data-chip="${bridgeB[0].id}"]`).click();
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-step",
    "middle",
  );
  // The middle tray offers album choices, still nothing marked correct.
  await expect(page.locator(".chip--album")).toHaveCount(
    round.middle.choices.length,
  );
  await expect(page.locator("[data-chip-state='correct']")).toHaveCount(0);

  await page.locator(`.chip[data-chip="${round.middle.album.id}"]`).click();
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "revealed",
  );
  await expect(page.getByTestId("verdict-heading")).toContainText("Solved");
  await expect(page.getByTestId("verdict-heading")).toContainText(
    round.middle.album.title,
  );
  await expect(page.getByTestId("verdict-rating")).toContainText("Clean");
  // The face-down slot flips to the real record.
  await expect(page.getByTestId("caption-middle")).toContainText(
    round.middle.album.title,
  );
  // Evidence spans both endpoints and the middle.
  expect(
    await page.getByTestId("evidence-sheet").locator("tbody tr").count(),
  ).toBeGreaterThanOrEqual(3);
});

test("failing mid-walk reveals the full path honestly", async ({ page }) => {
  const rounds = await fetchTwoHop(page);
  const round = rounds.find((r) => r.distractors.length >= 2);
  if (!round) throw new Error("no two-hop round with two distractors");
  await gotoRound(page, round);

  // Solve bridge_a, then burn both attempts on distractors in bridge_b.
  await page
    .locator(`.chip[data-chip="${round.bridge_answer_sets[0][0].id}"]`)
    .click();
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-step",
    "bridge_b",
  );
  await page.locator(`.chip[data-chip="${round.distractors[0].id}"]`).click();
  await page.locator(`.chip[data-chip="${round.distractors[1].id}"]`).click();

  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "revealed",
  );
  await expect(page.getByTestId("verdict-heading")).toContainText(
    "The answer was",
  );
  await expect(page.getByTestId("verdict-heading")).toContainText(
    round.middle.album.title,
  );
  await expect(page.getByTestId("verdict-rating")).toContainText("Revealed");
  await expect(page.getByTestId("caption-middle")).toContainText(
    round.middle.album.title,
  );
});

test("the kind toggle deals a two-hop round without pinning", async ({
  page,
}) => {
  await page.goto("/play/connection/?kind=two_hop&motion=off&seed=fixed");
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-kind",
    "two_hop",
  );
  await expect(
    page.locator("[data-testid='kind-toggle'] a[data-kind='two_hop']"),
  ).toHaveAttribute("aria-current", "true");
  // Default (no param) stays one-hop.
  await page.goto("/play/connection/?motion=off&seed=fixed");
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-kind",
    "one_hop",
  );
  await expect(
    page.locator("[data-testid='kind-toggle'] a[data-kind='one_hop']"),
  ).toHaveAttribute("aria-current", "true");
});
