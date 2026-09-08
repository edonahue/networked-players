// Integration test for the Connection of the Day archive page (Slice I):
// a real played date renders as played with its rating, and a real
// scheduled future date (relative to the actual wall-clock date, since the
// archive page itself never accepts the ?date= override -- only
// game/flagship.ts's daily round does) renders as "future" with no round
// content ever fetched or leaked.

import { expect, test, type Page } from "@playwright/test";

const PINNED_DATE_A = "2026-08-01";

interface DailyManifestEntry {
  date: string;
  round_id: string;
  /** schema v2 only: which frozen generation this date resolves against. */
  generation?: string;
}

interface DailyManifestGeneration {
  generation_id: string;
  rounds_url: string;
}

interface DailyManifest {
  schedule: DailyManifestEntry[];
  /** schema v2 only (ADR 0066); absent on a v1 manifest. */
  generations?: DailyManifestGeneration[];
}

interface RoundLite {
  id: string;
  answer_set: { id: number; name: string }[];
  distractors: { id: number; name: string }[];
}

async function fetchManifest(page: Page): Promise<DailyManifest> {
  const res = await page.request.get("/data/game/daily-manifest.v1.json");
  return (await res.json()) as DailyManifest;
}

/** The pool THIS date resolves against -- its own generation's under
 * schema v2, where a retired generation's dates live in a frozen copy and
 * are NOT guaranteed to also appear in the live pool. Reading the live
 * artifact unconditionally would hand back `undefined` for any archive date
 * from a retired generation. */
async function roundsForEntry(
  page: Page,
  manifest: DailyManifest,
  entry: DailyManifestEntry,
): Promise<RoundLite[]> {
  const generation = manifest.generations?.find(
    (g) => g.generation_id === entry.generation,
  );
  const res = await page.request.get(
    generation?.rounds_url ?? "/data/game/rounds.v1.json",
  );
  const { rounds } = (await res.json()) as { rounds: RoundLite[] };
  return rounds;
}

test("a played date shows its rating and a future scheduled date leaks nothing", async ({
  page,
}) => {
  const manifest = await fetchManifest(page);
  const entry = manifest.schedule.find((e) => e.date === PINNED_DATE_A)!;
  const rounds = await roundsForEntry(page, manifest, entry);
  const round = rounds.find((r) => r.id === entry.round_id);
  if (!round)
    throw new Error(
      `round ${entry.round_id} for ${PINNED_DATE_A} is not in generation ${entry.generation ?? "(v1)"}'s pool`,
    );

  // Play the pinned past date via the one allowed ?date= override.
  await page.addInitScript(() => {
    (window as unknown as Record<string, unknown>).__NP_ALLOW_DATE_OVERRIDE__ =
      true;
  });
  await page.goto(`/play/daily/?date=${PINNED_DATE_A}&motion=off`);
  await page.locator(`.chip[data-chip="${round.answer_set[0].id}"]`).click();
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "revealed",
  );

  await page.goto("/play/daily/archive/");
  const archive = page.locator("[data-testid='daily-archive']");
  await expect(archive).toBeVisible();

  const playedDay = archive.locator(
    `.archive-day[data-status="played"] .archive-day__date:text-is("${PINNED_DATE_A}")`,
  );
  await expect(playedDay).toBeVisible();
  const playedRow = archive.locator(
    `.archive-day:has(.archive-day__date:text-is("${PINNED_DATE_A}"))`,
  );
  await expect(playedRow).toHaveAttribute("data-status", "played");
  await expect(playedRow.locator(".archive-day__status")).toContainText(
    /played/i,
  );

  // The LAST scheduled date -- read from the manifest rather than hardcoded,
  // since the horizon moves every time the schedule is extended -- must
  // render as future, with no round content anywhere on the page.
  const futureEntry = manifest.schedule[manifest.schedule.length - 1];
  const futureRow = archive.locator(
    `.archive-day:has(.archive-day__date:text-is("${futureEntry.date}"))`,
  );
  await expect(futureRow).toHaveAttribute("data-status", "future");

  const bodyText = (await page.textContent("body")) ?? "";
  for (const person of [...round.answer_set, ...round.distractors]) {
    expect(bodyText).not.toContain(person.name);
  }

  await expect(archive.locator("[data-archive-stats]")).toContainText(
    /streak/i,
  );
});
