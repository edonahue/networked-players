// Local-only progression store (docs/WEB_PRODUCT_PLAN.md §5): one versioned
// localStorage key, written only after a round resolves. Storage is injected
// so tests use a plain object and play degrades silently when storage is
// unavailable. No accounts, no network.

import type { Rating } from "./types";

export const STORAGE_KEY = "np.game.v1";
export const STORE_VERSION = 1;

export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export interface GameStore {
  version: number;
  totals: {
    played: number;
    solved: number;
    clean: number;
    revealed: number;
  };
  streak: {
    current: number;
    best: number;
    lastDailyDate: string | null;
  };
  seenRounds: string[];
  daily: Record<string, string>;
}

export function emptyStore(): GameStore {
  return {
    version: STORE_VERSION,
    totals: { played: 0, solved: 0, clean: 0, revealed: 0 },
    streak: { current: 0, best: 0, lastDailyDate: null },
    seenRounds: [],
    daily: {},
  };
}

/**
 * Migrate any previously stored shape to the current version. Unknown or
 * corrupt input falls back to a fresh store rather than throwing — losing
 * local stats is preferable to breaking play.
 */
export function migrate(raw: unknown): GameStore {
  if (typeof raw !== "object" || raw === null) return emptyStore();
  const candidate = raw as Partial<GameStore> & { version?: number };
  if (candidate.version === STORE_VERSION) {
    const base = emptyStore();
    return {
      version: STORE_VERSION,
      totals: { ...base.totals, ...(candidate.totals ?? {}) },
      streak: { ...base.streak, ...(candidate.streak ?? {}) },
      seenRounds: Array.isArray(candidate.seenRounds)
        ? candidate.seenRounds.filter((id) => typeof id === "string")
        : [],
      daily:
        typeof candidate.daily === "object" && candidate.daily !== null
          ? Object.fromEntries(
              Object.entries(candidate.daily).filter(
                ([, value]) => typeof value === "string",
              ),
            )
          : {},
    };
  }
  // Version 0 (pre-release experiments) stored only { plays: number }.
  if (typeof (raw as { plays?: unknown }).plays === "number") {
    const store = emptyStore();
    store.totals.played = (raw as { plays: number }).plays;
    return store;
  }
  return emptyStore();
}

export function load(storage: StorageLike | null): GameStore {
  if (!storage) return emptyStore();
  try {
    const raw = storage.getItem(STORAGE_KEY);
    if (raw === null) return emptyStore();
    return migrate(JSON.parse(raw));
  } catch {
    return emptyStore();
  }
}

export function save(storage: StorageLike | null, store: GameStore): void {
  if (!storage) return;
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify(store));
  } catch {
    // Storage full or blocked: stats are best-effort by design.
  }
}

const MAX_SEEN_ROUNDS = 400;

export function recordRound(
  store: GameStore,
  roundId: string,
  rating: Rating,
): GameStore {
  const next: GameStore = {
    ...store,
    totals: { ...store.totals },
    streak: { ...store.streak },
    seenRounds: store.seenRounds.includes(roundId)
      ? store.seenRounds
      : [...store.seenRounds, roundId].slice(-MAX_SEEN_ROUNDS),
    daily: { ...store.daily },
  };
  next.totals.played += 1;
  if (rating === "revealed") next.totals.revealed += 1;
  else next.totals.solved += 1;
  if (rating === "clean") next.totals.clean += 1;
  return next;
}

// --- Set state (docs/WEB_PRODUCT_PLAN.md §5: quick rounds in ~5-round sets).
// One sitting = one set. Session-scoped by convention (the caller passes
// sessionStorage), same injected-StorageLike pattern as the main store.

export const SET_KEY = "np.set.v1";
export const SET_VERSION = 1;
export const SET_SIZE = 5;

export interface SetEntry {
  roundId: string;
  rating: Rating;
}

export interface SetState {
  version: number;
  kind: string;
  seed: string;
  entries: SetEntry[];
}

export function freshSet(kind: string, seed: string): SetState {
  return { version: SET_VERSION, kind, seed, entries: [] };
}

const RATINGS: readonly string[] = ["clean", "with_clues", "revealed"];

/**
 * Load the in-progress set for a kind. Anything unusable — missing, corrupt,
 * version or kind mismatch, or already complete — yields a fresh set seeded
 * with `seed`, so a new sitting simply begins.
 */
export function loadSet(
  storage: StorageLike | null,
  kind: string,
  seed: string,
): SetState {
  if (!storage) return freshSet(kind, seed);
  try {
    const raw = storage.getItem(SET_KEY);
    if (raw === null) return freshSet(kind, seed);
    const parsed = JSON.parse(raw) as Partial<SetState>;
    if (
      parsed.version !== SET_VERSION ||
      parsed.kind !== kind ||
      typeof parsed.seed !== "string" ||
      !Array.isArray(parsed.entries) ||
      parsed.entries.length >= SET_SIZE ||
      !parsed.entries.every(
        (e) =>
          typeof e === "object" &&
          e !== null &&
          typeof e.roundId === "string" &&
          RATINGS.includes(e.rating),
      )
    ) {
      return freshSet(kind, seed);
    }
    return parsed as SetState;
  } catch {
    return freshSet(kind, seed);
  }
}

export function saveSet(storage: StorageLike | null, set: SetState): void {
  if (!storage) return;
  try {
    storage.setItem(SET_KEY, JSON.stringify(set));
  } catch {
    // Best-effort, like the main store.
  }
}

export function recordSetRound(
  set: SetState,
  roundId: string,
  rating: Rating,
): SetState {
  return { ...set, entries: [...set.entries, { roundId, rating }] };
}

export function setComplete(set: SetState): boolean {
  return set.entries.length >= SET_SIZE;
}

/** Record a daily result; streak counts consecutive solved daily dates. */
export function recordDaily(
  store: GameStore,
  isoDate: string,
  rating: Rating,
  shareString: string,
): GameStore {
  const next = recordRound(store, `daily-${isoDate}`, rating);
  next.daily[isoDate] = shareString;
  const solved = rating !== "revealed";
  const previous = next.streak.lastDailyDate;
  if (solved) {
    const yesterday = new Date(`${isoDate}T00:00:00Z`);
    yesterday.setUTCDate(yesterday.getUTCDate() - 1);
    const consecutive = previous === yesterday.toISOString().slice(0, 10);
    next.streak.current = consecutive ? next.streak.current + 1 : 1;
    next.streak.best = Math.max(next.streak.best, next.streak.current);
  } else {
    next.streak.current = 0;
  }
  next.streak.lastDailyDate = isoDate;
  return next;
}
