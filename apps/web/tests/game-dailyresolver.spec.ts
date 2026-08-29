// Unit specs for dailyManifest.ts's resolveDailyRound -- pure-node tests in
// the Playwright runner (same pattern as game-canonical.spec.ts: no
// browser, no server). Corrective slice 5.1: proves every distinct failure
// reason is reachable and distinguishable at the resolver level, not just
// bundled into one UI message (game-daily.spec.ts covers the browser-level
// graceful rendering of a representative subset of these).

import { expect, test } from "@playwright/test";
import { resolveDailyRound } from "../src/game/dailyManifest";
import type { GameRound, GameRounds } from "../src/game/types";

const PROVENANCE = {
  source: "Discogs monthly data dump (CC0), one-hop working set",
  license: "See docs/DATA_AND_RIGHTS.md.",
  note: "Real records, not synthetic.",
  generated_by: "test",
  snapshot_date: "20260601",
  catalog_version: "catalog-v1-20260601-abc",
  pool_version: "connection-v1-20260601-def",
  artifact_version: "connection-artifact-v1-20260601-ghi",
};

function round(overrides: Partial<GameRound> = {}): GameRound {
  return {
    id: "conn-0000000001",
    pool: "real-records",
    kind: "one_hop",
    difficulty: "hard",
    endpoints: [
      {
        id: "album-a",
        title: "First Light",
        year: 1990,
        act: "Alice",
        label: null,
        art: null,
      },
      {
        id: "album-c",
        title: "Third Wave",
        year: 1995,
        act: "Cara",
        label: null,
        art: null,
      },
    ],
    answer_set: [{ id: 700, name: "Xavier", role_category: "guitar" }],
    distractors: [],
    clues: [],
    evidence: [
      {
        release_ref: "album-a",
        release_title: "First Light",
        contributor_id: 700,
        credited_as: "Xavier",
        role_text: "Guitar",
        credit_scope: "release_credit",
      },
    ],
    provenance_note: "test",
    ...overrides,
  };
}

function roundsArtifact(rounds: GameRound[]): GameRounds {
  return { schema_version: 1, provenance: PROVENANCE, rounds };
}

async function manifestFor(rounds: GameRound[]) {
  const { roundContentFingerprint } = await import("../src/game/canonical");
  return {
    schema_version: 1,
    mode: "connection_guesser_one_hop",
    catalog_version: PROVENANCE.catalog_version,
    pool_version: PROVENANCE.pool_version,
    artifact_version: PROVENANCE.artifact_version,
    generated_at: "2026-07-22T00:00:00+00:00",
    start_date: "2026-08-01",
    schedule: await Promise.all(
      rounds.map(async (r, i) => ({
        date: `2026-08-0${i + 1}`,
        round_id: r.id,
        round_fingerprint: await roundContentFingerprint(r),
      })),
    ),
  };
}

test("resolves a valid scheduled date to its round", async () => {
  const r = round();
  const manifest = await manifestFor([r]);
  const resolution = await resolveDailyRound(
    manifest,
    roundsArtifact([r]),
    "2026-08-01",
  );
  expect(resolution.ok).toBe(true);
  if (resolution.ok) expect(resolution.round.id).toBe(r.id);
});

test("unsupported-manifest: malformed rounds artifact", async () => {
  const r = round();
  const manifest = await manifestFor([r]);
  const resolution = await resolveDailyRound(
    manifest,
    { not: "valid" },
    "2026-08-01",
  );
  expect(resolution).toEqual({ ok: false, reason: "unsupported-manifest" });
});

test("unsupported-manifest: unrecognized rounds schema_version", async () => {
  const r = round();
  const manifest = await manifestFor([r]);
  const artifact = { ...roundsArtifact([r]), schema_version: 99 };
  const resolution = await resolveDailyRound(manifest, artifact, "2026-08-01");
  expect(resolution).toEqual({ ok: false, reason: "unsupported-manifest" });
});

test("unsupported-manifest: malformed manifest", async () => {
  const r = round();
  const resolution = await resolveDailyRound(
    { not: "valid" },
    roundsArtifact([r]),
    "2026-08-01",
  );
  expect(resolution).toEqual({ ok: false, reason: "unsupported-manifest" });
});

test("unsupported-manifest: unrecognized manifest schema_version", async () => {
  const r = round();
  const manifest = await manifestFor([r]);
  const resolution = await resolveDailyRound(
    { ...manifest, schema_version: 99 },
    roundsArtifact([r]),
    "2026-08-01",
  );
  expect(resolution).toEqual({ ok: false, reason: "unsupported-manifest" });
});

test("wrong-mode: manifest mode is not connection_guesser_one_hop", async () => {
  const r = round();
  const manifest = await manifestFor([r]);
  const resolution = await resolveDailyRound(
    { ...manifest, mode: "record_routes" },
    roundsArtifact([r]),
    "2026-08-01",
  );
  expect(resolution).toEqual({ ok: false, reason: "wrong-mode" });
});

test("version-mismatch: catalog_version disagrees", async () => {
  const r = round();
  const manifest = await manifestFor([r]);
  const resolution = await resolveDailyRound(
    { ...manifest, catalog_version: "catalog-v1-20260601-different" },
    roundsArtifact([r]),
    "2026-08-01",
  );
  expect(resolution).toEqual({ ok: false, reason: "version-mismatch" });
});

test("version-mismatch: pool_version disagrees", async () => {
  const r = round();
  const manifest = await manifestFor([r]);
  const resolution = await resolveDailyRound(
    { ...manifest, pool_version: "connection-v1-20260601-different" },
    roundsArtifact([r]),
    "2026-08-01",
  );
  expect(resolution).toEqual({ ok: false, reason: "version-mismatch" });
});

test("version-mismatch: artifact_version disagrees", async () => {
  const r = round();
  const manifest = await manifestFor([r]);
  const resolution = await resolveDailyRound(
    {
      ...manifest,
      artifact_version: "connection-artifact-v1-20260601-different",
    },
    roundsArtifact([r]),
    "2026-08-01",
  );
  expect(resolution).toEqual({ ok: false, reason: "version-mismatch" });
});

test("not-scheduled: date has no schedule entry", async () => {
  const r = round();
  const manifest = await manifestFor([r]);
  const resolution = await resolveDailyRound(
    manifest,
    roundsArtifact([r]),
    "2020-01-01",
  );
  expect(resolution).toEqual({ ok: false, reason: "not-scheduled" });
});

test("missing-round: scheduled round id is not in the pool", async () => {
  const r = round();
  const manifest = await manifestFor([r]);
  const resolution = await resolveDailyRound(
    manifest,
    roundsArtifact([]),
    "2026-08-01",
  );
  expect(resolution).toEqual({ ok: false, reason: "missing-round" });
});

test("ineligible-round: manifest points at a two-hop round", async () => {
  const twoHop = round({
    id: "conn-000000000a",
    kind: "two_hop",
    answer_set: [],
    bridge_answer_sets: [[], []],
    middle: {
      album: {
        id: "album-m",
        title: "Middle",
        year: 1992,
        act: "Middle Act",
        label: null,
        art: null,
      },
      choices: [],
    },
  });
  const manifest = await manifestFor([twoHop]);
  const resolution = await resolveDailyRound(
    manifest,
    roundsArtifact([twoHop]),
    "2026-08-01",
  );
  expect(resolution).toEqual({ ok: false, reason: "ineligible-round" });
});

test("ineligible-round: manifest points at a synthetic round", async () => {
  const synthetic = round({
    id: "conn-000000000b",
    pool: "synthetic-universe",
  });
  const manifest = await manifestFor([synthetic]);
  const resolution = await resolveDailyRound(
    manifest,
    roundsArtifact([synthetic]),
    "2026-08-01",
  );
  expect(resolution).toEqual({ ok: false, reason: "ineligible-round" });
});

test("fingerprint-mismatch: round content changed underneath the entry", async () => {
  const r = round();
  const manifest = await manifestFor([r]);
  const tampered = {
    ...r,
    distractors: [{ id: 1, name: "New", role_category: "guitar" }],
  };
  const resolution = await resolveDailyRound(
    manifest,
    roundsArtifact([tampered]),
    "2026-08-01",
  );
  expect(resolution).toEqual({ ok: false, reason: "fingerprint-mismatch" });
});

// --- Malformed-fetch guards (ADR 0044 pre-merge patch): a malformed fetched
// artifact must always return a typed integrity failure, never throw. Each
// test uses a real scheduled entry but corrupts the rounds/schedule shape the
// resolver dereferences.

test("malformed rounds: a null member never throws", async () => {
  const r = round();
  const manifest = await manifestFor([r]);
  // `rounds: [null]` still contains an entry matching the scheduled id at
  // index 0 only if it isn't null -- here the only member is null, so no id
  // matches and the guard must skip it rather than read `.id` off null.
  const artifact = {
    schema_version: 1,
    provenance: PROVENANCE,
    rounds: [null],
  };
  const resolution = await resolveDailyRound(manifest, artifact, "2026-08-01");
  expect(resolution).toEqual({ ok: false, reason: "missing-round" });
});

test("malformed rounds: a primitive member never throws", async () => {
  const r = round();
  const manifest = await manifestFor([r]);
  const artifact = { schema_version: 1, provenance: PROVENANCE, rounds: [42] };
  const resolution = await resolveDailyRound(manifest, artifact, "2026-08-01");
  expect(resolution).toEqual({ ok: false, reason: "missing-round" });
});

test("malformed schedule: an entry missing round_id is not scheduled", async () => {
  const r = round();
  const manifest = await manifestFor([r]);
  // Drop round_id from the matching entry -- it must be rejected as an
  // unusable entry, not dereferenced.
  const entry = manifest.schedule[0] as Record<string, unknown>;
  delete entry.round_id;
  const resolution = await resolveDailyRound(
    manifest,
    roundsArtifact([r]),
    "2026-08-01",
  );
  expect(resolution).toEqual({ ok: false, reason: "not-scheduled" });
});

test("malformed schedule: an entry missing round_fingerprint is not scheduled", async () => {
  const r = round();
  const manifest = await manifestFor([r]);
  const entry = manifest.schedule[0] as Record<string, unknown>;
  delete entry.round_fingerprint;
  const resolution = await resolveDailyRound(
    manifest,
    roundsArtifact([r]),
    "2026-08-01",
  );
  expect(resolution).toEqual({ ok: false, reason: "not-scheduled" });
});

test("malformed schedule: a null/primitive entry is skipped, not dereferenced", async () => {
  const r = round();
  const manifest = await manifestFor([r]);
  const badManifest = {
    ...manifest,
    schedule: [null, ...manifest.schedule],
  };
  // The valid entry still resolves; the null member must not throw during
  // the schedule scan.
  const resolution = await resolveDailyRound(
    badManifest,
    roundsArtifact([r]),
    "2026-08-01",
  );
  expect(resolution.ok).toBe(true);
});

test("malformed round shape: fingerprinting an odd round does not throw", async () => {
  const r = round();
  const manifest = await manifestFor([r]);
  // A round that is real-records/one_hop and matches the scheduled id, but
  // whose endpoints/answer_set are malformed. Fingerprinting is pure JSON
  // serialization -- it must not throw; the content simply differs.
  const malformed = {
    id: r.id,
    pool: "real-records",
    kind: "one_hop",
    endpoints: null,
    answer_set: null,
  };
  const resolution = await resolveDailyRound(
    manifest,
    { schema_version: 1, provenance: PROVENANCE, rounds: [malformed] },
    "2026-08-01",
  );
  expect(resolution).toEqual({ ok: false, reason: "fingerprint-mismatch" });
});

// --- schema v2: multi-generation resolution (ADR 0066) ----------------------
//
// The property these exist for: after a pool regeneration, an
// already-published date must STILL resolve to its exact original round,
// while new dates resolve against the new generation -- from one manifest.

const GEN2_PROVENANCE = {
  ...PROVENANCE,
  catalog_version: "catalog-v1-20260601-newcat",
  pool_version: "connection-v1-20260601-newpool",
  artifact_version: "connection-artifact-v1-20260601-newart",
};

function gen2RoundsArtifact(rounds: GameRound[]): GameRounds {
  return { schema_version: 1, provenance: GEN2_PROVENANCE, rounds };
}

/** gen-1 holds `oldRound` on 2026-08-01; gen-2 holds `newRound` on
 * 2026-08-02 -- the real cutover shape in miniature. */
async function manifestV2(oldRound: GameRound, newRound: GameRound) {
  const { roundContentFingerprint } = await import("../src/game/canonical");
  return {
    schema_version: 2,
    mode: "connection_guesser_one_hop",
    generated_at: "2026-08-01T00:00:00+00:00",
    start_date: "2026-08-01",
    generations: [
      {
        generation_id: "gen-1",
        catalog_version: PROVENANCE.catalog_version,
        pool_version: PROVENANCE.pool_version,
        artifact_version: PROVENANCE.artifact_version,
        rounds_url: "/data/game/generations/gen-1/rounds.json",
      },
      {
        generation_id: "gen-2",
        catalog_version: GEN2_PROVENANCE.catalog_version,
        pool_version: GEN2_PROVENANCE.pool_version,
        artifact_version: GEN2_PROVENANCE.artifact_version,
        rounds_url: "/data/game/rounds.v1.json",
      },
    ],
    schedule: [
      {
        date: "2026-08-01",
        round_id: oldRound.id,
        round_fingerprint: await roundContentFingerprint(oldRound),
        generation: "gen-1",
      },
      {
        date: "2026-08-02",
        round_id: newRound.id,
        round_fingerprint: await roundContentFingerprint(newRound),
        generation: "gen-2",
      },
    ],
  };
}

test("v2: a current date resolves against the loaded newest-generation pool with no extra fetch", async () => {
  const oldRound = round();
  const newRound = round({ id: "conn-00000000ff" });
  const manifest = await manifestV2(oldRound, newRound);
  let fetches = 0;
  const resolution = await resolveDailyRound(
    manifest,
    gen2RoundsArtifact([newRound]),
    "2026-08-02",
    async (url: string) => {
      fetches += 1;
      return { url };
    },
  );
  expect(resolution.ok).toBe(true);
  if (resolution.ok) expect(resolution.round.id).toBe(newRound.id);
  expect(fetches).toBe(0);
});

test("v2: a retired-generation date still resolves to its original round via that generation's frozen rounds", async () => {
  const oldRound = round();
  const newRound = round({ id: "conn-00000000ff" });
  const manifest = await manifestV2(oldRound, newRound);
  const requested: string[] = [];
  const resolution = await resolveDailyRound(
    manifest,
    // The live pool is gen-2 and does NOT contain gen-1's round.
    gen2RoundsArtifact([newRound]),
    "2026-08-01",
    async (url: string) => {
      requested.push(url);
      return roundsArtifact([oldRound]);
    },
  );
  expect(resolution.ok).toBe(true);
  if (resolution.ok) expect(resolution.round.id).toBe(oldRound.id);
  expect(requested).toEqual(["/data/game/generations/gen-1/rounds.json"]);
});

test("v2: unknown-generation when an entry names a generation absent from generations[]", async () => {
  const oldRound = round();
  const newRound = round({ id: "conn-00000000ff" });
  const manifest = await manifestV2(oldRound, newRound);
  manifest.schedule[0].generation = "gen-nonexistent";
  const resolution = await resolveDailyRound(
    manifest,
    gen2RoundsArtifact([newRound]),
    "2026-08-01",
  );
  expect(resolution).toEqual({ ok: false, reason: "unknown-generation" });
});

test("v2: generation-rounds-unavailable when the frozen generation pool cannot be fetched", async () => {
  const oldRound = round();
  const newRound = round({ id: "conn-00000000ff" });
  const manifest = await manifestV2(oldRound, newRound);
  const resolution = await resolveDailyRound(
    manifest,
    gen2RoundsArtifact([newRound]),
    "2026-08-01",
    async () => {
      throw new Error("404");
    },
  );
  expect(resolution).toEqual({
    ok: false,
    reason: "generation-rounds-unavailable",
  });
});

test("v2: version-mismatch when a generation's rounds_url serves the wrong pool", async () => {
  const oldRound = round();
  const newRound = round({ id: "conn-00000000ff" });
  const manifest = await manifestV2(oldRound, newRound);
  const resolution = await resolveDailyRound(
    manifest,
    gen2RoundsArtifact([newRound]),
    "2026-08-01",
    // gen-1's URL wrongly serves a gen-2-provenance pool: must fail closed,
    // never deal a round from a pool this date was not frozen against.
    async () => gen2RoundsArtifact([oldRound]),
  );
  expect(resolution).toEqual({ ok: false, reason: "version-mismatch" });
});

test("v2: fingerprint-mismatch when a retired generation's round content changed", async () => {
  const oldRound = round();
  const newRound = round({ id: "conn-00000000ff" });
  const manifest = await manifestV2(oldRound, newRound);
  const tampered = round({
    answer_set: [{ id: 700, name: "Tampered", role_category: "guitar" }],
  });
  const resolution = await resolveDailyRound(
    manifest,
    gen2RoundsArtifact([newRound]),
    "2026-08-01",
    async () => roundsArtifact([tampered]),
  );
  expect(resolution).toEqual({ ok: false, reason: "fingerprint-mismatch" });
});

test("v2: not-scheduled for a date outside the schedule", async () => {
  const oldRound = round();
  const newRound = round({ id: "conn-00000000ff" });
  const manifest = await manifestV2(oldRound, newRound);
  const resolution = await resolveDailyRound(
    manifest,
    gen2RoundsArtifact([newRound]),
    "2026-09-09",
  );
  expect(resolution).toEqual({ ok: false, reason: "not-scheduled" });
});

test("v2: wrong-mode is still rejected", async () => {
  const oldRound = round();
  const newRound = round({ id: "conn-00000000ff" });
  const manifest = await manifestV2(oldRound, newRound);
  manifest.mode = "record_routes";
  const resolution = await resolveDailyRound(
    manifest,
    gen2RoundsArtifact([newRound]),
    "2026-08-02",
  );
  expect(resolution).toEqual({ ok: false, reason: "wrong-mode" });
});

test("v1 manifests still resolve unchanged after v2 support was added", async () => {
  const r = round();
  const manifest = await manifestFor([r]);
  const resolution = await resolveDailyRound(
    manifest,
    roundsArtifact([r]),
    "2026-08-01",
  );
  expect(resolution.ok).toBe(true);
  if (resolution.ok) expect(resolution.round.id).toBe(r.id);
});
