// Connection of the Day: frozen, append-only date -> round resolution
// (docs/WEB_PRODUCT_PLAN.md §5, ADR 0043's corrective-slice-4.6 and -5.1
// addenda). Replaces the old date-seeded shuffle (`dailySeed`/`createRng`)
// entirely -- a published date must always resolve to the same round,
// verifiably, or fail gracefully. Never falls back to hashing a date when
// the manifest doesn't cover it.
//
// Verifies the COMPLETE artifact pairing before dealing a round: both
// schema versions, the manifest's mode, and all three of
// catalog_version/pool_version/artifact_version agreeing between the
// manifest and the fetched rounds artifact's own provenance -- not just the
// per-round fingerprint. A manifest built against one generation of the
// rounds pool must never be silently paired with a different generation
// (corrective slice 5.1's single-artifact-version rule, mirrored here from
// `connection_daily_manifest.py::_version_mismatches`). Nothing here trusts
// a TypeScript type assertion as runtime proof -- every field this module
// depends on is checked with a runtime guard before use, since both fetched
// JSON files are untrusted input.

import { roundContentFingerprint } from "./canonical";
import type { GameRound, GameRounds } from "./types";

export const CONNECTION_DAILY_MANIFEST_MODE = "connection_guesser_one_hop";
export const SUPPORTED_ROUNDS_SCHEMA_VERSION = 1;
export const SUPPORTED_MANIFEST_SCHEMA_VERSION = 1;

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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

/** Runtime guard for exactly the fields daily resolution depends on -- not
 * a full contract validation (that's the Python validators' job), but
 * enough to refuse to reason about a malformed or unexpectedly-shaped
 * fetch response rather than throwing deep inside resolution logic. */
export function isGameRoundsArtifact(value: unknown): value is GameRounds {
  if (!isRecord(value)) return false;
  if (typeof value.schema_version !== "number") return false;
  if (!isRecord(value.provenance)) return false;
  const provenance = value.provenance;
  if (
    !isNonEmptyString(provenance.catalog_version) ||
    !isNonEmptyString(provenance.pool_version) ||
    !isNonEmptyString(provenance.artifact_version)
  ) {
    return false;
  }
  return Array.isArray(value.rounds);
}

export function isDailyManifest(value: unknown): value is DailyManifest {
  if (!isRecord(value)) return false;
  if (typeof value.schema_version !== "number") return false;
  if (typeof value.mode !== "string") return false;
  if (
    !isNonEmptyString(value.catalog_version) ||
    !isNonEmptyString(value.pool_version) ||
    !isNonEmptyString(value.artifact_version)
  ) {
    return false;
  }
  return Array.isArray(value.schedule);
}

function isEligibleRound(
  round: unknown,
): round is GameRound & { pool: "real-records"; kind: "one_hop" } {
  return (
    isRecord(round) && round.pool === "real-records" && round.kind === "one_hop"
  );
}

export type DailyResolution =
  | { ok: true; round: GameRound }
  | { ok: false; reason: "unsupported-manifest" }
  | { ok: false; reason: "wrong-mode" }
  | { ok: false; reason: "version-mismatch" }
  | { ok: false; reason: "not-scheduled" }
  | { ok: false; reason: "missing-round" }
  | { ok: false; reason: "ineligible-round" }
  | { ok: false; reason: "fingerprint-mismatch" };

/** Resolve a calendar date to its frozen round. Every check below is a
 * distinct, independently testable failure mode -- the UI may collapse
 * several into one user-facing integrity message, but this function never
 * does, so tests can tell them apart:
 *
 * 1. Both artifacts must be well-formed and at a schema version this build
 *    understands (`unsupported-manifest` -- covers either fetch being
 *    malformed or at an unrecognized schema_version).
 * 2. `manifest.mode` must be exactly `connection_guesser_one_hop`
 *    (`wrong-mode`) -- never silently accept a Record Routes or other
 *    manifest shape that happens to parse.
 * 3. `catalog_version`/`pool_version`/`artifact_version` must agree
 *    EXACTLY between the manifest and the rounds artifact's own
 *    provenance (`version-mismatch`) -- mirrors
 *    `connection_daily_manifest.py::_version_mismatches`'s schema-v1
 *    single-generation rule.
 * 4. The date must have a scheduled entry (`not-scheduled`).
 * 5. The entry's round must exist in the fetched pool (`missing-round`).
 * 6. That round must actually be real-records/one_hop (`ineligible-round`)
 *    -- catches a manifest somehow pointing at a two-hop or synthetic
 *    round, which must never be dealt as a daily.
 * 7. The round's CURRENT published content must still match what the
 *    manifest expects (`round_content_fingerprint`, recomputed
 *    client-side) (`fingerprint-mismatch`) -- catches a round that
 *    silently changed underneath an already-shared date.
 *
 * Never derives an assignment for a date the manifest doesn't cover, and
 * never falls back to any other selection strategy on failure. */
export async function resolveDailyRound(
  manifest: unknown,
  roundsArtifact: unknown,
  isoDate: string,
): Promise<DailyResolution> {
  if (
    !isGameRoundsArtifact(roundsArtifact) ||
    roundsArtifact.schema_version !== SUPPORTED_ROUNDS_SCHEMA_VERSION ||
    !isDailyManifest(manifest) ||
    manifest.schema_version !== SUPPORTED_MANIFEST_SCHEMA_VERSION
  ) {
    return { ok: false, reason: "unsupported-manifest" };
  }
  if (manifest.mode !== CONNECTION_DAILY_MANIFEST_MODE) {
    return { ok: false, reason: "wrong-mode" };
  }
  const provenance = roundsArtifact.provenance;
  if (
    manifest.catalog_version !== provenance.catalog_version ||
    manifest.pool_version !== provenance.pool_version ||
    manifest.artifact_version !== provenance.artifact_version
  ) {
    return { ok: false, reason: "version-mismatch" };
  }

  const entry = manifest.schedule.find(
    (e) => isRecord(e) && e.date === isoDate,
  );
  if (!entry) return { ok: false, reason: "not-scheduled" };

  const round = roundsArtifact.rounds.find((r) => r.id === entry.round_id);
  if (!round) return { ok: false, reason: "missing-round" };
  if (!isEligibleRound(round)) return { ok: false, reason: "ineligible-round" };

  const fingerprint = await roundContentFingerprint(round);
  if (fingerprint !== entry.round_fingerprint) {
    return { ok: false, reason: "fingerprint-mismatch" };
  }
  return { ok: true, round };
}
