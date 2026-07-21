// Unit specs for localDate.ts -- pure-node tests in the Playwright runner
// (same pattern as game-canonical.spec.ts: no browser, no server).
// Corrective slice 5.1: Connection of the Day rolls over at the player's
// LOCAL calendar midnight, not UTC -- these tests prove localIsoDate reads
// the runtime's local-time getters, by varying process.env.TZ around a
// single fixed UTC instant near a real timezone-offset boundary.

import { expect, test } from "@playwright/test";
import { localIsoDate } from "../src/game/localDate";

test("localIsoDate formats a local date with zero-padded month and day", () => {
  const date = new Date(2026, 0, 5, 10, 30); // local Jan 5, 2026
  expect(localIsoDate(date)).toBe("2026-01-05");
});

test("localIsoDate rolls over at LOCAL midnight, independent of the UTC date", () => {
  // A single fixed instant: 2026-08-01T23:30:00Z. In UTC+1 that is already
  // local Aug 2 (past local midnight); in UTC-5 it is still local Aug 1
  // (four and a half hours before local midnight). A UTC-based
  // implementation (toISOString().slice(0,10)) would report "2026-08-01"
  // for BOTH -- this proves localIsoDate does not do that.
  const instant = new Date("2026-08-01T23:30:00Z");
  const previousTZ = process.env.TZ;
  try {
    process.env.TZ = "Etc/GMT-1"; // POSIX sign is inverted: this is UTC+1.
    expect(localIsoDate(instant)).toBe("2026-08-02");

    process.env.TZ = "Etc/GMT+5"; // POSIX sign inverted: this is UTC-5.
    expect(localIsoDate(instant)).toBe("2026-08-01");
  } finally {
    process.env.TZ = previousTZ;
  }
});
