// Unit specs for the Connection of the Day archive's pure calendar logic
// (Slice I, dailyArchive.ts). No browser needed.

import { expect, test } from "@playwright/test";
import { buildArchiveDays } from "../src/game/dailyArchive";
import type { DailyEntry } from "../src/game/store";

const schedule = [
  { date: "2026-08-01", round_id: "r1", round_fingerprint: "f1" },
  { date: "2026-08-02", round_id: "r2", round_fingerprint: "f2" },
  { date: "2026-08-03", round_id: "r3", round_fingerprint: "f3" },
];

test("a played past date carries its recorded rating", () => {
  const daily: Record<string, DailyEntry> = {
    "2026-08-01": { shareString: "share text", rating: "clean" },
  };
  const days = buildArchiveDays(schedule, daily, "2026-08-03");
  expect(days[0]).toEqual({
    date: "2026-08-01",
    status: "played",
    rating: "clean",
  });
});

test("a scheduled past date with no local record is unplayed, not missed", () => {
  const days = buildArchiveDays(schedule, {}, "2026-08-03");
  expect(days[1]).toEqual({
    date: "2026-08-02",
    status: "unplayed",
    rating: null,
  });
});

test("today counts as playable, not future", () => {
  const daily: Record<string, DailyEntry> = {
    "2026-08-03": { shareString: "share text", rating: "with_clues" },
  };
  const days = buildArchiveDays(schedule, daily, "2026-08-03");
  expect(days[2]).toEqual({
    date: "2026-08-03",
    status: "played",
    rating: "with_clues",
  });
});

test("a date after today is future and never carries a rating, even if local storage somehow has one", () => {
  const futureSchedule = [
    ...schedule,
    { date: "2026-08-04", round_id: "r4", round_fingerprint: "f4" },
  ];
  const daily: Record<string, DailyEntry> = {
    "2026-08-04": { shareString: "should never surface", rating: "clean" },
  };
  const days = buildArchiveDays(futureSchedule, daily, "2026-08-03");
  expect(days[3]).toEqual({
    date: "2026-08-04",
    status: "future",
    rating: null,
  });
});
