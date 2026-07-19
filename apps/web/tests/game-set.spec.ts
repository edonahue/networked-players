// The five-round session arc (docs/WEB_PRODUCT_PLAN.md §5): pure-node specs
// for the set-state helpers, plus browser specs for progress, the summary
// card, and the fresh-set handoff. Browser flows pin rounds and disable
// motion for determinism.

import { expect, test, type Page } from "@playwright/test";
import {
  freshSet,
  loadSet,
  recordSetRound,
  SET_KEY,
  SET_SIZE,
  setComplete,
  type StorageLike,
} from "../src/game/store";

function memoryStorage(initial: Record<string, string> = {}): StorageLike {
  const data = new Map(Object.entries(initial));
  return {
    getItem: (key) => data.get(key) ?? null,
    setItem: (key, value) => void data.set(key, value),
  };
}

test("loadSet starts fresh on missing, corrupt, kind-mismatched, or complete state", () => {
  expect(loadSet(null, "one_hop", "s").entries).toEqual([]);
  expect(loadSet(memoryStorage(), "one_hop", "s").seed).toBe("s");
  expect(
    loadSet(memoryStorage({ [SET_KEY]: "not json" }), "one_hop", "s").entries,
  ).toEqual([]);

  let set = freshSet("two_hop", "old");
  set = recordSetRound(set, "syn-1h-x", "clean");
  const stored = memoryStorage({ [SET_KEY]: JSON.stringify(set) });
  // Same kind: the sitting continues, keeping its own seed.
  expect(loadSet(stored, "two_hop", "new").seed).toBe("old");
  expect(loadSet(stored, "two_hop", "new").entries).toHaveLength(1);
  // Different kind: a fresh sitting.
  expect(loadSet(stored, "one_hop", "new").entries).toEqual([]);

  let full = freshSet("one_hop", "s");
  for (let i = 0; i < SET_SIZE; i += 1) {
    full = recordSetRound(full, `r${i}`, "clean");
  }
  expect(setComplete(full)).toBe(true);
  expect(
    loadSet(memoryStorage({ [SET_KEY]: JSON.stringify(full) }), "one_hop", "s2")
      .entries,
  ).toEqual([]);
});

test("recordSetRound appends without mutating and setComplete flips at five", () => {
  const set = freshSet("one_hop", "s");
  const next = recordSetRound(set, "a", "with_clues");
  expect(set.entries).toHaveLength(0);
  expect(next.entries).toEqual([{ roundId: "a", rating: "with_clues" }]);
  expect(setComplete(next)).toBe(false);
});

// --- Browser flows ---------------------------------------------------------

interface RoundLite {
  id: string;
  kind: string;
  answer_set: { id: number }[];
}

async function fetchOneHop(page: Page): Promise<RoundLite[]> {
  const res = await page.request.get("/data/game/rounds.v1.json");
  const { rounds } = (await res.json()) as { rounds: RoundLite[] };
  return rounds.filter((round) => round.kind === "one_hop");
}

async function solvePinned(page: Page, round: RoundLite): Promise<void> {
  await page.goto(`/play/connection/?round=${round.id}&motion=off`);
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "guessing",
  );
  await page.locator(`.chip[data-chip="${round.answer_set[0].id}"]`).click();
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "revealed",
  );
}

test("a sitting counts rounds and advances within the set", async ({
  page,
}) => {
  const [first, second] = await fetchOneHop(page);
  await page.goto("/play/connection/?motion=off&seed=fixed");
  await expect(page.getByTestId("set-progress")).toHaveText("Round 1 of 5");

  await solvePinned(page, first);
  await expect(page.getByTestId("set-progress")).toContainText("Round 2 of 5");
  await expect(page.getByTestId("set-progress")).toContainText("●");
  await expect(page.getByTestId("next-round")).toHaveText(
    "Next round (2 of 5)",
  );
  await expect(page.getByTestId("set-summary")).toBeHidden();

  // The next round continues the same sitting.
  await solvePinned(page, second);
  await expect(page.getByTestId("set-progress")).toContainText("Round 3 of 5");
  const stored = await page.evaluate(() =>
    window.sessionStorage.getItem("np.set.v1"),
  );
  expect(JSON.parse(stored ?? "{}").entries).toHaveLength(2);
});

test("the fifth round completes the set with a needle-drop summary", async ({
  page,
}) => {
  const rounds = await fetchOneHop(page);
  const fifth = rounds[4];
  // Seed a sitting with four rounds already played (once — an init script
  // would re-seed on every navigation and clobber the post-set fresh state).
  await page.goto(`/play/connection/?round=${fifth.id}&motion=off`);
  await page.evaluate(
    ([key, value]) => window.sessionStorage.setItem(key, value),
    [
      "np.set.v1",
      JSON.stringify({
        version: 1,
        kind: "one_hop",
        seed: "fixed",
        entries: [
          { roundId: rounds[0].id, rating: "clean" },
          { roundId: rounds[1].id, rating: "clean" },
          { roundId: rounds[2].id, rating: "with_clues" },
          { roundId: rounds[3].id, rating: "revealed" },
        ],
      }),
    ] as [string, string],
  );
  await page.reload();

  await solvePinned(page, fifth);
  const summary = page.getByTestId("set-summary");
  await expect(summary).toBeVisible();
  await expect(summary).toContainText("Set complete");
  await expect(summary.locator(".set-summary__glyphs")).toHaveText("● ● ◐ ○ ●");
  await expect(summary).toContainText("5 rounds this sitting");
  await expect(summary).toContainText("3 clean");
  await expect(page.getByTestId("set-progress")).toContainText("Set complete");
  await expect(page.getByTestId("next-round")).toHaveText("Start a new set");

  // Starting a new set resets the sitting.
  await page.getByTestId("next-round").click();
  await expect(page.getByTestId("set-progress")).toHaveText("Round 1 of 5");
  await expect(page.getByTestId("set-summary")).toBeHidden();
});
