import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import type { DailyManifestV1, RoundsV1, UniverseV1 } from "../src/data/rounds";

// Validates apps/web/public/data/game/{universe,rounds,daily-manifest}.v1.json
// structurally and cross-referentially, plus the leak/tone scan every other
// public artifact in this project gets (see cohort-manifest.spec.ts, which
// this mirrors). The Python pipeline's own validate_rounds_artifact and
// validate_daily_manifest already guarantee the artifact's contract before
// it is published here; this test exists to catch web-specific drift and to
// re-verify the artifact actually shipped to apps/web/public is what it
// claims to be.

const WEB_ROOT = fileURLToPath(new URL("..", import.meta.url));
const PUBLIC_ROOT = `${WEB_ROOT}public`;
const UNIVERSE_PATH = `${PUBLIC_ROOT}/data/game/universe.v1.json`;
const ROUNDS_PATH = `${PUBLIC_ROOT}/data/game/rounds.v1.json`;
const DAILY_PATH = `${PUBLIC_ROOT}/data/game/daily-manifest.v1.json`;

const FORBIDDEN_SUBSTRINGS = [
  "/home/",
  "data/private",
  "local/",
  ".ssh",
  "DISCOGS_TOKEN",
];
const FORBIDDEN_PHRASES = ["worked with", "collaborated with", "influenced"];
const STRENGTH_FLAGS = new Set([
  "co_billed_release_artists",
  "performer_credit",
  "non_performer_only",
]);
const SCOPE_FLAGS = new Set(["same_recording", "release_scope_credit"]);

function assertNoForbiddenContent(label: string, rawText: string) {
  const lowered = rawText.toLowerCase();
  for (const substring of FORBIDDEN_SUBSTRINGS) {
    expect(
      lowered,
      `${label} must not contain ${JSON.stringify(substring)}`,
    ).not.toContain(substring.toLowerCase());
  }
  for (const phrase of FORBIDDEN_PHRASES) {
    expect(
      lowered,
      `${label} must not contain ${JSON.stringify(phrase)}`,
    ).not.toContain(phrase);
  }
}

const universeRaw = readFileSync(UNIVERSE_PATH, "utf-8");
const roundsRaw = readFileSync(ROUNDS_PATH, "utf-8");
const dailyRaw = readFileSync(DAILY_PATH, "utf-8");
const universe: UniverseV1 = JSON.parse(universeRaw);
const rounds: RoundsV1 = JSON.parse(roundsRaw);
const daily: DailyManifestV1 = JSON.parse(dailyRaw);

test("game artifacts exist and parse", () => {
  expect(existsSync(UNIVERSE_PATH)).toBe(true);
  expect(existsSync(ROUNDS_PATH)).toBe(true);
  expect(existsSync(DAILY_PATH)).toBe(true);
  expect(universe).toBeTruthy();
  expect(rounds).toBeTruthy();
  expect(daily).toBeTruthy();
});

test("universe and rounds share the same pool_version as the daily manifest", () => {
  expect(rounds.pool_version).toBe(universe.pool_version);
  expect(daily.pool_version).toBe(universe.pool_version);
});

test("provenance says real, not synthetic", () => {
  expect(universe.provenance.generated_by.toLowerCase()).not.toContain(
    "synthetic",
  );
  expect(rounds.provenance.generated_by.toLowerCase()).not.toContain(
    "synthetic",
  );
  expect(universe.provenance.note).not.toContain("example.invalid");
});

test("every round's endpoints and distractors reference a real album", () => {
  const albumIds = new Set(universe.albums.map((a) => a.id));
  for (const round of rounds.rounds) {
    expect(
      albumIds.has(round.from_album_id),
      `round ${round.id} from_album_id ${round.from_album_id} is not a real album`,
    ).toBe(true);
    expect(
      albumIds.has(round.to_album_id),
      `round ${round.id} to_album_id ${round.to_album_id} is not a real album`,
    ).toBe(true);
    for (const distractor of round.distractors) {
      expect(
        albumIds.has(distractor.album_id),
        `round ${round.id} distractor ${distractor.album_id} is not a real album`,
      ).toBe(true);
    }
  }
});

test("every hop resolves to a real release, has an explicit role on both sides, and exactly one strength/scope flag", () => {
  const releaseIds = new Set(rounds.releases.map((r) => r.release_id));
  const artistIds = new Set(rounds.artists.map((a) => a.artist_id));

  for (const round of rounds.rounds) {
    const expectedHops = round.kind === "one_hop" ? 1 : 2;
    expect(round.hops.length, `round ${round.id} hop count`).toBe(expectedHops);

    for (const hop of round.hops) {
      expect(
        releaseIds.has(hop.release_id),
        `round ${round.id} hop references unpublished release ${hop.release_id}`,
      ).toBe(true);
      expect(artistIds.has(hop.artist_a_id)).toBe(true);
      expect(artistIds.has(hop.artist_b_id)).toBe(true);
      expect(hop.role_a, `round ${round.id} hop missing role_a`).toBeTruthy();
      expect(hop.role_b, `round ${round.id} hop missing role_b`).toBeTruthy();

      const strength = hop.quality_flags.filter((f) => STRENGTH_FLAGS.has(f));
      const scope = hop.quality_flags.filter((f) => SCOPE_FLAGS.has(f));
      expect(
        strength.length,
        `round ${round.id} hop must have exactly one strength flag, got ${JSON.stringify(hop.quality_flags)}`,
      ).toBe(1);
      expect(
        scope.length,
        `round ${round.id} hop must have exactly one scope flag, got ${JSON.stringify(hop.quality_flags)}`,
      ).toBe(1);
    }
  }
});

test("round ids are unique", () => {
  const ids = rounds.rounds.map((r) => r.id);
  expect(new Set(ids).size).toBe(ids.length);
});

test("daily schedule has no gaps, no duplicate dates, and no round scheduled twice", () => {
  const roundIds = new Set(rounds.rounds.map((r) => r.id));
  const seenDates = new Set<string>();
  const seenRounds = new Set<string>();
  let previous: Date | null = null;

  for (const entry of daily.schedule) {
    expect(
      roundIds.has(entry.round_id),
      `${entry.round_id} is not a real round`,
    ).toBe(true);
    expect(seenDates.has(entry.date), `duplicate date ${entry.date}`).toBe(
      false,
    );
    seenDates.add(entry.date);
    expect(
      seenRounds.has(entry.round_id),
      `round ${entry.round_id} scheduled twice`,
    ).toBe(false);
    seenRounds.add(entry.round_id);

    const current = new Date(`${entry.date}T00:00:00Z`);
    if (previous) {
      const dayMs = 24 * 60 * 60 * 1000;
      expect(
        current.getTime() - previous.getTime(),
        `gap before ${entry.date}`,
      ).toBe(dayMs);
    }
    previous = current;
  }
});

test("game artifacts are free of forbidden strings and phrasing", () => {
  assertNoForbiddenContent("universe.v1.json", universeRaw);
  assertNoForbiddenContent("rounds.v1.json", roundsRaw);
  assertNoForbiddenContent("daily-manifest.v1.json", dailyRaw);
});
