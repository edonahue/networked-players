// Unit specs for the local progression store: versioned localStorage shape,
// migration behavior, corrupt-input resilience, and streak accounting.
// Storage is injected as a plain object — no browser needed.

import { expect, test } from "@playwright/test";
import {
  STORAGE_KEY,
  emptyStore,
  load,
  migrate,
  recordDaily,
  recordRound,
  save,
  type StorageLike,
} from "../src/game/store";

function fakeStorage(): StorageLike & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return {
    data,
    getItem: (key) => data.get(key) ?? null,
    setItem: (key, value) => {
      data.set(key, value);
    },
  };
}

test("round-trips through storage under the versioned key", () => {
  const storage = fakeStorage();
  let store = load(storage);
  expect(store).toEqual(emptyStore());
  store = recordRound(store, "syn-1h-0102", "clean");
  save(storage, store);
  expect(storage.data.has(STORAGE_KEY)).toBe(true);
  const reloaded = load(storage);
  expect(reloaded.totals).toEqual({
    played: 1,
    solved: 1,
    clean: 1,
    revealed: 0,
  });
  expect(reloaded.seenRounds).toEqual(["syn-1h-0102"]);
});

test("migrates the v0 experimental shape and rejects garbage", () => {
  const migrated = migrate({ plays: 7 });
  expect(migrated.version).toBe(2);
  expect(migrated.totals.played).toBe(7);
  expect(migrate("not an object")).toEqual(emptyStore());
  expect(migrate(null)).toEqual(emptyStore());
  expect(migrate({ version: 99, junk: true })).toEqual(emptyStore());
});

test("corrupt stored JSON falls back to a fresh store", () => {
  const storage = fakeStorage();
  storage.setItem(STORAGE_KEY, "{not json");
  expect(load(storage)).toEqual(emptyStore());
});

test("missing storage disables stats without breaking play", () => {
  expect(load(null)).toEqual(emptyStore());
  save(null, emptyStore()); // must not throw
});

test("seen rounds dedupe and revealed rounds count as unsolved", () => {
  let store = emptyStore();
  store = recordRound(store, "r1", "revealed");
  store = recordRound(store, "r1", "with_clues");
  expect(store.seenRounds).toEqual(["r1"]);
  expect(store.totals).toEqual({ played: 2, solved: 1, clean: 0, revealed: 1 });
});

test("daily streak counts consecutive solved days and resets on a miss", () => {
  let store = emptyStore();
  store = recordDaily(store, "2026-07-16", "clean", "●");
  expect(store.streak).toEqual({
    current: 1,
    best: 1,
    lastDailyDate: "2026-07-16",
  });
  store = recordDaily(store, "2026-07-17", "with_clues", "◐");
  expect(store.streak.current).toBe(2);
  expect(store.streak.best).toBe(2);
  // Miss a day: solving the 19th after the 17th restarts at 1.
  store = recordDaily(store, "2026-07-19", "clean", "●");
  expect(store.streak.current).toBe(1);
  expect(store.streak.best).toBe(2);
  // Failing a daily zeroes the current streak.
  store = recordDaily(store, "2026-07-20", "revealed", "○");
  expect(store.streak.current).toBe(0);
  expect(store.streak.best).toBe(2);
  expect(Object.keys(store.daily)).toEqual([
    "2026-07-16",
    "2026-07-17",
    "2026-07-19",
    "2026-07-20",
  ]);
});

test("recordDaily stores the rating alongside the share string", () => {
  let store = emptyStore();
  store = recordDaily(store, "2026-07-16", "clean", "●");
  expect(store.daily["2026-07-16"]).toEqual({
    shareString: "●",
    rating: "clean",
  });
});

test("migrates a v1 store (bare share strings) to v2, conservatively rating every historical entry as revealed", () => {
  const migrated = migrate({
    version: 1,
    totals: { played: 3, solved: 2, clean: 1, revealed: 1 },
    streak: { current: 2, best: 4, lastDailyDate: "2026-01-05" },
    seenRounds: ["conn-old-example"],
    daily: {
      "2026-01-04": "old share text",
      "2026-01-05": "old share text 2",
    },
  });
  expect(migrated.version).toBe(2);
  expect(migrated.totals.played).toBe(3);
  expect(migrated.streak.best).toBe(4);
  expect(migrated.daily).toEqual({
    "2026-01-04": { shareString: "old share text", rating: "revealed" },
    "2026-01-05": { shareString: "old share text 2", rating: "revealed" },
  });
});

test("v2 migration discards a malformed daily entry rather than throwing", () => {
  const migrated = migrate({
    version: 2,
    daily: {
      "2026-01-04": { shareString: "ok", rating: "clean" },
      "2026-01-05": { shareString: "bad rating" },
      "2026-01-06": "not even an object",
    },
  });
  expect(migrated.daily).toEqual({
    "2026-01-04": { shareString: "ok", rating: "clean" },
  });
});
