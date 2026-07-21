# Connection Guesser daily-manifest contract (connection-daily-manifest-v1)

The frozen, append-only date → round schedule for Connection of the Day
(`apps/web/public/data/game/daily-manifest.v1.json`), produced by
`networked-players-catalog build-connection-daily-manifest` /
`extend-connection-daily-manifest`
(`packages/graph-core/.../connection_daily_manifest.py`, ADR 0043's
corrective-slice-4.6 and -5.1 addenda).

> **Schema-v1 rule: one manifest, one exact rounds-artifact generation.** A
> `connection-daily-manifest-v1` file's `catalog_version`/`pool_version`/
> `artifact_version` must agree EXACTLY with the paired rounds artifact's
> `provenance` before building, validating, or extending — checked before
> any output is produced. There is no support in schema v1 for a manifest
> spanning multiple rounds-artifact generations, and no per-entry or
> segmented version field. If the rounds pool genuinely needs to move to a
> new generation (new snapshot, corrected content, reordered array), that is
> an explicit, documented, versioned migration decision for an operator —
> never something `extend_connection_daily_manifest` papers over silently.

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
| `generated_at` | string | ISO timestamp of the most recent build/extend operation, an EXPLICIT required input to both `build_connection_daily_manifest`/`extend_connection_daily_manifest` (never the wall clock) — so identical arguments reproduce a byte-identical manifest. Not meaningful for stability — the `schedule` array is. |
| `start_date` | string | `YYYY-MM-DD` of `schedule[0].date`. |
| `schedule` | array | See below. |

## `schedule[]` entry shape

| Field | Type | Meaning |
| --- | --- | --- |
| `date` | string | `YYYY-MM-DD`, an ordinary calendar-date label — not tied to any one timezone. Contiguous and unique across the whole array — no gaps, no duplicates, strictly increasing. Each browser resolves this label against its OWN local calendar date (`localIsoDate`, corrective slice 5.1) — see "Local calendar day, not UTC" below. |
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
- **Deterministic generation and extension, as COMPLETE artifacts.** Both
  the initial build and every extension use a seeded pseudo-random
  permutation (`random.Random(pool_version)`) plus a single deterministic
  forward lookahead-swap pass that avoids the worst adjacent-day repetition
  (a repeated endpoint album or accepted performer on consecutive days) —
  reproducible from the same inputs, never live-random, never sorted-by-id
  order. Because `generated_at` is an explicit input rather than the wall
  clock, running either operation twice with identical arguments produces a
  byte-identical manifest file, not just an identical `schedule` array.
- **Extension-boundary adjacency.** When extending, the manifest's current
  LAST scheduled round is passed as adjacency context to the same
  lookahead-swap pass — the boundary between old and new entries is treated
  like any other adjacent pair, so the first newly appended date also avoids
  repeating the prior day's endpoint or performer when a non-conflicting
  candidate exists. A forced conflict (every remaining candidate conflicts)
  is left in place, deterministically, and shows up honestly in
  `schedule_diagnostics`' repeat-streak numbers — never hidden.
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
sets; `schema_version`/`mode` literals; required version fields present and
non-empty; **exact agreement of `catalog_version`/`pool_version`/
`artifact_version` with the paired rounds artifact** (all three, not just
`pool_version` — the schema-v1 single-generation rule above); a valid ISO
`generated_at`; a valid ISO `start_date` that equals `schedule[0].date`;
a non-empty schedule; contiguous unique dates; unique round ids; every
round id matches the `conn-<10 hex chars>` format and resolves as a real
one-hop round (not merely "exists" — a two-hop or Record Routes id fails
with a specific message); every `round_fingerprint` matches both the
`rfp-<16 hex chars>` format and a fresh recomputation; a recursive
`seed`-key scan; and forbidden-substring/influence-phrase scans. Invalid
date/datetime strings produce a controlled `ConnectionDailyManifestError`,
never an uncaught `ValueError`.

`extend_connection_daily_manifest` runs the version-agreement check FIRST,
before touching anything else — a mismatch fails before any output is
produced, and before the per-entry fingerprint re-verification even begins.

## Diagnostics (non-gating)

`connection-daily-manifest-diagnostics` / `schedule_diagnostics` report,
purely for observability, never to gate generation: distinct/repeated round
counts, endpoint and accepted-performer use frequency, difficulty and decade
distribution, multi-answer round count, and the longest adjacent-date repeat
streak for an endpoint album or accepted performer. The scheduler does not
optimize decade/difficulty balance — only the worst adjacent-day repetition
is actively avoided; everything else is reported honestly, not engineered.

## Frontend integration

`apps/web/src/game/dailyManifest.ts::resolveDailyRound(manifest,
roundsArtifact, isoDate)` takes the COMPLETE fetched `GameRounds` artifact
(schema_version + provenance + rounds), not just the rounds array, and
verifies the full pairing before dealing a round. Every field this function
depends on is checked with a runtime guard first (`isGameRoundsArtifact`/
`isDailyManifest`) — a TypeScript type assertion is never treated as runtime
proof, since both fetched JSON files are untrusted input:

1. Both artifacts must be well-formed and at a schema version this build
   understands. Failing either → `{ok: false, reason:
   "unsupported-manifest"}`.
2. `manifest.mode` must be exactly `"connection_guesser_one_hop"`. Otherwise
   → `{ok: false, reason: "wrong-mode"}`.
3. `catalog_version`/`pool_version`/`artifact_version` must agree EXACTLY
   between the manifest and `roundsArtifact.provenance` (mirrors
   `_version_mismatches` above). Otherwise → `{ok: false, reason:
   "version-mismatch"}`.
4. Look up `isoDate` in `manifest.schedule`. Not found → `{ok: false,
   reason: "not-scheduled"}` (rendered as "Today's connection has not been
   scheduled yet.", never a derived fallback).
5. Look up the entry's `round_id` in `roundsArtifact.rounds`. Missing →
   `{ok: false, reason: "missing-round"}`.
6. That round must actually be `pool: "real-records"` and `kind:
   "one_hop"`. Otherwise → `{ok: false, reason: "ineligible-round"}` — catches
   a manifest somehow pointing at a two-hop or synthetic round, which must
   never be dealt as a daily.
7. Recompute `round_content_fingerprint(round)` and compare to the entry's
   `round_fingerprint`. Mismatch → `{ok: false, reason:
   "fingerprint-mismatch"}`.
8. Otherwise `{ok: true, round}`.

Each reason is independently testable (`apps/web/tests/game-dailyresolver.spec.ts`);
the UI (`flagship.ts`) may render several under one shared integrity message,
but the resolver never blurs them together.

`np.game.v1` local storage (`apps/web/src/game/store.ts`) is unaffected by
this contract: `daily` results are keyed by ISO date, independent of how the
round for that date was selected, so results recorded under the prior
date-seeded system remain readable and are never rewritten.

## Local calendar day, not UTC

Connection of the Day rolls over at the PLAYER'S LOCAL calendar midnight,
not UTC (corrective slice 5.1) — a deliberate product decision. The
committed manifest's `schedule[].date` is an ordinary `YYYY-MM-DD` label,
not tied to any timezone; `apps/web/src/game/localDate.ts::localIsoDate`
computes the effective date from the browser's own local-time getters
(`getFullYear`/`getMonth`/`getDate`), never `toISOString`/`getUTC*`. This
means **players in different time zones enter the next scheduled puzzle at
their own local midnight, not simultaneously** — the schedule itself never
changes, only when each browser considers "today" to have arrived.

## Date-override gate (`?date=`)

The `?date=` query parameter exists so Playwright and local development can
pin a specific calendar date; production must never honor it (a visitor
could otherwise peek at a future scheduled connection by editing the URL —
no secret is compromised either way, since the manifest is public, but this
is not something to expose casually). `apps/web/src/game/dateOverride.ts::
isDateOverrideAllowed()` gates it:

- `true` under `astro dev` (`import.meta.env.DEV`) — never true for
  `astro build` or the `astro preview` server, so a real production deploy
  (`astro build` + `wrangler deploy`) never has this set.
- `true` when a test harness has explicitly injected
  `window.__NP_ALLOW_DATE_OVERRIDE__ = true` before navigation (Playwright,
  via `page.addInitScript`) — there is no way to set this from outside the
  page's own JS context.

A production visitor's `?date=` is silently ignored; the effective date
falls back to `localIsoDate(new Date())`, never a derived-from-date-string
fallback.

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
