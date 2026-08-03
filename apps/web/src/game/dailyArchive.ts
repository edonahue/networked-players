// Connection of the Day archive/calendar (Slice I): cross-references the
// public, frozen `daily-manifest.v1.json` (ADR 0041/0043 -- scheduled dates
// are committed in advance, but never reveal round content ahead of time)
// against the local progression store's `daily` record. Pure logic only --
// no DOM here, so it's directly unit-testable; `dailyArchiveStage.ts` wires
// this to the page.
//
// Tripwire (docs/decisions -- Phase 2 plan): a future scheduled date must
// never render its round's content, even via a debug override. This module
// enforces that structurally -- the manifest schedule carries only
// `date`/`round_id`/`round_fingerprint`, never round content, so a future
// entry has nothing to leak in the first place. `isDateOverrideAllowed()`
// (dateOverride.ts) still gates the one existing `?date=` override on the
// daily page itself; this module doesn't add a second override path.

import type { DailyEntry } from "./store";
import type { DailyManifestEntry } from "./dailyManifest";

export type ArchiveDayStatus = "played" | "unplayed" | "future";

export interface ArchiveDay {
  date: string;
  status: ArchiveDayStatus;
  rating: DailyEntry["rating"] | null;
}

/** One entry per scheduled date, in schedule order. `future` dates
 * (strictly after `todayIsoDate`, the player's own local calendar date)
 * never carry a rating even if the local store somehow has an entry for
 * one (e.g. a clock changed backward) -- `unplayed`/`played` are only ever
 * derived for today or the past. */
export function buildArchiveDays(
  schedule: DailyManifestEntry[],
  daily: Record<string, DailyEntry>,
  todayIsoDate: string,
): ArchiveDay[] {
  return schedule.map((entry) => {
    if (entry.date > todayIsoDate) {
      return { date: entry.date, status: "future", rating: null };
    }
    const played = daily[entry.date];
    if (played) {
      return { date: entry.date, status: "played", rating: played.rating };
    }
    return { date: entry.date, status: "unplayed", rating: null };
  });
}
