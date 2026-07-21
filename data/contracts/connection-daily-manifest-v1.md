# Connection Guesser daily-manifest contract (connection-daily-manifest-v1)

The frozen, append-only date → round schedule for Connection of the Day
(`apps/web/public/data/game/daily-manifest.v1.json`), produced by
`networked-players-catalog build-connection-daily-manifest` /
`extend-connection-daily-manifest`
(`packages/graph-core/.../connection_daily_manifest.py`, ADR 0043's
corrective-slice-4.6 addendum).

> **Not `rounds-v1.md`'s `pool_version`/manifest concept.** PR #43's original
> `daily_manifest.py` (still used by `build-daily-manifest`/
> `extend-daily-manifest`/`validate-daily-manifest`) schedules the unrelated
> Record Routes path-shaped `rounds.py` artifact, whose `pool_version` is a
> **top-level** field. This contract's `pool_version` lives inside the
> Connection Guesser rounds artifact's `provenance`, not at the top level —
> do not assume the two manifest shapes or CLI commands are interchangeable.
> See `game-rounds-v1.md` and ADR 0043 for the full disambiguation.

## Top-level shape

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | int | Always `1`. |
| `mode` | string | Always `"connection_guesser_one_hop"` — unambiguous identity, never confusable with a Record Routes or two-hop schedule. |
| `catalog_version` | string | The canonical `apps/web/public/data/catalog/albums.v1.json` version the scheduled rounds' albums came from (copied from the rounds artifact's `provenance.catalog_version`). |
| `pool_version` | string | The scheduled rounds' pool **membership** version (copied from `provenance.pool_version`) — which puzzles exist, not their full content. |
| `artifact_version` | string | The scheduled rounds' **complete content** version (copied from `provenance.artifact_version`) — changes if any round's clues/distractors/evidence/choice-order changed, even with identical membership. |
| `generated_at` | string | ISO timestamp of the most recent build/extend operation. Not meaningful for stability — the `schedule` array is. |
| `start_date` | string | `YYYY-MM-DD` of `schedule[0].date`. |
| `schedule` | array | See below. |

## `schedule[]` entry shape

| Field | Type | Meaning |
| --- | --- | --- |
| `date` | string | `YYYY-MM-DD`, UTC calendar date. Contiguous and unique across the whole array — no gaps, no duplicates, strictly increasing. |
| `round_id` | string | A real, `pool: "real-records"`, `kind: "one_hop"` round id from the paired `rounds.v1.json` (`conn-<10 hex chars>`, see `game-rounds-v1.md`). Never a two-hop, Record Routes, or synthetic round id. |
| `round_fingerprint` | string | `round_content_fingerprint(round)` at the moment this date was scheduled (`rfp-<16 hex chars>`) — the frozen expectation for that round's **complete** published content, not just its id. |

No field is ever named `seed`; a recursive scan for a literal `seed` key
anywhere in the manifest is part of validation (matching the same convention
used for the Connection Guesser rounds/universe pair).

## Eligibility

Only rounds satisfying **all** of the following may ever appear in
`schedule[]`:

- `pool == "real-records"`
- `kind == "one_hop"`
- present in the currently-published `rounds.v1.json`

The builder filters explicitly (`_eligible_one_hop_rounds`) — it never
schedules "every id in `rounds.v1.json`." Two-hop rounds, Record Routes path
rounds, and the synthetic test fixture are structurally excluded, not merely
discouraged.

## Stability guarantees

- **Append-only, never rewritten.** Once a `date → round_id` entry is
  written, no code path in this project rewrites, reorders, or removes it.
  `extend_connection_daily_manifest` only appends dates after the current
  last date.
- **Content-verified on extension.** Before appending anything,
  `extend_connection_daily_manifest` re-verifies every EXISTING entry's
  `round_fingerprint` against the current rounds artifact. A missing round or
  a fingerprint mismatch raises immediately — the extension refuses to build
  on top of a corrupted history rather than silently accepting drift.
- **Content-verified at runtime.** The frontend (`apps/web/src/game/
  dailyManifest.ts::resolveDailyRound`) recomputes `round_content_fingerprint`
  client-side (a TypeScript port sharing the exact canonical-hashing
  algorithm, see `game-universe-v1.md`) and refuses to deal a round whose
  current content doesn't match what the manifest expects.
- **Deterministic generation and extension.** Both the initial build and
  every extension use a seeded pseudo-random permutation
  (`random.Random(pool_version)`) plus a single deterministic forward
  lookahead-swap pass that avoids the worst adjacent-day repetition (a
  repeated endpoint album or accepted performer on consecutive days) —
  reproducible from the same inputs, never live-random, never sorted-by-id
  order.
- **No repeats until the eligible pool is exhausted.** `round_id` never
  repeats across dates in one manifest. Once every eligible one-hop round has
  been scheduled once, `extend_connection_daily_manifest` raises rather than
  silently cycling or reshuffling prior dates — cycling is an explicit future
  policy decision, not implemented.
- **Never padded.** The achieved schedule length is `min(days, len(eligible))`,
  reported honestly.

## Validation

`validate_connection_daily_manifest` (generation-time,
`connection_daily_manifest.py`) checks: exact top-level and per-entry key
sets, `schema_version`/`mode` literals, required version fields present,
`pool_version` agreement with the paired rounds artifact, contiguous unique
dates, unique round ids, every round id resolves as a real one-hop round (not
merely "exists" — a two-hop or Record Routes id fails with a specific
message), every `round_fingerprint` matches a fresh recomputation, a
recursive `seed`-key scan, and forbidden-substring/influence-phrase scans.

## Diagnostics (non-gating)

`connection-daily-manifest-diagnostics` / `schedule_diagnostics` report,
purely for observability, never to gate generation: distinct/repeated round
counts, endpoint and accepted-performer use frequency, difficulty and decade
distribution, multi-answer round count, and the longest adjacent-date repeat
streak for an endpoint album or accepted performer. The scheduler does not
optimize decade/difficulty balance — only the worst adjacent-day repetition
is actively avoided; everything else is reported honestly, not engineered.

## Frontend integration

`apps/web/src/game/dailyManifest.ts::resolveDailyRound(manifest, rounds,
isoDate)`:

1. Look up `isoDate` in `manifest.schedule`. Not found → `{ok: false, reason:
   "not-scheduled"}` (rendered as "Today's connection has not been scheduled
   yet.", never a derived fallback).
2. Look up the entry's `round_id` in the already-fetched `rounds.v1.json`.
   Missing → `{ok: false, reason: "missing-round"}` (integrity error).
3. Recompute `round_content_fingerprint(round)` and compare to the entry's
   `round_fingerprint`. Mismatch → `{ok: false, reason:
   "fingerprint-mismatch"}` (integrity error).
4. Otherwise `{ok: true, round}`.

`np.game.v1` local storage (`apps/web/src/game/store.ts`) is unaffected by
this contract: `daily` results are keyed by ISO date, independent of how the
round for that date was selected, so results recorded under the prior
date-seeded system remain readable and are never rewritten.

## Revisit trigger

If a future catalog/pool regeneration changes an already-scheduled round's
content or removes it from the pool entirely, `extend_connection_daily_manifest`
will refuse to extend and the frontend will show an integrity error for that
date — this is deliberate fail-closed behavior, not a bug. Resolving it
requires an explicit operator decision (a new manifest version, a documented
exception, or accepting the integrity error for that specific historic date),
not a silent code change. If a repeat/cycling policy is ever needed once the
eligible pool is exhausted, it must be an explicit, documented, versioned
decision — not introduced silently into `extend_connection_daily_manifest`.
