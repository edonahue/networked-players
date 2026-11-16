// Fixed calendar dates for the daily-game specs, derived from the committed
// manifest rather than written as literals.
//
// The daily manifest is append-only for already-played dates (ADR 0041,
// ADR 0066) and `data/integrity/daily-manifest-pin-v1.json` pins the played
// prefix, so the FIRST dates of the schedule can never be rewritten. The
// specs need dates that exist in the manifest, are consecutive (streak
// tests), and are far in the past (never "today"); the first scheduled dates
// satisfy all three for as long as the manifest exists.

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { DATA_DIR } from "./catalogFacts";

interface ManifestLite {
  schedule: { date: string }[];
}

const schedule = (
  JSON.parse(
    readFileSync(join(DATA_DIR, "game/daily-manifest.v1.json"), "utf8"),
  ) as ManifestLite
).schedule;

/** First scheduled date: an already-played, pinned date. */
export const PINNED_DATE_A = schedule[0].date;
/** The next calendar day (consecutive with A, for streak continuity). */
export const PINNED_DATE_B = schedule[1].date;
/** A later already-played pinned date that is NOT adjacent to A (streak-break
 * tests). Index 9 sits well inside the pinned prefix. */
export const PINNED_DATE_LATER = schedule[9].date;
