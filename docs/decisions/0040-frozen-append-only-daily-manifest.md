# ADR 0040: A frozen, append-only date-to-round manifest for Connection of the Day

- **Status:** Accepted
- **Date:** 2026-07-19

## Context

Connection of the Day needs every visitor on a given calendar date to see the same
round, and needs that mapping to stay fixed forever once published — a visitor who
plays on a date and returns later must see the same answer they already saw, and a
shared link to "today's" round must keep working after the day has passed. The
operator's brief was explicit: "frozen/versioned mechanism, no naive modulo."

A naive `hash(date) % len(rounds)` or `date_index % len(rounds)` mapping is unstable
under the one change this project's own real-data process guarantees will happen
repeatedly: growing the rounds pool. Regenerating `rounds.v1.json` with more rounds
changes `len(rounds)` (or a round's position in a re-sorted list), which changes
every future date's `% len(rounds)` result and can silently reassign a date that was
already played and shared — exactly the failure mode "frozen" is meant to rule out.

## Decision

`daily_manifest.py` builds an explicit, materialized `date -> round_id` table
(`daily-manifest.v1.json`), not a formula evaluated at request time. Two operations,
never a third:

- `build_daily_manifest(round_ids, pool_version, start_date, days)` — the one-time
  initial build. Assignment order is a deterministic pseudo-random permutation,
  `random.Random(pool_version).shuffle(round_ids)`, not sorted `round_id` order (so
  consecutive days don't visibly correlate with generation order) and not
  live-random (so the exact same `pool_version` always reproduces the exact same
  schedule — proven by a regression test that rebuilds the pool and re-asserts a
  pinned date's round ID is unchanged). Never schedules more dates than there are
  distinct rounds: the achieved length is `min(days, len(round_ids))`, reported
  honestly rather than padded by repeating a round across dates.
- `extend_daily_manifest` — the only way to add capacity once the schedule runs out.
  It appends new dates starting the day after the manifest's current last date,
  drawn only from rounds not already scheduled anywhere in the manifest. It never
  rewrites an existing `date -> round_id` entry, regardless of pool regeneration or
  growth in between.

There is no code path that regenerates or resorts already-assigned dates. A rebuild
of the underlying rounds pool changes what's available for *future* `extend_daily_manifest`
calls; it cannot touch a date already in the file. The manifest file itself, not a
formula, is the source of truth — this is what makes stability provable by reading
the file rather than by reasoning about a shuffle's properties.

## Consequences

- Real launch measurement: 172 scheduled dates from a 172-round pool
  (`docs/DATA_SIZING.md`) — every real round got exactly one date, with room to
  `extend_daily_manifest` as the pool grows in a future generation pass.
- Growing the rounds pool later is always safe for already-published dates: run
  `extend-daily-manifest`, never `build-daily-manifest`, against an existing
  manifest file.
- The cost of this guarantee is that `daily-manifest.v1.json` must be treated as an
  accumulating, versioned artifact in its own right (schema-versioned, contract-
  validated by `validate_daily_manifest`/the Playwright gap-and-duplicate check in
  `rounds-manifest.spec.ts`), not a value re-derived on demand from `rounds.v1.json`
  alone.
- If a `pool_version` is ever retired in favor of a new one (a rounds pool rebuilt
  from a new snapshot, say), the old manifest's already-published dates remain valid
  history; a new `pool_version` starts a new manifest rather than silently
  reassigning the old one's dates.

## Validation

`packages/graph-core/tests/test_daily_manifest.py` covers determinism for a fixed
`pool_version` (`test_build_daily_manifest_is_deterministic_for_a_fixed_pool_version`),
divergence across `pool_version`s, no-padding-past-available-rounds, duplicate-round
rejection, and `extend_daily_manifest` appending after the last date without
touching history. `apps/web/tests/smoke.spec.ts`'s "daily page resolves today's
exact round from the frozen manifest" test proves the end-to-end property that
actually matters to a visitor: it cross-checks the live page's rendered round
against the published manifest file for the real current date, then reloads and
re-asserts the identical round renders again — confirming the page reads the frozen
file rather than re-deriving a round at request time.

## Revisit trigger

Revisit if a real operational need ever requires reassigning an already-published
date (e.g. a scheduled round is discovered to leak an answer and must be pulled).
That is a deliberate, human-authored exception to "never rewrite," not something
this mechanism should support silently — it would need its own explicit tooling and
an audit trail, not a code path that treats any date as ordinarily mutable.
