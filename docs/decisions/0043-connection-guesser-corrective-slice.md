# ADR 0043: Corrective slice for the real Connection Guesser pool (slice 4.5)

- **Status:** Accepted
- **Date:** 2026-07-21
- **Extends:** [ADR 0042](0042-real-connection-guesser-pool.md) without reverting it
- **Relates to:** [ADR 0038](0038-hybrid-album-catalog-assembly.md)

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

## Revisit trigger

If a future catalog expansion or policy change admits new candidates, re-run
the audit in `docs/STUDIO_ALBUM_CATALOG_AUDIT.md` — the deny-list categories
it covers are specifically the ones with no structured Discogs signal, so a
new candidate can silently reintroduce the same class of leak without a human
pass. If Record Routes (slice 6) ever needs to publish its artifact at the
same file names this ADR's Connection Guesser pool uses, stop and resolve the
collision explicitly rather than letting the two contracts overwrite each
other on disk.
