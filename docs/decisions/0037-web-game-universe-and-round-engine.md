# ADR 0037: Web game universe and round engine

- **Status:** Accepted
- **Date:** 2026-07-18

## Context

`docs/WEB_PRODUCT_PLAN.md` (merged after repository inspection and an operator
interview) commits the frontend to a flagship Connection Guesser game: choice-chip
deduction over one-hop and two-hop credit connections, a clue ladder, needle-drop
ratings, and a date-seeded daily — mobile-first, static-first, local-state-only.
Today's play surfaces are reveal-only viewers; the album grid runs on a synthetic
`challenge.v2.json` placeholder pending live gate F, while real curated data exists
only in `challenge.v1.json` (ADR 0012). No committed artifact carries the shape a
deduction game needs (answer sets, validated distractors, clues, difficulty), and
`packages/game-rules` is a placeholder, so the game layer must live in `apps/web`
for now without inventing claims the pipeline cannot back.

## Decision

Introduce two committed web artifacts and a vanilla-TypeScript round engine:

- **`game-universe-v1`** (`apps/web/public/data/game/universe.v1.json`): the
  "Meridian Tapes" synthetic universe — a fully fictional studio community
  (~30 albums, 22 contributors, reserved id ranges) authored in
  `apps/web/scripts/universe-def.mjs` and expanded deterministically. Its
  provenance self-identifies as synthetic in `source`, `license`, and `note`
  read in isolation — deliberately avoiding the `challenge.v2.json` trap where
  only `generated_by` reveals the fixture is synthetic. Sleeve art is generated
  SVG geometry with an in-art `SYNTHETIC` stamp; fictional records never carry
  real artwork.
- **`game-rounds-v1`** (`apps/web/public/data/game/rounds.v1.json`): the derived
  round pool. Two pools, badged in the UI: `synthetic-universe` (from the
  universe) and `real-records` (derived from the real curated `challenge.v1.json`;
  hotlinked Discogs art per ADR 0012; placeholder identities per ADR 0026/0035
  excluded). `scripts/build-rounds.mjs --check` is wired into the web build and
  fails on drift, empty answer sets, any distractor that actually satisfies the
  connection, missing evidence, pool-floor violations, or leak/tone-scan hits.
  `apps/web/tests/game-data.spec.ts` re-verifies the invariants from first
  principles so the generator never grades its own output.
- **Engine modules** (`apps/web/src/game/`): a pure state machine
  (idle → dealing → guessing ⇄ clue → resolving → revealed, with two-hop
  bridges-then-hidden-middle steps), seeded PRNG, needle-drop scoring, and a
  versioned `np.game.v1` localStorage store with migrations. No UI in this
  slice; no new runtime dependencies, no framework.

Future real pools — a dump-derived challenge artifact after live gate F, or a
human-reviewed cohort (ADR 0031) — plug in as additional `pool` values under the
same round shape. The misleading provenance block inside the generated
`challenge.v2.json` should be fixed at its generator
(`packages/graph-core` `build-challenge-from-dump`) so synthetic runs
self-identify in `source`, not only in `generated_by`.

## Consequences

The web app gains its first derived-and-validated game substrate and its first
(small) client logic layer while remaining static and dependency-free at runtime.
Two committed JSON artifacts join the drift-checked set; editing the universe
means editing the definition and regenerating, never hand-editing JSON. The
game layer living in `apps/web` is an accepted interim: if `packages/game-rules`
becomes real, round derivation is the first candidate to migrate behind it.
Synthetic and real content can now appear side by side, so pool badging and
provenance notes become load-bearing UI obligations, not decoration.

## Validation

`node scripts/build-rounds.mjs --check` passes and is exercised by
`npm run check`/`npm run build`; the Playwright-runner unit specs cover engine
transitions (including two-hop beats and attempt exhaustion), PRNG determinism,
scoring, store migration, sleeve determinism and stamping, first-principles
distractor correctness for both pools, pool floors (≥40 synthetic, ≥8 two-hop,
≥6 real, all difficulties), and forbidden-substring/influence-phrase scans over
both artifacts.

## Revisit trigger

Revisit when live gate F produces a real dump-derived challenge artifact (add it
as a pool and reweigh the synthetic pool's prominence), when the first
human-reviewed cohort is promoted (cohort-backed rounds with quality-flag
caveats), or if `packages/game-rules` gains a real implementation (move round
derivation and scoring behind the package boundary).
