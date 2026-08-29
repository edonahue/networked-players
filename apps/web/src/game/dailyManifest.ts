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
/** Schema v2 adds `generations[]` and a per-entry `generation` tag so one
 * manifest can span MULTIPLE pool generations (ADR 0066). v1 remains fully
 * supported: this build reads either, so the manifest can be upgraded
 * independently of a deploy and rolled back without stranding visitors. */
export const SUPPORTED_MANIFEST_SCHEMA_VERSION_V2 = 2;

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

/** One frozen pool generation: the exact artifact triple its dates resolve
 * against, plus where that generation's rounds live. gen-1's rounds are a
 * byte-identical frozen copy at its own URL; the newest generation's
 * `rounds_url` is the live rounds artifact. */
export interface DailyManifestGeneration {
  generation_id: string;
  catalog_version: string;
  pool_version: string;
  artifact_version: string;
  rounds_url: string;
}

export interface DailyManifestEntryV2 extends DailyManifestEntry {
  generation: string;
}

export interface DailyManifestV2 {
  schema_version: number;
  mode: string;
  generated_at: string;
  start_date: string;
  generations: DailyManifestGeneration[];
  schedule: DailyManifestEntryV2[];
}

/** Either supported shape. Both carry `schedule` and `start_date`, which is
 * all the archive calendar reads. */
export type AnyDailyManifest = DailyManifest | DailyManifestV2;

export async function fetchDailyManifest(): Promise<AnyDailyManifest> {
  const response = await fetch("/data/game/daily-manifest.v1.json");
  if (!response.ok) {
    throw new Error(
      `failed to load daily-manifest.v1.json: ${response.status}`,
    );
  }
  return (await response.json()) as AnyDailyManifest;
}

/** Fetch one generation's own rounds artifact. Only used on the schema-v2
 * path, and only when the already-loaded artifact isn't the one this date's
 * generation resolves against (an archive date from a retired generation) --
 * a today-date on the newest generation needs no extra request. */
export async function fetchRoundsArtifact(url: string): Promise<unknown> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`failed to load ${url}: ${response.status}`);
  }
  return await response.json();
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

/** Same runtime-shape discipline as `isDailyManifest`, for the v2 shape:
 * `generations[]` replaces the top-level version triple, and every schedule
 * entry carries the `generation` it resolves against. */
export function isDailyManifestV2(value: unknown): value is DailyManifestV2 {
  if (!isRecord(value)) return false;
  if (value.schema_version !== SUPPORTED_MANIFEST_SCHEMA_VERSION_V2) {
    return false;
  }
  if (typeof value.mode !== "string") return false;
  if (!Array.isArray(value.generations) || value.generations.length === 0) {
    return false;
  }
  return Array.isArray(value.schedule);
}

function isGeneration(value: unknown): value is DailyManifestGeneration {
  return (
    isRecord(value) &&
    isNonEmptyString(value.generation_id) &&
    isNonEmptyString(value.catalog_version) &&
    isNonEmptyString(value.pool_version) &&
    isNonEmptyString(value.artifact_version) &&
    isNonEmptyString(value.rounds_url)
  );
}

/** A schedule entry is only usable if every field the resolver reads is a
 * present, non-empty string. A malformed member (null, a primitive, or one
 * missing `round_id`/`round_fingerprint`) is treated as "no entry for this
 * date" rather than dereferenced -- the browser never throws on bad fetched
 * JSON, it returns a typed failure. */
function isScheduleEntry(value: unknown): value is DailyManifestEntry {
  return (
    isRecord(value) &&
    isNonEmptyString(value.date) &&
    isNonEmptyString(value.round_id) &&
    isNonEmptyString(value.round_fingerprint)
  );
}

function isScheduleEntryV2(value: unknown): value is DailyManifestEntryV2 {
  return (
    isRecord(value) &&
    isScheduleEntry(value) &&
    isNonEmptyString(value.generation)
  );
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
  | { ok: false; reason: "fingerprint-mismatch" }
  // v2-only: the entry names a generation absent from `generations[]`, so
  // there is no artifact triple to verify it against.
  | { ok: false; reason: "unknown-generation" }
  // v2-only: that generation's own rounds artifact could not be fetched or
  // was malformed. Deliberately distinct from `missing-round` (pool loaded,
  // round absent) so the two are independently testable.
  | { ok: false; reason: "generation-rounds-unavailable" };

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
  fetchRounds: (url: string) => Promise<unknown> = fetchRoundsArtifact,
): Promise<DailyResolution> {
  // Schema v2 (multi-generation, ADR 0066) is handled by its own path: the
  // artifact triple to verify against lives per-generation rather than at
  // the top level, and which rounds artifact is even correct depends on
  // which generation THIS date belongs to.
  if (isDailyManifestV2(manifest)) {
    return resolveDailyRoundV2(manifest, roundsArtifact, isoDate, fetchRounds);
  }
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
    (e) => isScheduleEntry(e) && e.date === isoDate,
  );
  if (!entry || !isScheduleEntry(entry)) {
    return { ok: false, reason: "not-scheduled" };
  }

  // Guard each member before dereferencing `.id` -- a `null` or primitive in
  // the fetched `rounds` array must not throw, it must resolve to a typed
  // integrity failure.
  const round = roundsArtifact.rounds.find(
    (r) => isRecord(r) && typeof r.id === "string" && r.id === entry.round_id,
  );
  if (!round) return { ok: false, reason: "missing-round" };
  if (!isEligibleRound(round)) return { ok: false, reason: "ineligible-round" };

  const fingerprint = await roundContentFingerprint(round);
  if (fingerprint !== entry.round_fingerprint) {
    return { ok: false, reason: "fingerprint-mismatch" };
  }
  return { ok: true, round };
}

/** Schema-v2 resolution (ADR 0066). Same seven integrity checks as v1, but
 * every version comparison is against THIS DATE'S OWN generation rather
 * than a single top-level triple:
 *
 * - the entry names a `generation`, which must exist in `generations[]`
 *   (`unknown-generation`);
 * - that generation's `catalog_version`/`pool_version`/`artifact_version`
 *   must match the rounds artifact actually used (`version-mismatch`) --
 *   the v1 single-generation rule, applied per generation;
 * - the rounds artifact used is the one already loaded when its provenance
 *   matches this generation (the common case: a current date on the newest
 *   generation, no extra request), otherwise this generation's frozen
 *   `rounds_url` is fetched (`generation-rounds-unavailable` if that fails
 *   or is malformed).
 *
 * A date from a retired generation therefore keeps resolving to its exact
 * original round forever, which is the entire point of the multi-generation
 * manifest -- an already-played, already-shared date must never break
 * because the pool was later regenerated. */
async function resolveDailyRoundV2(
  manifest: DailyManifestV2,
  loadedRoundsArtifact: unknown,
  isoDate: string,
  fetchRounds: (url: string) => Promise<unknown>,
): Promise<DailyResolution> {
  if (manifest.mode !== CONNECTION_DAILY_MANIFEST_MODE) {
    return { ok: false, reason: "wrong-mode" };
  }

  const entry = manifest.schedule.find(
    (e) => isScheduleEntryV2(e) && e.date === isoDate,
  );
  if (!entry || !isScheduleEntryV2(entry)) {
    return { ok: false, reason: "not-scheduled" };
  }

  const generation = manifest.generations.find(
    (g) => isGeneration(g) && g.generation_id === entry.generation,
  );
  if (!generation || !isGeneration(generation)) {
    return { ok: false, reason: "unknown-generation" };
  }

  // Prefer the artifact already in hand when it IS this generation's -- a
  // today-date on the newest generation must not pay for a second fetch.
  let artifact: unknown = loadedRoundsArtifact;
  const alreadyLoadedMatches =
    isGameRoundsArtifact(artifact) &&
    artifact.provenance.catalog_version === generation.catalog_version &&
    artifact.provenance.pool_version === generation.pool_version &&
    artifact.provenance.artifact_version === generation.artifact_version;

  if (!alreadyLoadedMatches) {
    try {
      artifact = await fetchRounds(generation.rounds_url);
    } catch {
      return { ok: false, reason: "generation-rounds-unavailable" };
    }
  }

  if (
    !isGameRoundsArtifact(artifact) ||
    artifact.schema_version !== SUPPORTED_ROUNDS_SCHEMA_VERSION
  ) {
    return { ok: false, reason: "generation-rounds-unavailable" };
  }

  // Verify the triple even on the freshly-fetched path: a generation whose
  // rounds_url serves the wrong pool must fail closed, not deal a round
  // from a pool this date was never frozen against.
  const provenance = artifact.provenance;
  if (
    provenance.catalog_version !== generation.catalog_version ||
    provenance.pool_version !== generation.pool_version ||
    provenance.artifact_version !== generation.artifact_version
  ) {
    return { ok: false, reason: "version-mismatch" };
  }

  const round = artifact.rounds.find(
    (r) => isRecord(r) && typeof r.id === "string" && r.id === entry.round_id,
  );
  if (!round) return { ok: false, reason: "missing-round" };
  if (!isEligibleRound(round)) return { ok: false, reason: "ineligible-round" };

  const fingerprint = await roundContentFingerprint(round);
  if (fingerprint !== entry.round_fingerprint) {
    return { ok: false, reason: "fingerprint-mismatch" };
  }
  return { ok: true, round };
}
