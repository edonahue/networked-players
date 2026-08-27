# ADR 0066: A bounded, human-authored exception to the never-rewrite daily-manifest rule

- **Status:** Accepted
- **Date:** 2026-08-27

## Context

[ADR 0041](0041-frozen-append-only-daily-manifest.md) established that a published
`date -> round_id` schedule entry is never rewritten — only appended to, via
`extend_daily_manifest` / `extend_connection_daily_manifest`. That ADR's own revisit
trigger names exactly one case where that guarantee should be deliberately
relaxed: "a real operational need ever requires reassigning an already-published
date," which "would need its own explicit tooling and an audit trail, not a code
path that treats any date as ordinarily mutable."

Phase 7's catalog expansion is that operational need. Growing the public catalog
from 140 to ~180 albums regenerates the Connection Guesser rounds pool from a new
snapshot generation. The owner's decision for this phase (recorded in the Phase 7
plan) was to cut over to the new generation sooner than the pure-append design
would allow — rather than waiting for all 90 already-scheduled real dates to run
out before a single new-generation round is ever shown, unreached future dates in
the existing schedule may be replaced with new-generation rounds ahead of that.

This is a schedule rewrite in the literal sense ADR 0041 warns about, so it needs
its own tooling, its own safety invariant, and its own audit trail — not a silent
capability bolted onto the existing append path.

## Decision

`connection_daily_manifest.py` gains a schema v2 shape (`upgrade_connection_daily_manifest_to_v2`,
`migrate_connection_daily_manifest_generation`, `validate_connection_daily_manifest_v2`)
that adds a `generations[]` list to the manifest and a `generation` tag to every
schedule entry, and permits exactly one new mutation on top of v1's append-only
rule:

- **What may be rewritten:** only schedule entries whose `date` is `>= cutover_date`,
  for an operator-chosen `cutover_date`. Every entry strictly before `cutover_date`
  is carried over byte-identical — same `date`/`round_id`/`round_fingerprint`/
  `generation` — and is re-verified against its own generation's rounds artifact
  before anything is written, so this can never run on top of an already-corrupted
  history.
- **Why this is safe despite being a rewrite:** the manifest schema stores only
  `date`/`round_id`/`round_fingerprint`, never round content, and the game UI never
  renders a future date's round before that date arrives (`dailyArchive.ts`).
  Replacing an unreached, unrevealed future entry changes nothing any visitor has
  ever seen, played, or shared — the invariant ADR 0041 actually protects
  (temporal stability of what a visitor already saw) is untouched.
- **The safety margin on `cutover_date` itself:** `apps/web/src/game/localDate.ts`
  deliberately rolls a date over at each *player's own local midnight*, not UTC
  midnight. The real timezone spread (UTC-12 to UTC+14) is about 26 hours, so at
  any instant a player's local calendar date can already be one day ahead of the
  operator's own UTC "today." `migrate_connection_daily_manifest_generation`
  therefore refuses any `cutover_date` less than `_MIN_CUTOVER_LEAD_DAYS = 2` full
  days after the supplied `generated_at`, not merely "the day after" — closing the
  one-day-early edge case a real operator running this near their own midnight
  could otherwise hit.
- **Contiguity is enforced, not assumed:** the function also refuses a
  `cutover_date` that would leave a gap between the last kept date and the first
  new one (found while writing this feature's own tests, not anticipated in the
  original plan — see the "Errors and fixes" note in the PR description).
- **The audit trail:** `generations[]` is itself append-only. Every migration adds
  exactly one new generation entry naming its own `catalog_version`/`pool_version`/
  `artifact_version`/`rounds_url`; no prior generation entry is ever modified.
  `validate_connection_daily_manifest_v2` re-verifies every schedule entry's
  fingerprint against its *own* named generation's rounds artifact, and cross-checks
  each `generations[]` entry's version fields against that same artifact's own
  provenance — so a hand-edited generation entry, or a validation run against the
  wrong artifact, is caught rather than silently accepted.
- **This is deliberately narrow, not a general rewrite capability.** There is no
  code path that touches a date before `cutover_date`, no way to target an
  arbitrary past date, and no way to skip the fingerprint re-verification of
  everything kept. A human operator chooses `cutover_date` for one specific,
  one-time catalog-generation cutover; this is not exposed as an ordinary
  extend-style operation.

## Consequences

- The real 90 already-published dates in `apps/web/public/data/game/daily-manifest.v1.json`
  survive the v1 -> v2 structural upgrade byte-identical (proved directly against
  the real committed file, not just a fixture, in
  `test_upgrade_preserves_every_one_of_the_real_committed_manifest_entries`).
- Only unreached future dates within the existing 90-date runway (or beyond it)
  can ever be replaced; every real visitor's already-seen date is untouched by
  construction, not by policy alone.
- `daily-manifest.v1.json` becomes a multi-generation artifact going forward.
  `apps/web/src/game/dailyManifest.ts`'s client-side resolver needs a follow-up
  change to resolve a schedule entry's `generation` to the right rounds URL — out
  of scope for this ADR, tracked as a separate PR in the Phase 7 plan.
- This is a one-time exception mechanism for a real, named operational need
  (Phase 7's catalog regeneration), not a standing capability to be reached for
  casually. Using it again outside a genuine new-generation cutover should prompt
  re-reading this ADR's reasoning, not just its function signature.

## Validation

`packages/graph-core/tests/test_connection_daily_manifest_v2.py` (24 tests) covers:
lossless v1->v2 structural upgrade including the real committed manifest;
byte-identical preservation of every kept entry across a migration; rejection of
a cutover inside the unsafe lead-time window; rejection of a cutover that would
leave a schedule gap; rejection of a reused generation id, a missing rounds
artifact for a kept generation, and a silently-changed kept round; determinism of
the migration for fixed inputs; and validator coverage for cross-generation round
id collisions, missing/duplicate `generations[]` entries, tampered content, and a
mismatched generation-to-artifact provenance pairing.
`packages/catalog/tests/test_cli_connection_daily_manifest_v2.py` (5 tests) pins
the CLI wiring for `upgrade-connection-daily-manifest-to-v2`,
`migrate-connection-daily-manifest-generation`, and
`validate-connection-daily-manifest-v2`, including the shared
`GENERATION_ID=PATH` argument parsing.

## Revisit trigger

Revisit if a future need arises to rewrite a date *before* the cutover point (a
kept, already-scheduled entry) — that is a fundamentally different guarantee than
this ADR makes and would need its own decision, not an extension of this one.
