// Connection of the Day (docs/WEB_PRODUCT_PLAN.md §5, §12.6): a frozen,
// append-only date -> round resolution via daily-manifest.v1.json (ADR
// 0043's corrective-slice-4.6 addendum) -- never a date-seeded derivation.
// Tests pin ?date= to real dates already committed in the published
// manifest (dates pinned via ?date= within the committed range) so nothing depends on the real
// wall-clock date.

import { expect, test, type Page } from "@playwright/test";

const PINNED_DATE_A = "2026-08-01";
const PINNED_DATE_B = "2026-08-02";
// Before the manifest's start_date -> friendly "upcoming". Kept well before
// any plausible launch date so this stays valid across launch-date migrations.
const PRE_LAUNCH_DATE = "2020-01-01";
// After the last scheduled date -> "schedule needs extending".
const POST_RANGE_DATE = "2030-12-01";

const _MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

/** The "Month D" launch label the upcoming state derives from the committed
 * manifest's own start_date -- never a hardcoded date. */
async function launchLabel(page: Page): Promise<string> {
  const manifest = await fetchManifest(page);
  const [, m, d] = manifest.start_date.split("-").map((n) => Number(n));
  return `${_MONTHS[m - 1]} ${d}`;
}

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
  if (!entry)
    throw new Error(`fixture date ${date} is not in the committed manifest`);
  return entry;
}

/** Playwright is the ONE place allowed to enable the ?date= override
 * (corrective slice 5.1, dateOverride.ts) -- injected via a page-scoped
 * global before navigation, never a production code path. Production
 * builds have no way to set this. */
async function allowDateOverride(page: Page): Promise<void> {
  await page.addInitScript(() => {
    (window as unknown as Record<string, unknown>).__NP_ALLOW_DATE_OVERRIDE__ =
      true;
  });
}

async function gotoDaily(page: Page, date: string): Promise<void> {
  await allowDateOverride(page);
  await page.goto(`/play/daily/?date=${date}&motion=off`);
}

test("the manifest is real, one-hop only, and covers the documented range", async ({
  page,
}) => {
  const manifest = await fetchManifest(page);
  const rounds = await fetchRounds(page);
  const byId = new Map(rounds.map((r) => [r.id, r]));
  expect(manifest.mode).toBe("connection_guesser_one_hop");
  // start_date is the (migratable) launch date; assert it equals the first
  // scheduled entry rather than a hardcoded date.
  expect(manifest.start_date).toBe(manifest.schedule[0].date);
  expect(manifest.schedule.length).toBeGreaterThanOrEqual(60);
  for (const entry of manifest.schedule) {
    expect(
      byId.get(entry.round_id)?.kind,
      `${entry.date} -> ${entry.round_id}`,
    ).toBe("one_hop");
  }
});

test("a pinned scheduled date resolves exactly to its manifest entry", async ({
  page,
}) => {
  const entry = await entryFor(page, PINNED_DATE_A);
  await gotoDaily(page, PINNED_DATE_A);
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-round",
    entry.round_id,
  );
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "guessing",
  );
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-kind",
    "one_hop",
  );
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
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-round",
    entryA.round_id,
  );

  await gotoDaily(page, PINNED_DATE_B);
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-round",
    entryB.round_id,
  );
});

test("reloading the same date never changes the resolved round", async ({
  page,
}) => {
  const entry = await entryFor(page, PINNED_DATE_A);
  await gotoDaily(page, PINNED_DATE_A);
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-round",
    entry.round_id,
  );
  await page.reload();
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-round",
    entry.round_id,
  );
});

test("a later scheduled date still resolves to its own frozen round (no drift)", async ({
  page,
}) => {
  const manifest = await fetchManifest(page);
  const laterEntry = manifest.schedule[manifest.schedule.length - 1];
  await gotoDaily(page, laterEntry.date);
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-round",
    laterEntry.round_id,
  );
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "guessing",
  );
});

test("solving the daily records a streak and builds a spoiler-free share string", async ({
  page,
}) => {
  const entry = await entryFor(page, PINNED_DATE_A);
  const rounds = await fetchRounds(page);
  const round = rounds.find((r) => r.id === entry.round_id)!;

  await gotoDaily(page, PINNED_DATE_A);
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "guessing",
  );
  await page.locator(`.chip[data-chip="${round.answer_set[0].id}"]`).click();
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "revealed",
  );

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
    (await page.evaluate(() => window.localStorage.getItem("np.game.v1"))) ??
      "{}",
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
  for (const person of round.answer_set) {
    await expect(page.getByTestId("daily-panel")).not.toContainText(
      person.name,
    );
  }
});

test("a streak breaks across a missed date", async ({ page }) => {
  const entryA = await entryFor(page, PINNED_DATE_A);
  const roundsA = await fetchRounds(page);
  const roundA = roundsA.find((r) => r.id === entryA.round_id)!;

  await gotoDaily(page, PINNED_DATE_A);
  await page.locator(`.chip[data-chip="${roundA.answer_set[0].id}"]`).click();
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "revealed",
  );
  await expect(page.getByTestId("streak-line")).toContainText("Streak: 1 day");

  // Skip a date (not the immediately following calendar day) -- the streak
  // must reset to 1 on the next solve, not continue from 1.
  const laterDate = "2026-08-10";
  const laterEntry = await entryFor(page, laterDate);
  const rounds = await fetchRounds(page);
  const laterRound = rounds.find((r) => r.id === laterEntry.round_id)!;
  await gotoDaily(page, laterDate);
  await page
    .locator(`.chip[data-chip="${laterRound.answer_set[0].id}"]`)
    .click();
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "revealed",
  );
  await expect(page.getByTestId("streak-line")).toContainText("Streak: 1 day");
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

test("a date before the first scheduled date shows a friendly upcoming state, not an error", async ({
  page,
}) => {
  const label = await launchLabel(page);
  await gotoDaily(page, PRE_LAUNCH_DATE);
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "upcoming",
  );
  await expect(page.getByTestId("question")).toContainText(`launches ${label}`);
  // Friendly, not an error: no gameplay control is active.
  await expect(page.getByTestId("chip-tray")).toBeHidden();
  await expect(page.getByTestId("clue-button")).toBeHidden();
  await expect(page.getByTestId("give-up")).toBeHidden();
  // Announced politely, never on the assertive channel.
  await expect(page.getByTestId("live-assertive")).toBeEmpty();
  await expect(page.getByTestId("live-region")).toContainText(
    `launches ${label}`,
  );
});

test("a date past the last scheduled date fails gracefully as an extension-needed error", async ({
  page,
}) => {
  await gotoDaily(page, POST_RANGE_DATE);
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "error",
  );
  await expect(page.getByTestId("question")).toContainText(
    "schedule needs extending",
  );
  await expect(page.getByTestId("chip-tray")).toBeHidden();
});

test("a missing daily-manifest fetch fails gracefully", async ({ page }) => {
  await page.route("**/data/game/daily-manifest.v1.json", (route) =>
    route.fulfill({ status: 500, body: "boom" }),
  );
  await gotoDaily(page, PINNED_DATE_A);
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "error",
  );
  await expect(page.getByTestId("question")).toContainText(
    "Could not load today's schedule",
  );
});

test("a manifest entry referencing a missing round is an integrity error, not a crash", async ({
  page,
}) => {
  const entry = await entryFor(page, PINNED_DATE_A);
  await page.route("**/data/game/rounds.v1.json", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.rounds = body.rounds.filter(
      (r: { id: string }) => r.id !== entry.round_id,
    );
    await route.fulfill({ response, json: body });
  });
  await gotoDaily(page, PINNED_DATE_A);
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "error",
  );
  await expect(page.getByTestId("question")).toContainText(
    "record set is missing",
  );
});

test("a round whose content silently changed is an integrity error, not a spoofed round", async ({
  page,
}) => {
  const entry = await entryFor(page, PINNED_DATE_A);
  await page.route("**/data/game/rounds.v1.json", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    const round = body.rounds.find(
      (r: { id: string }) => r.id === entry.round_id,
    );
    // Tamper with a real published field without changing the id -- exactly
    // the case round_content_fingerprint exists to catch.
    round.distractors = [
      { id: 999999999, name: "Tampered Name", role_category: "guitar" },
      ...round.distractors,
    ];
    await route.fulfill({ response, json: body });
  });
  await gotoDaily(page, PINNED_DATE_A);
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "error",
  );
  await expect(page.getByTestId("question")).toContainText(
    "changed unexpectedly",
  );
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
        daily: {
          "2026-01-04": "old share text",
          "2026-01-05": "old share text 2",
        },
      }),
    );
  });
  await gotoDaily(page, PINNED_DATE_A);
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "guessing",
  );
  const stored = JSON.parse(
    (await page.evaluate(() => window.localStorage.getItem("np.game.v1"))) ??
      "{}",
  );
  expect(stored.daily["2026-01-04"]).toBe("old share text");
  expect(stored.daily["2026-01-05"]).toBe("old share text 2");
  expect(stored.streak.best).toBe(4);
});

test("an error state announces to the assertive live region", async ({
  page,
}) => {
  await gotoDaily(page, POST_RANGE_DATE);
  await expect(page.getByTestId("live-assertive")).toContainText(
    "schedule needs extending",
  );
});

test("a malformed rounds fetch (null members) is an integrity error, not a crash", async ({
  page,
}) => {
  await page.route("**/data/game/rounds.v1.json", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    // Inject a null and a primitive member -- the resolver must not throw
    // when scanning for the scheduled round.
    body.rounds = [null, 42, ...body.rounds];
    await route.fulfill({ response, json: body });
  });
  await gotoDaily(page, PINNED_DATE_A);
  // The real scheduled round is still present after the junk, so it resolves;
  // the point is that the junk members never crash the scan.
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "guessing",
  );
});

// --- Corrective slice 5.1: full artifact verification -----------------------

/** Intercept the manifest fetch and hand back a version with `mutate`
 * applied -- for constructing integrity-failure scenarios that don't exist
 * in the real committed artifact. */
async function withMutatedManifest(
  page: Page,
  mutate: (manifest: DailyManifest) => void,
): Promise<void> {
  await page.route("**/data/game/daily-manifest.v1.json", async (route) => {
    const response = await route.fetch();
    const body = (await response.json()) as DailyManifest;
    mutate(body);
    await route.fulfill({ response, json: body });
  });
}

test("a wrong manifest mode is an integrity error, never dealt as a daily round", async ({
  page,
}) => {
  await withMutatedManifest(page, (m) => {
    m.mode = "record_routes";
  });
  await gotoDaily(page, PINNED_DATE_A);
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "error",
  );
  await expect(page.getByTestId("question")).toContainText("don't match");
  await expect(page.getByTestId("chip-tray")).toBeHidden();
});

test("an unsupported manifest schema_version is an integrity error", async ({
  page,
}) => {
  await withMutatedManifest(page, (m) => {
    (m as unknown as Record<string, unknown>).schema_version = 99;
  });
  await gotoDaily(page, PINNED_DATE_A);
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "error",
  );
  await expect(page.getByTestId("question")).toContainText("don't match");
});

test("a catalog_version mismatch between manifest and rounds is an integrity error", async ({
  page,
}) => {
  await withMutatedManifest(page, (m) => {
    (m as unknown as Record<string, unknown>).catalog_version =
      "catalog-v1-20260601-different";
  });
  await gotoDaily(page, PINNED_DATE_A);
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "error",
  );
  await expect(page.getByTestId("question")).toContainText("don't match");
});

test("a pool_version mismatch between manifest and rounds is an integrity error", async ({
  page,
}) => {
  await withMutatedManifest(page, (m) => {
    (m as unknown as Record<string, unknown>).pool_version =
      "connection-v1-20260601-different";
  });
  await gotoDaily(page, PINNED_DATE_A);
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "error",
  );
  await expect(page.getByTestId("question")).toContainText("don't match");
});

test("an artifact_version mismatch between manifest and rounds is an integrity error", async ({
  page,
}) => {
  await withMutatedManifest(page, (m) => {
    (m as unknown as Record<string, unknown>).artifact_version =
      "connection-artifact-v1-20260601-different";
  });
  await gotoDaily(page, PINNED_DATE_A);
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "error",
  );
  await expect(page.getByTestId("question")).toContainText("don't match");
});

test("a manifest entry pointing at a real two-hop round is refused, never dealt as a daily", async ({
  page,
}) => {
  const rounds = await fetchRounds(page);
  const rawRoundsRes = await page.request.get("/data/game/rounds.v1.json");
  const rawRounds = (await rawRoundsRes.json()) as {
    rounds: Record<string, unknown>[];
  };
  const twoHop = rounds.find((r) => r.kind === "two_hop")!;
  const twoHopRaw = rawRounds.rounds.find((r) => r.id === twoHop.id)!;
  const { roundContentFingerprint } = await import("../src/game/canonical");
  const fingerprint = await roundContentFingerprint(twoHopRaw);

  await withMutatedManifest(page, (m) => {
    m.schedule[0] = {
      date: PINNED_DATE_A,
      round_id: twoHop.id,
      round_fingerprint: fingerprint,
    };
  });
  await gotoDaily(page, PINNED_DATE_A);
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "error",
  );
  await expect(page.getByTestId("question")).toContainText(
    "does not point at a valid daily round",
  );
  await expect(page.getByTestId("chip-tray")).toBeHidden();
});

test("a manifest entry pointing at an injected synthetic round is refused", async ({
  page,
}) => {
  const { roundContentFingerprint } = await import("../src/game/canonical");
  const syntheticRound = {
    id: "conn-00000000ff",
    pool: "synthetic-universe",
    kind: "one_hop",
    difficulty: "hard",
    endpoints: [
      {
        id: "syn-a",
        title: "Synth A",
        year: 1990,
        act: "X",
        label: null,
        art: null,
      },
      {
        id: "syn-c",
        title: "Synth C",
        year: 1991,
        act: "Y",
        label: null,
        art: null,
      },
    ],
    answer_set: [
      { id: 90000001, name: "Synthetic Performer", role_category: "guitar" },
    ],
    distractors: [],
    clues: [],
    evidence: [
      {
        release_ref: "syn-a",
        release_title: "Synth A",
        contributor_id: 90000001,
        credited_as: "Synthetic Performer",
        role_text: "Guitar",
        credit_scope: "release_credit",
      },
    ],
    provenance_note: "test",
  };
  const fingerprint = await roundContentFingerprint(syntheticRound);

  await page.route("**/data/game/rounds.v1.json", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.rounds.push(syntheticRound);
    await route.fulfill({ response, json: body });
  });
  await withMutatedManifest(page, (m) => {
    m.schedule[0] = {
      date: PINNED_DATE_A,
      round_id: syntheticRound.id,
      round_fingerprint: fingerprint,
    };
  });
  await gotoDaily(page, PINNED_DATE_A);
  await expect(page.getByTestId("stage")).toHaveAttribute(
    "data-phase",
    "error",
  );
  await expect(page.getByTestId("question")).toContainText(
    "does not point at a valid daily round",
  );
  for (const person of [syntheticRound.answer_set[0]]) {
    await expect(page.getByTestId("question")).not.toContainText(person.name);
  }
});

test("production ignores ?date= entirely -- no override gate, no injected global", async ({
  page,
}) => {
  // Deliberately NOT calling allowDateOverride: this is what a real
  // production visitor's browser looks like. The pinned date is a real
  // scheduled date, but without the gate it must never be honored -- the
  // effective date falls back to the (unscheduled, in this sandbox) real
  // local date instead of silently trusting the query string.
  await page.goto(`/play/daily/?date=${PINNED_DATE_A}&motion=off`);
  const entry = await entryFor(page, PINNED_DATE_A);
  // The override is ignored, so the pinned date's round is never dealt: the
  // stage never carries that round_id. (Which graceful/played state the real
  // wall-clock date lands in -- upcoming before the start date, a different
  // round in range, or extension-needed after -- is deliberately not
  // asserted, to keep this independent of the real date.)
  await expect(page.getByTestId("stage")).not.toHaveAttribute(
    "data-round",
    entry.round_id,
  );
  // And it is never the playable state for the pinned round specifically.
  const phase = await page.getByTestId("stage").getAttribute("data-phase");
  expect(phase).not.toBeNull();
});
