// Connection of the Day: frozen, append-only date -> round resolution
// (docs/WEB_PRODUCT_PLAN.md §5, ADR 0043's corrective-slice-4.6 addendum).
// Replaces the old date-seeded shuffle (`dailySeed`/`createRng`) entirely --
// a published date must always resolve to the same round, verifiably, or
// fail gracefully. Never falls back to hashing a date when the manifest
// doesn't cover it.

import { roundContentFingerprint } from "./canonical";
import type { GameRound } from "./types";

export interface DailyManifestEntry {
  date: string;
  round_id: string;
  round_fingerprint: string;
}

export interface DailyManifest {
  schema_version: number;
  mode: string;
  catalog_version: string;
  pool_version: string;
  artifact_version: string;
  generated_at: string;
  start_date: string;
  schedule: DailyManifestEntry[];
}

export async function fetchDailyManifest(): Promise<DailyManifest> {
  const response = await fetch("/data/game/daily-manifest.v1.json");
  if (!response.ok) {
    throw new Error(
      `failed to load daily-manifest.v1.json: ${response.status}`,
    );
  }
  return (await response.json()) as DailyManifest;
}

export type DailyResolution =
  | { ok: true; round: GameRound }
  | { ok: false; reason: "not-scheduled" }
  | { ok: false; reason: "missing-round"; roundId: string }
  | { ok: false; reason: "fingerprint-mismatch"; roundId: string };

/** Resolve a calendar date to its frozen round via the manifest, then
 * verify the round's CURRENT published content still matches what the
 * manifest expects (`round_content_fingerprint`, recomputed client-side) --
 * catches a round that silently changed underneath an already-shared date,
 * rather than quietly serving different content for the same URL. Never
 * derives an assignment for a date the manifest doesn't cover. */
export async function resolveDailyRound(
  manifest: DailyManifest,
  rounds: GameRound[],
  isoDate: string,
): Promise<DailyResolution> {
  const entry = manifest.schedule.find((e) => e.date === isoDate);
  if (!entry) return { ok: false, reason: "not-scheduled" };
  const round = rounds.find((r) => r.id === entry.round_id);
  if (!round)
    return { ok: false, reason: "missing-round", roundId: entry.round_id };
  const fingerprint = await roundContentFingerprint(round);
  if (fingerprint !== entry.round_fingerprint) {
    return {
      ok: false,
      reason: "fingerprint-mismatch",
      roundId: entry.round_id,
    };
  }
  return { ok: true, round };
}
