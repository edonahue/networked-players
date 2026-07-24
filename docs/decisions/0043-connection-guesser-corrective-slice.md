# ADR 0043: Corrective slice for the real Connection Guesser pool (slices 4.5, 4.6)

- **Status:** Accepted
- **Date:** 2026-07-21 (slice 4.5); addendum 2026-07-22 (slice 4.6)
- **Extends:** [ADR 0042](0042-real-connection-guesser-pool.md) without reverting it
- **Relates to:** [ADR 0038](0038-hybrid-album-catalog-assembly.md), [ADR 0041](0041-frozen-append-only-daily-manifest.md)

## Context

ADR 0042 shipped a real, Python-generated Connection Guesser pool (500
rounds), correctly replacing the synthetic-first pool and correctly choosing
the album-credit-intersection semantic over `rounds.py`'s path semantic. A
focused post-ship review of that slice found eleven real defects in the
generator, frontend, validator, catalog, and docs it produced — not
architectural mistakes, but correctness and honesty gaps within the chosen
architecture. This ADR documents the corrective slice ("4.5") that fixed all
eleven before any later slice (daily manifest, Record Routes, cover art)
built on top of the flawed artifacts.

## Findings and fixes

1. **PAN/ANV conflation.** `ContributorRef.name` used `row["anv"] or
   row["name"]` — a real person's chip label varied round to round depending
   on which release's ANV happened to be picked. Fixed: `ContributorRef.name`
   is always the canonical PAN-resolved name; `EvidenceRow.credited_as`
   alone carries the ANV/as-credited spelling.
2. **Incomplete two-hop bridge answers.** `bridge_a_id = min(bridge_a)`
   published only the lowest-artist_id performer as a bridge's answer, even
   when multiple real performers validly bridged that side — and the
   others were left eligible as "proven wrong" distractors, which they were
   not. Fixed: every valid performer per side is published in
   `bridge_answer_sets`, with evidence for each; a "primary" performer is
   still chosen (lowest id) but only for clue text, never for correctness.
3. **Distractors excluded only the primary bridge ids.** Same root cause as
   (2): the distractor pool excluded only the two "primary" ids, so a real
   alternate bridge performer could ship as a distractor. Fixed: distractors
   exclude the full union of every valid bridge performer on both sides.
4. **Hidden middle always at choice index 0.** `choices = [middle_ref] +
   [...]` never shuffled — the hidden-middle step was guessable by position
   alone. Fixed: choices are shuffled by a seed deterministically derived
   from the round's own stable id (`_seeded_shuffle`), reproducible across
   regeneration, never wall-clock random and never a fixed index.
5. **Frontend two-hop reveal used an empty `answer_set`.** `flagship.ts`
   built the verdict/correctness logic from `round.answer_set`, which is
   always `[]` for a two-hop round by design (each bridge has its own
   answer set, not the round as a whole). A player who gave up or failed
   before reaching the middle step saw no chip marked correct, and the
   verdict heading read literally `"The answer was , through <title>"` — an
   empty name before the comma. Fixed: `finishRound` now reads the correct
   answer set for whichever step's tray was on screen
   (`answersForStep(trayStep)`), and the verdict text names both bridges'
   real answers plus the hidden middle (`describeAnswer()`). New pinned
   Playwright tests cover a clean solve, giving up at each of the three
   steps, and multi-answer chip marking.
6. **Clue wording implied a single answer.** The role/initials clues named
   only the "primary" answer's role/initials with no hedge, misleading for
   any round with more than one valid answer (71/300 one-hop rounds already
   had one before this fix). Fixed: `_role_clause`/`_initials_clause` add an
   honest qualifier ("… work (among other valid answers)", "… (one of
   several valid answers)") whenever more than one valid answer exists for
   that step.
7. **Ordinal, position-dependent round ids.** `f"conn-{index:06d}"` assigned
   after final selection meant a round's identity depended on where it
   landed in the selected pool — reordering or regenerating the pool at a
   different target could reassign an existing round's id, which a future
   frozen daily manifest cannot tolerate. Fixed: `_stable_id` derives a
   round's id from a sha256 digest of its own canonical semantic fields
   (sorted endpoint album ids + sorted answer ids for one-hop; endpoint ids +
   middle id + sorted bridge answer ids per side for two-hop) —
   insertion/selection-order independent, verified by regenerating the pool
   at two different targets and checking ids match for rounds selected both
   times.
8. **The published universe was an evidence-only subset, not a complete
   index.** `GameUniverse.credits[]` was built only from rounds' own
   `evidence[]` rows — performers who never became a round's answer (e.g.
   two albums' *other* shared/non-shared performers) were absent. This
   made a genuinely independent re-derivation of "who is credited on both of
   these albums" impossible from the published artifact alone;
   `apps/web/tests/game-data.spec.ts` could only check a one-directional
   subset against a different, narrower artifact (`challenge.v2.json`, which
   is pre-filtered for an unrelated path-discovery process and routinely
   under-reports real credits). Fixed: `build_connection_universe_and_rounds`
   now takes the generator's own complete per-album performer index and
   publishes every eligible credit for every album referenced by a round —
   not just the evidence-cited ones. `game-data.spec.ts` now checks exact
   equality between the universe's own complete data and every round's
   published answer/bridge sets, in both directions.
9. **The validator didn't check enough, and the wrong validator could be
   pointed at real data.** `validate_connection_rounds_artifact` didn't check
   exact top-level key sets, schema/catalog/pool version fields, stable-id
   format, a recursive `seed`-key leak, or that an eliminate clue never
   targets a valid answer. Separately, `packages/contracts/.../rounds.py`
   (the Record Routes path-contract validator) and its Pi-fleet job
   (`infra/ansible/files/rounds_check_job.py`,
   `deploy-rounds-check-job.yml`) defaulted to the exact same file paths
   (`apps/web/public/data/game/{universe,rounds}.v1.json`) the *real,
   currently-published* Connection Guesser pool now lives at — a live
   wiring bug, not a hypothetical one: running that playbook's default
   invocation would validate real Connection Guesser data against the wrong
   contract. Fixed: the graph-core validator gained the full checklist; a
   new dependency-free `networked_players_contracts.connection_rounds`
   mirrors it (`connection_rounds_failures`) for Pi-fleet/web-build use; a
   new `infra/ansible/files/connection_rounds_check_job.py` job body and an
   updated `deploy-rounds-check-job.yml` point the default paths at the
   correct validator; every affected module's docstring now explicitly
   disambiguates the two contracts and warns that "rounds.v1" alone never
   identifies which one an artifact satisfies.
10. **`challenge.v2.json`'s `albums[]` was treated as the catalog's source of
    truth.** The Connection Guesser generator's own docstring said so
    explicitly. This is backwards: a single-purpose artifact (the album
    browser's evidence-path challenge) should not be the thing that decides
    which albums exist for every other real surface. Fixed: `catalog_version`
    added to `assemble_album_catalog`'s output; the catalog is now published
    at `apps/web/public/data/catalog/albums.v1.json` as the canonical,
    versioned, independently validated (`validate_album_catalog`) source of
    truth. Both `build-challenge-from-dump --albums` and
    `build-connection-rounds --albums` (renamed from `--challenge`) consume
    the *same* file; `challenge.v2.json`'s own provenance now records the
    `catalog_version` it was built from, so any two real artifacts can be
    checked for catalog agreement without re-deriving anything.
11. **Two more non-studio albums with no structured Discogs signal.** A
    full audit (`docs/STUDIO_ALBUM_CATALOG_AUDIT.md`) of the real 140-album
    catalog, prompted by two operator-found leaks (*Eat A Peach* — mixed
    live/studio; *We Are The World* — charity/various-artists single), found
    two more of the same class: *Friday Night In San Francisco* (live) and
    *Rattle And Hum* (mixed live/studio, companion to a concert
    documentary). All four share the exact pattern the deny-list already
    existed for: zero `Live`/`Compilation` format descriptors across every
    working-set pressing, no matching master genre/style, no title token a
    regex could key on. All four added to
    `data/albums/studio-album-master-exclusions-v1.json` with the same
    evidentiary reasoning style as the pre-existing two entries. The catalog
    was regenerated at the same `target_count` (140); the four excluded
    masters were backfilled by four other real, verified studio albums from
    the candidate ranking.

## Consequences

Real, measured (`snapshot=20260601`, corrected 140-album catalog,
`catalog_version` recorded in every downstream artifact's provenance) — see
the corrective-slice-4.5 PR comment for exact regenerated counts against the
launch floor (≥50 one-hop, ≥20 two-hop) and quality/diversity metrics
(endpoint/bridge-use distribution, multi-answer round counts, answer-position
distribution).

- `apps/web/public/data/catalog/albums.v1.json` is a new canonical public
  artifact (Finding 10); `apps/web/src/game/flagship.ts` gained
  `answersForStep`/`describeAnswer` (Finding 5); `apps/web/tests/
  game-data.spec.ts` now does exact-equality first-principles verification
  instead of a one-directional subset check (Finding 8).
- `packages/graph-core/.../connection_rounds.py`'s diversity cap
  (`_select_diversified`) now penalizes/caps by individual bridge-performer
  id, not a compound pair-string key — a performer who bridges many
  different album pairs is capped across all of them, closing a real gap
  the operator flagged (unverified before this slice; confirmed real once
  `bridge_answer_sets` could contain more than one id per side).
- `generate_connection_round_pool` now returns the complete per-album
  performer index as a third value, threaded into
  `build_connection_universe_and_rounds` — a new internal dependency, not a
  new external one.

## Validation

`packages/graph-core/tests/test_connection_rounds.py` gained a regression
fixture with two real shared performers on one bridge side (one with a lower
artist_id than the other, reproducing exactly what the old `min()`
implementation would have gotten wrong) plus new tests for: complete bridge
answer sets, PAN/ANV separation, honest multi-answer clue wording, stable-id
pool-regeneration invariance, deterministic seeded shuffling, universe credit
completeness, and validator rejection of a missing `catalog_version` or an
unstable round id. `packages/contracts/tests/test_connection_rounds_contracts.py`
is new, covering the dependency-free mirror's rejection cases independently.
`apps/web/tests/game-twohop.spec.ts` gained pinned tests for a clean solve, a
mid-walk failure with a non-empty verdict, giving up at each of the three
steps, multi-answer chip correctness, and a real-pool answer-position
distribution check. Full validation results (make check, npm run check,
Playwright, catalog audit, deterministic-regeneration check) are recorded in
the corrective-slice-4.5 PR comment, not duplicated here.

## Daily-manifest migration implications (documented, not built)

Slice 5 (the frozen daily manifest, explicitly out of scope for this
corrective slice) can now safely reference these stable, content-derived
round ids: an id survives pool regeneration as long as the round's own
endpoints/answers/bridges are unchanged, so a frozen date -> round-id mapping
built against this pool won't silently point at a different round after a
future regeneration the way an ordinal id could have. Two things slice 5 will
still need to handle, not fixed here: (1) a round whose underlying credit
data is later corrected (e.g. a future catalog audit excludes an album this
pool used) will get a *different* stable id or vanish from the pool entirely
— the manifest's "never silently reassign a published date" rule (ADR 0041)
needs an explicit invalidation path for that case, not just id stability; (2)
`pool_version` (new in this slice) should become the manifest's
cross-check field alongside `catalog_version`, so a manifest built against
one pool generation can detect if it's being validated against a
different one.

## Addendum: corrective slice 4.6 (2026-07-22)

Before implementing the frozen daily manifest (slice 5), a smaller follow-up
review found five reproducibility/correctness gaps in slice 4.5's own output
— fixed here, ahead of freezing anything against them.

1. **`pool_version` only ever hashed round ids (membership), never full
   content.** A clue rewording, a distractor swap, or a middle-choice
   reshuffle on an already-selected round left `pool_version` unchanged —
   exactly the kind of silent drift a frozen daily manifest cannot tolerate.
   Fixed: a new `artifact_version` (`connection_rounds.py::artifact_version`)
   hashes the round array's COMPLETE published content, built from each
   round's own `round_content_fingerprint`. Both are canonical-JSON content
   hashes (sorted keys, no whitespace-sensitivity) via a genuinely shared
   primitive, `networked_players_contracts.canonical`, ported byte-for-byte
   to TypeScript in `apps/web/src/game/canonical.ts` (cross-language
   agreement proven by `apps/web/tests/game-canonical.spec.ts`). Stable round
   ids (`_stable_id`) are unchanged — they were already semantic-fields-only,
   correctly excluding presentation. Both validators now recompute and
   reject a stale `artifact_version`, and recompute a round's own id from its
   published semantic fields (catching an id that doesn't match its own
   content, not just a malformed one).
2. **The production catalog CLI could silently omit every policy input.**
   `build-album-catalog`'s `--masters-root`/`--release-format-policy`/
   `--studio-album-exclusions` were all optional, so nothing stopped an
   under-gated catalog from being built and published by mistake. Fixed: a
   new `build-public-album-catalog` command makes all three required and
   cross-checks their `snapshot_date` against the one-hop dataset's, failing
   immediately on a missing, malformed, empty, or mismatched-snapshot input.
   `build-album-catalog` is now explicitly documented as exploratory-only,
   not the way to produce the committed catalog. Regenerating the real
   catalog through the new command reproduced the exact same
   `catalog_version` as the currently-published one — proof of no
   unintended drift, not a reason to republish it.
3. **The two-hop premise overclaimed.** "No one is credited on both of these
   records" is false whenever a non-performer (producer, engineer) happens
   to share both records — the actual, narrower invariant is "no *eligible
   performer*." Fixed in `flagship.ts`'s `questionFor` (and the one-hop
   question's "One person" → "One eligible performer," the same imprecision
   in miniature); pinned in both `game-flagship.spec.ts` and
   `game-twohop.spec.ts`.
4. **The two validators' docstrings overclaimed generation-time's power.**
   Both `validate_connection_rounds_artifact` and its dependency-free mirror
   in fact operate on the same inputs — the already-built `universe`/`rounds`
   pair, no live graph connection — so both can (and, after this slice, do)
   recompute exact intersections, distractor invalidity, "no direct eligible
   performer between two-hop endpoints" (new: universe-derived, no graph
   needed), stable ids, and `artifact_version`, all from the universe's
   complete credits (Finding 7). Neither re-verifies two-hop middle-album
   uniqueness across the *entire* catalog post-hoc — that guarantee is
   enforced by construction during discovery, not independently checkable
   from the smaller published universe. Both docstrings now say exactly
   this, replacing language that implied generation-time re-queried the
   source graph at validation time (it does not).
5. **The prose catalog audit wasn't a provable record.** Nothing confirmed
   `docs/STUDIO_ALBUM_CATALOG_AUDIT.md` actually covered all 140 albums, or
   would catch a future catalog drifting from what it described. Fixed: a
   new committed `docs/data/studio-album-catalog-audit-v1.json`
   (`networked_players_graph_core.catalog_audit`, `build-album-catalog-audit`
   / `validate-album-catalog-audit`) — one row per catalog album, tied to a
   `catalog_version`, cross-validated for exact 1:1 correspondence with the
   catalog. The prose document now points to it as the machine-checkable
   companion rather than claiming to be one itself.

Validation: `make check` (554 tests, +34 new), `npm run check` (0 errors),
full Playwright suite (89/89, +7 new). The real Guesser pool was regenerated
once (to add `artifact_version`) and diffed byte-for-byte against the prior
publish before republishing — every round's content and `pool_version` were
identical; only the new provenance field changed.

## Addendum: slice 5, frozen Connection of the Day (2026-07-22)

With slice 4.6's `artifact_version`/`round_content_fingerprint` in place,
slice 5 implements the frozen daily manifest itself:
`packages/graph-core/.../connection_daily_manifest.py`
(`data/contracts/connection-daily-manifest-v1.md`) — a **new** module, not a
reuse of `daily_manifest.py` (see ADR 0041's correction note: that module was
built and proven against the unrelated Record Routes artifact shape).

- **Explicit eligibility filtering.** The builder only ever schedules
  `pool == "real-records"` AND `kind == "one_hop"` rounds — never "every id
  in `rounds.v1.json`."
- **Content-verified extension.** `extend_connection_daily_manifest`
  re-verifies every existing entry's `round_fingerprint` against the current
  rounds artifact before appending anything; a missing round or a changed
  fingerprint raises rather than extending on top of a broken history.
- **Deterministic, non-overengineered scheduling.** A seeded pseudo-random
  permutation (`pool_version`) plus one deterministic forward lookahead-swap
  pass that avoids the worst adjacent-day repetition (a shared endpoint album
  or accepted performer two days running) — not a recommendation system;
  decade/difficulty balance is reported via `schedule_diagnostics`, never
  optimized for.
- **No repeats until pool exhaustion**, at which point extension raises with
  a documented policy error rather than silently cycling.
- **Frontend**: `apps/web/src/game/dailyManifest.ts::resolveDailyRound`
  replaces the old date-seeded `pickDaily` (`dailySeed`/`createRng`)
  entirely. It resolves a date through the manifest, then recomputes
  `round_content_fingerprint` client-side (`apps/web/src/game/canonical.ts`,
  the same shared canonical-hashing port slice 4.6 built) and refuses to
  deal a round whose current content doesn't match what the manifest
  expects. Four distinct graceful states, all rendered into the existing
  stage shell (`showStageError`), never a thrown error and never a derived
  fallback: round-pool fetch failure, manifest fetch failure, date not
  scheduled, and an integrity error (missing round or content mismatch) —
  pinned in Playwright via real `page.route` interception, not mocked
  assumptions.
- **Storage**: `np.game.v1`'s `daily` map is keyed by ISO date and was never
  touched by this change — results recorded under the old date-seeded system
  remain readable untouched; no schema-version bump was needed.

**Real committed manifest**: 90 dates, `2026-08-01` through `2026-10-29`
(chosen as a near-term date since this branch/PR has not launched — not a
retroactive assignment of already-passed dates), drawn from 90 of the 300
real one-hop rounds (210 remain for future `extend-connection-daily-manifest`
calls, deliberately not consuming the whole pool on the first publish).
Deterministic regeneration confirmed byte-identical (excluding the
`generated_at` timestamp); the append-only extension workflow was verified to
preserve all prior entries byte-for-byte while adding new ones. See the
corrective-slice PR comment for the full schedule diagnostics.

Validation: `make check` (578 tests, +24 over slice 4.6's 554), `npm run
check` (0 errors), full Playwright suite (100/100, +15 new in
`game-daily.spec.ts` replacing the old date-seeded-shuffle tests entirely, +
1 in `game-canonical.spec.ts` already counted in slice 4.6).

## Revisit trigger

If a future catalog expansion or policy change admits new candidates, re-run
the audit in `docs/STUDIO_ALBUM_CATALOG_AUDIT.md` and regenerate
`docs/data/studio-album-catalog-inclusion-audit-v1.json` (renamed from
`studio-album-catalog-audit-v1.json` in slice 5.1 to make its scope
unambiguous — see that addendum below) — the deny-list categories the
prose audit covers are specifically the ones with no structured Discogs
signal, so a new candidate can silently reintroduce the same class of leak
without a human pass, and a stale JSON audit will fail
`validate-album-catalog-audit` against the new `catalog_version`. If Record
Routes (slice 6) ever needs to publish its artifact at the same file names
this ADR's Connection Guesser pool uses, stop and resolve the collision
explicitly rather than letting the two contracts overwrite each other on
disk. If a future catalog/pool regeneration changes an already-scheduled
round's underlying content or removes it entirely, `extend_connection_daily_manifest`
will refuse to extend and the frontend will show an integrity error for that
date until an operator makes an explicit decision — this is deliberate,
not a bug to silently patch around. A repeat/cycling policy for after pool
exhaustion must be an explicit, documented, versioned decision, not a quiet
code change.

## Addendum: corrective slice 5.1 (2026-07-22) — hardening the frozen contract

A focused follow-up review of the slice-5 daily manifest found real gaps in
the version-agreement and reproducibility guarantees it claimed, plus two
correctness/product gaps in the frontend (UTC-day rollover, an ungated
`?date=` override) and one honesty gap in the catalog audit's scope. All
fixed without reverting the slice 5 architecture (dedicated module, real
one-hop-only eligibility, append-only schedule, per-round fingerprints,
graceful frontend failure) and without moving any already-assigned date.

1. **Strict single-artifact-version manifest (schema v1).** The manifest
   recorded `catalog_version`/`pool_version`/`artifact_version`, but only
   `pool_version` was ever checked against the paired rounds artifact — an
   extension could append rounds from a differently-versioned artifact while
   keeping the old manifest-level `artifact_version`. Fixed:
   `_version_mismatches` now requires exact three-way agreement, checked
   before any output in both `validate_connection_daily_manifest` and
   `extend_connection_daily_manifest` (fail-before-output). No schedule
   segments or per-entry artifact versions — a manifest genuinely spanning
   two generations is out of scope for schema v1 by design; a real
   generation change requires an explicit versioned migration.
2. **`artifact_version` now reflects PUBLISHED ORDER.** It previously
   sorted per-round fingerprints before hashing — order-insensitive, even
   though `rounds[]`'s array order is itself part of the published artifact
   and can affect ordinary set ordering. Fixed in both
   `networked_players_graph_core.connection_rounds::artifact_version` and
   its dependency-free mirror: the fingerprints are hashed in their actual
   array order. Verified: swapping two rounds changes `artifact_version`;
   unrelated JSON formatting does not; round ids and per-round fingerprints
   are completely unaffected by this change (see the real-artifact
   regeneration below).
3. **Validator strengthened** to check the full contract: exact key sets,
   `schema_version`/`mode`, valid non-empty versions, the three-way
   version-agreement rule above, valid ISO `generated_at`/`start_date`,
   `start_date == schedule[0].date`, contiguous/unique dates, unique round
   ids, `conn-<10 hex>`/`rfp-<16 hex>` format checks, forbidden-substring/
   phrase scans, and a controlled `ConnectionDailyManifestError` (never an
   uncaught `ValueError`) on malformed date strings.
4. **`generated_at` is now an explicit required input**, never
   `datetime.now(UTC)` — `build_connection_daily_manifest`/
   `extend_connection_daily_manifest` take it as a caller-supplied argument,
   and the new `--generated-at` CLI flag is required on both commands. This
   makes both operations byte-for-byte reproducible as COMPLETE artifacts
   (not just their `schedule` array) given identical arguments — verified
   directly by running each twice and comparing full dicts.
5. **Extension-boundary adjacency quality.** The scheduler's lookahead-swap
   pass only ever looked within the newly-shuffled batch; the boundary round
   (the manifest's prior last entry) was never considered. Fixed:
   `_quality_scheduled_order` accepts the prior last round as adjacency
   context during extension, so the first appended date also avoids
   repeating its endpoint/performer when a non-conflicting candidate exists
   — a forced conflict (none available) is left in place, deterministically,
   and shows up honestly in `schedule_diagnostics`.
6. **Local calendar day, not UTC.** `new Date().toISOString().slice(0,10)`
   reported the UTC calendar date; Connection of the Day now rolls over at
   the player's own LOCAL midnight (`apps/web/src/game/localDate.ts::
   localIsoDate`, using local-time getters only). This is a real product
   decision, documented in `connection-daily-manifest-v1.md`: players in
   different time zones enter the next scheduled puzzle at their own local
   midnight, not simultaneously — the committed schedule itself is unchanged.
7. **Gated `?date=` override.** Previously honored unconditionally in every
   build, including production. `apps/web/src/game/dateOverride.ts::
   isDateOverrideAllowed()` now allows it only under `astro dev`
   (`import.meta.env.DEV`) or when a test harness has explicitly injected
   `window.__NP_ALLOW_DATE_OVERRIDE__ = true` (Playwright, via
   `page.addInitScript`) — a real production build (`astro build` +
   `wrangler deploy`) never has either set, so `?date=` is silently ignored
   there. No secret involved; the manifest itself stays public.
8. **Full artifact verification in the browser, with runtime guards.**
   `dailyManifest.ts::resolveDailyRound` now takes the COMPLETE fetched
   `GameRounds` artifact (not just `.rounds`) and checks, with lightweight
   runtime type guards rather than trusted TypeScript assertions: both
   schema versions are supported (`unsupported-manifest`); `manifest.mode`
   is exactly `connection_guesser_one_hop` (`wrong-mode`); all three
   versions agree with the fetched pool's provenance (`version-mismatch`);
   the date is scheduled (`not-scheduled`); the round exists
   (`missing-round`); the round is actually `real-records`/`one_hop`
   (`ineligible-round` — catches a manifest somehow pointing at a two-hop or
   synthetic round); and the fingerprint matches (`fingerprint-mismatch`).
   Each reason is independently tested
   (`apps/web/tests/game-dailyresolver.spec.ts`, 14 pure-node tests); the UI
   collapses several into one shared integrity message but the resolver
   never does.
9. **Catalog audit scope corrected.** The committed audit was already
   narrowly an inclusion-only ledger in practice (excluded masters never got
   a row), but its generic filename invited reading it as a full
   accept/reject ledger. Renamed
   `docs/data/studio-album-catalog-audit-v1.json` →
   `studio-album-catalog-inclusion-audit-v1.json`; its own `note` field and
   `docs/STUDIO_ALBUM_CATALOG_AUDIT.md`'s pointer now say explicitly that
   this is an inclusion ledger, not an accept-and-reject one, and link
   directly to `data/albums/studio-album-master-exclusions-v1.json` for
   excluded-master decisions and their reasoning.
10. **Production catalog command fully fail-closed on snapshot metadata.**
    `build-public-album-catalog` required its policy *paths* but tolerated
    *missing* `snapshot_date`/identity fields inside them (only a
    *mismatched* one was refused). Fixed: the one-hop manifest, masters
    manifest, release-format-policy, and studio-album-exclusions inputs
    must all carry a valid non-empty `snapshot_date` matching the one-hop
    snapshot; the policy file's `kind` and the exclusions file's `policy`
    identity fields are checked; the exclusions array must be a well-formed
    list (an empty list is valid; a missing/malformed one is not).

**Real artifact regeneration** (same `local/processed/discogs-onehop-v3/
snapshot=20260601` + `apps/web/public/data/catalog/albums.v1.json` +
`local/analysis/album-catalog-integration/artist-family-exclusions-v1.json`
inputs slice 4.5/4.6 used): `build-connection-rounds` reproduced the exact
same 425/885 candidates found, 300/200 selected, identical round order,
identical round ids, and identical per-round content fingerprints — only
`provenance.artifact_version` changed (from the old order-insensitive value
to the new order-sensitive one), confirmed byte-identical across two
independent regeneration runs. The daily manifest was then rebuilt against
the corrected rounds artifact with the SAME `--start-date 2026-08-01
--days 90`: **the resulting `schedule` array is byte-for-byte identical to
the previous one** — every date, round_id, and round_fingerprint unchanged;
only the manifest's top-level `artifact_version` and `generated_at` moved.
No previously assigned date changed.

**Final published versions:** `catalog_version
catalog-v1-20260601-0e7ec70fbb7e` (unchanged), `pool_version
connection-v1-20260601-27f5032ebc16` (unchanged), `artifact_version
connection-artifact-v1-20260601-e27209c5f7a0` (new, order-sensitive
formula), 90 dates `2026-08-01`..`2026-10-29` (unchanged).

Validation: `make check` (612 tests, +34 over slice 5's 578), full
Playwright suite (124/124, +24 over slice 5's 100: 14 pure-node resolver
tests in `game-dailyresolver.spec.ts`, 2 in `game-localdate.spec.ts`, and 8
new browser-level integrity scenarios added to `game-daily.spec.ts`),
`npm run check` (0 errors).

## Addendum: Pi-fleet check-job wiring, found and fixed again (2026-07-22, slice 8)

Finding 8 above fixed the *job body* mismatch (the wrong validator's default
paths pointed at real Connection Guesser data) but left a second, narrower
instance of the same class of bug live: `deploy-rounds-check-job.yml` was
corrected to deploy `connection_rounds_check_job.py`, but
`scripts/enqueue_rounds_check.py` (and its `.sh` wrapper and Makefile target)
were never updated to match — they still enqueued
`rounds_check_job.check_rounds`, a module the corrected playbook never copies
to a worker's `rq_jobs_dir`. Running `make deploy-rounds-check-job` followed
by `make rounds-check-distributed` would have deployed the right job body but
then failed on the worker with a Python import error trying to run the wrong
one. Found during slice 8's audit of the check-job pattern before replicating
it for Record Routes/album-art/daily-manifest/catalog; not previously run for
real (no completed job-result record exists), so this was caught as a static
wiring defect, not from a live failure.

Fixed by renaming every file in the chain to match what it actually deploys,
closing the drift for good rather than patching the mismatch in place:
`deploy-rounds-check-job.yml` → `deploy-connection-rounds-check-job.yml`
(artifact filenames also changed from generic `universe.v1.json`/
`rounds.v1.json` to `connection-universe.v1.json`/`connection-rounds.v1.json`
-- see the filename-collision note below), `run-deploy-rounds-check-job-local.sh`
→ `run-deploy-connection-rounds-check-job-local.sh`, `enqueue_rounds_check.py`
→ `enqueue_connection_rounds_check.py` (`JOB_FUNCTION` corrected to
`connection_rounds_check_job.check_connection_rounds`), `enqueue-rounds-check.sh`
→ `enqueue-connection-rounds-check.sh`, and the Makefile's
`deploy-rounds-check-job`/`rounds-check-distributed` targets to
`deploy-connection-rounds-check-job`/`connection-rounds-check-distributed`.
Added the drift-prevention test that should have existed alongside the
original Finding 8 fix: `test_connection_rounds_check_job_body.py`, loading
the real `infra/ansible/files/connection_rounds_check_job.py` by path and
checking it agrees with `connection_rounds.validate_connection_rounds_artifact`
on the same fixtures (the same pattern `test_cohort_check_job_body.py`/
`test_rounds_check_job_body.py` already used — its absence is exactly how the
first fix's follow-through gap went uncaught).

**Filename-collision risk, closed pre-emptively.** The generic
`universe.v1.json`/`rounds.v1.json` filenames this playbook wrote into the
shared `rq_jobs_dir` would have collided with slice 8's new
`deploy-record-routes-check-job.yml` (a genuinely different contract, same
generic names) the first time both jobs were deployed to the same Pi — one
playbook's artifact copy silently clobbering the other's. Every check-job
playbook added in slice 8 now writes contract-prefixed filenames
(`connection-*`, `routes-*`, or a globally-unique name like `albums.v1.json`)
specifically so multiple check jobs can coexist in one worker's `rq_jobs_dir`.

`infra/ansible/files/rounds_check_job.py` and its existing
`test_rounds_check_job_body.py` are unchanged and untouched by this fix --
that job body still correctly tests the legacy `rounds_failures`/Record-
Routes-precursor contract behind the marked-legacy `build-rounds-from-dump`
CLI command, it is just intentionally never deployed to the live fleet (no
published artifact needs it validated remotely; a one-line comment added to
the file says so, so a future reader doesn't assume a playbook is merely
missing by accident).

## Addendum: the cohort-artifact check job was never staged (2026-07-23, post-#54)

A third instance of the same class of bug this ADR keeps finding in the
Pi-fleet check-job wiring: `scripts/enqueue_cohort_check.py`'s per-worker
fan-out (fixed alongside the other five `enqueue_*_check.py` scripts, see
tracker issue #53) enqueued jobs correctly, but the cohort artifact itself
was never actually placed on any worker's filesystem. Unlike the other five
checks (a fixed, known-in-advance artifact a `deploy-*-check-job.yml`
playbook bundles at deploy time), cohort checks take a per-invocation
`--artifact <path>` with no fixed location to bundle ahead of time --
`deploy-cohort-check-job.yml`'s own header comment says plainly that it
deploys only the job body for exactly this reason. Compounding it,
`infra/ansible/files/cohort_artifact_check_job.py` was the one check-job
body missing the `_resolve()` helper every sibling has (resolves a relative
path against the job body's own directory, i.e. the persistent
`rq_jobs_dir`) -- a bare `Path(artifact_path).read_text()` resolved against
the RQ burst worker's process CWD instead, which is nowhere documented and
not guaranteed to contain anything. The documented example commands in
`docs/OPERATOR_SETUP.md` (coordination-host-relative paths like
`local/analysis/cohorts/<source-id>/connectivity.json`) would have failed
with `FileNotFoundError` on a real, normally-provisioned worker -- caught
by inspection before any real fleet run happened, not from a live failure
(no real check job has run against the fleet yet, per issue #53).

Fixed with a real per-invocation stage -> enqueue -> verify -> cleanup
flow rather than a deploy-time bundle, since the artifact path is only
known at enqueue time: `infra/ansible/playbooks/stage-artifact.yml`
copies the operator's local file to every targeted worker's `rq_jobs_dir`
under a content-addressed filename (`cohort-input-<sha256>.json`,
`any_errors_fatal: true` so one worker's checksum mismatch aborts before
anything is enqueued); `scripts/_artifact_staging.py` wraps that from
Python; `enqueue_cohort_check.py` stages, enqueues, and always removes the
staged copy afterward (`try`/`finally`, `--keep-staged` to retain it for
debugging). `cohort_artifact_check_job.py` gained the missing `_resolve()`
and now returns a structured `{"valid": false, "failures": [...]}` on a
missing or malformed file instead of an uncaught RQ traceback.

`scripts/enqueue_verify_challenge.py` was deliberately left untouched --
it already splits a batch of paths across workers (a genuinely different,
already-correct sharding pattern), unrelated to this bug.
