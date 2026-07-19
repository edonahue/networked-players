// Phone-viewport coverage for the flagship (plan §12.8/§13): a full one-hop
// round on a 390×844 screen — the mobile-first loop the product decisions
// centered on. Asserts playability and that the page never scrolls sideways.

import { expect, test, type Page } from "@playwright/test";

test.use({ viewport: { width: 390, height: 844 } });

interface RoundLite {
  id: string;
  kind: string;
  answer_set: { id: number }[];
}

async function firstOneHop(page: Page): Promise<RoundLite> {
  const res = await page.request.get("/data/game/rounds.v1.json");
  const { rounds } = (await res.json()) as { rounds: RoundLite[] };
  const round = rounds.find((r) => r.kind === "one_hop");
  if (!round) throw new Error("no one-hop round in the artifact");
  return round;
}

test("a full one-hop round plays on a phone-sized screen without sideways scroll", async ({
  page,
}) => {
  const round = await firstOneHop(page);
  await page.goto(`/play/connection/?round=${round.id}&motion=off`);
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "guessing",
  );

  // No horizontal overflow at any point in the round.
  const overflow = () =>
    page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
  expect(await overflow()).toBeLessThanOrEqual(0);

  // Both sleeves and the tray are on screen and tappable.
  await expect(page.getByTestId("sleeve-a")).toBeVisible();
  await expect(page.getByTestId("sleeve-b")).toBeVisible();
  const answerChip = page.locator(
    `.chip[data-chip="${round.answer_set[0].id}"]`,
  );
  await answerChip.scrollIntoViewIfNeeded();
  await answerChip.click();

  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "revealed",
  );
  await expect(page.getByTestId("verdict-heading")).toBeFocused();
  await expect(page.getByTestId("evidence-sheet")).toBeVisible();
  expect(await overflow()).toBeLessThanOrEqual(0);
});
