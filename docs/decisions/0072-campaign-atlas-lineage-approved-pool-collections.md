# ADR 0072: Campaign "Atlas" — lineage by content version, a checked approval boundary, and Collections over the catalog

- **Status:** Accepted (direction and contracts-to-build; no contract in this ADR is implemented
  by the PR that adds it — see "What this ADR does not claim")
- **Date:** 2026-11-15
- **Extends:** [ADR 0041](0041-frozen-append-only-daily-manifest.md),
  [ADR 0043](0043-connection-guesser-corrective-slice.md),
  [ADR 0048](0048-contributor-index-and-pages.md),
  [ADR 0066](0066-phase7-daily-manifest-schedule-rewrite-exception.md),
  [ADR 0069](0069-public-universe-model-and-expansion-policy.md),
  [ADR 0070](0070-community-detection-and-explore-scaling-measurement.md) without modifying
  any of them
- **Will be followed by separate ADRs for:** the Collection and `playable-cohort-v2` contracts
  (amending [ADR 0028](0028-curated-cohort-source-ingestion.md) and
  [ADR 0031](0031-human-reviewed-cohort-promotion.md)), a graph-derived contributor index
  (per ADR 0048's own revisit trigger), and migrating the sharded hop re-check onto the
  capability platform (superseding [ADR 0062](0062-pi-fleet-verify-challenge-migration-deferred.md))
- **Status page:** [`docs/CAMPAIGN.md`](../CAMPAIGN.md)

## Context

A planning pass on 2026-11-15 reconstructed the project from the repository and its committed
artifacts after a development hiatus. It found a credible static product on a real 217-album
catalog, and a production process that depends on an operator hand-running roughly eleven
build commands in the right order with the right flags.

Expansion Round 1 (`docs/EXPANSION_PIPELINE.md`, "Round 1") recorded what that costs: a first
attempt that delivered 6 albums against a target of 30, a Record Routes pool silently halved by
a code default, 94 dropped contributor pages, 90 daily dates that stopped resolving, and albums
published through a default fallback. Read together, those incidents have one root cause with
three faces:

1. **No checked lineage.** `validate-public-artifacts` validates the Connection Guesser and
   Record Routes pools without the catalog, so a stale pool passes. A challenge-only rebuild
   leaves the registry, contributor index and hop distances stale and green. No committed
   artifact records the parameters it was built with.
2. **No checked approval boundary.** Nothing verifies that the catalog builder consumed exactly
   the albums the owner approved. Eight Round 1 albums (two added by the `--editorial-albums`
   fallback, six from a local graph-rich selection) have no committed approval record.
3. **No orchestrator.** Ordering constraints that matter — freeze the live daily generation
   before rebuilding the pool it points at, carry forward the previous challenge, inherit the
   previous round's targets — live in prose.

The same pass measured the committed graph and found that the three programmes the roadmap
treats separately (catalog expansion, cohorts, Explore) are one activity: choosing which
musical neighbourhoods to make real. Today's catalog already contains one dense, real
neighbourhood (Los Angeles studio players, roughly 1975–84) and several the owner wants that
are thin or absent.

## Decision

### 1. Lineage is declared in content versions, not file hashes

Every public artifact is re-formatted by Prettier after its builder writes it
(`docs/OPERATOR_SETUP.md`, "After any artifact build"), so a hash of file bytes is stale the
moment the artifact is committed. The repository already has the right primitive:
`networked_players_contracts.canonical.content_hash`, which is formatting-independent, and
per-artifact content versions built on it.

- Each builder stamps `provenance.inputs` — a map from upstream **artifact** name to that
  artifact's content version — and `build_parameters`. `challenge.v3` gains a
  `challenge_version`.
- `validate-public-artifacts` gains one generic rule: every declared input version must equal
  the current upstream artifact's version.
- Artifacts are classed `live`, `frozen` (daily generation files, which deliberately carry
  catalog versions that no longer exist) or `appended` (the daily manifest, which is extended
  outside any rebuild). Only `live` artifacts participate in the generic rule.
- Semantic checks that a version cannot express are added alongside: the Guesser, Routes and
  challenge album sets must equal the catalog's; the evidence registry must contain every
  release id cited by the challenge, routes and graph.
- Inputs that are not committed artifacts (corpus roots, policy indexes) are recorded by name,
  with a manifest digest where a manifest exists. They are recorded, not CI-checkable.

**Stated limit.** The artifacts committed today cannot be given lineage retroactively: their
parameters and non-committed inputs were never recorded. They receive the semantic checks
immediately and real lineage at their next rebuild.

*Alternative rejected:* a separate ledger file of sha256 file hashes. It fails on Prettier, it
would duplicate version fields the artifacts already carry, and a ledger generated for
artifacts whose build was never recorded would only bless their current state.

### 2. A committed, cumulative approved pool with a two-way check

`data/albums/approved-pool-v1.json` lists every album approved for publication: `master_id`,
the round that added it, and the public `selection_source` label (ADR 0069's enum) — nothing
else.

- **Public labels only.** No scores, no rejected or deferred candidates, no reviewer identity,
  and no lane detail finer than ADR 0069 §2's public vocabulary. The public record still never
  implies personal-collection sourcing.
- **Two-way.** The catalog's master set must equal the pool's. The catalog builder fails when
  an approved album is dropped (today an ineligible pre-resolved album moves silently to
  `pre_resolved_missed`) and when any album outside the pool appears.
- When a pool is supplied, shortlist auto-fill and the `--editorial-albums` default fallback
  are disabled. The `top-albums` matching lane itself is unchanged.
- The pool is seeded with the 217 albums published today. The owner approved the two fallback
  albums retroactively on 2026-11-15; the six graph-rich picks are recorded once the owner
  confirms them.

Generated rankings and review packets never authorise publication. The pool does.

### 3. A thin, operator-run round runner

`networked-players-catalog round <plan|run|verify>` sequences the existing builders. It is a
new module; `cli.py` is not restructured.

- Required explicit inputs. Parameters are inherited from the previous artifacts'
  `build_parameters`, not from code defaults.
- Hard preconditions: the live daily generation is frozen before the Guesser pool is rebuilt;
  the previous challenge is carried forward; the previous Routes universe is supplied;
  formatting respects `apps/web/.prettierignore`.
- Restart from a named stage, with per-stage progress output.
- **No content-addressed stage cache in the first version.** Some inputs are private and the
  daily-manifest stage is calendar-coupled; a cache is revisited only after a real round has
  run through the runner.
- The runner never runs in CI: the album-art stage needs an API token and a private cache.

### 4. The daily manifest is calendar-coupled and is handled as such

`migrate_connection_daily_manifest_generation` drops entries on or after a cutover date that
must lead `--generated-at` by a minimum number of days. Two consequences are recorded here
because they are easy to get wrong:

- A round whose pull request merges after its cutover date rewrites dates players have already
  seen. A CI check must fail a round PR whose cutover is not still in the future.
- **Rollback of a round is not a plain `git revert`.** Reverting the manifest after its cutover
  has passed violates ADR 0041/0066 in the other direction. The rollback procedure reverts the
  round's artifacts except the daily manifest and generation files, keeps the new generation
  frozen in place, and schedules forward.

Entries for dates already played are additionally pinned by a committed digest so that a
later edit cannot swap a played date to another valid round of the same generation.

### 5. Collections are views over the published catalog

The public name for a real, reviewed cohort is **Collection**. Code and contracts keep
`cohort`. Public copy must not suggest the owner's private record collection.

- A Collection's albums are catalog albums. A theme that needs albums the catalog lacks becomes
  an expansion seed, which is how rounds are chosen from now on.
- Existing cohort pairs are artist-to-artist paths over the one-hop corpus (ADR 0030) and the
  v1 playable contract requires a third-party source URL (ADR 0028). A Collection over the
  performer-only graph (ADR 0068) is a different object, so it gets its own contracts
  (`collection-v1`, `playable-cohort-v2`) under a follow-up ADR. ADR 0031's human-approval
  boundary is kept and extended to collections and journeys; nothing is promoted automatically.
- Collections are original thematic concepts over CC0 catalogue facts. The existing local run
  built from a third-party list remains a pipeline rehearsal and is not promoted.
- Algorithmic neighbourhoods are a separate, computed feature and are never labelled as
  Collections.

### 6. Album-projection clustering is a new measurement, with a gate

ADR 0070 denied Leiden on the performer graph: album anchors never share a community because
they are never adjacent. The album projection (records as nodes, weighted by shared performers)
has not been measured. It is small enough to run locally.

Gate, all required: the largest cluster holds at most 25 % of albums; at least 40 % of albums
fall in clusters of four or more records spanning three or more distinct artists; modularity is
clearly above a degree-preserving null model; the owner finds at least 7 of 10 sampled clusters
musically legible. A pass makes clusters *candidate* collections for human review. A fail is
recorded as an addendum here and collections stay seed-driven. ADR 0070's denials for the
performer graph, ADR 0063's for betweenness, and ADR 0070's final finding on tiles all stand.

### 7. Expansion rounds are theme-seeded

Each round's spec names its themes and lane quotas (theme / graph value / coverage repair).
Round 2's themes, chosen by the owner on 2026-11-15, are the acid-jazz and Jamiroquai orbit,
desert rock, and jazz fusion. Naming a theme approves no album.

Themes outside the current one-hop corpus must be supplied from the full corpus; the one-hop
corpus is re-widened only for approved albums.

## What this ADR does not claim

No lineage field, approved pool, runner, Collection contract or cluster study exists in the
repository as of this ADR. It records decisions and the order of work. `docs/CAMPAIGN.md`
tracks which pieces have shipped; treat anything not marked done there as not existing.

## Consequences

- The next public-artifact rebuild is larger than a normal round: it is the first one to carry
  lineage and build parameters.
- Unifying evidence-release selection across the graph, challenge and routes changes round
  content, so it can only ship together with a rebuild behind a frozen daily generation.
- A graph-derived contributor index would change the published page set substantially; it needs
  its own ADR and an owner review of the page diff. ADR 0048's guarantee is unchanged: documented
  path endpoints stay documented. No broader URL-permanence promise is introduced.
- Public claims about fleet verification describe a second-node re-check by a mirrored
  implementation, not an independent proof.

## Validation

Each work package in `docs/CAMPAIGN.md` carries its own acceptance test. For the contracts in
this ADR specifically: a test that stales each of the Guesser pool, Routes pool, challenge and
registry must turn validation red; the catalog builder must reject both an unapproved album and
a dropped approved album; a rebuild attempted with an unfrozen live daily generation must be
refused; a synthetic end-to-end round run twice must produce identical content versions.

## Revisit trigger

- If stamping `provenance.inputs` proves unable to express a dependency that has caused a real
  incident, revisit a separate ledger — based on `content_hash`, never on file bytes.
- If a compelling theme's albums fail studio-album eligibility as a class (soundtracks are the
  likely case), design an evidence-only record tier under its own ADR rather than relaxing
  ADR 0069's eligibility.
- After the first round has run through the runner end to end, revisit a stage cache with the
  measured cost of the stages it would skip.

## Addendum (2026-11-18): the album-projection gate (§6) passes

The study module (`networked-players-research`, album projection; PR #269) was run on the
217-album catalog at its defaults (at least two shared performers, same-artist pairs excluded,
Leiden resolution 2, ten seeds, twenty null samples). The measured criteria all pass:

| Criterion | Threshold | Measured |
| --- | --- | --- |
| Largest cluster share | ≤ 25 % | 6.9 % |
| Coverage (albums in clusters of ≥ 4 records and ≥ 3 artists) | ≥ 40 % | 50.2 % |
| Modularity above a degree-preserving null | clearly above (z ≥ 3) | z = 4.2 |
| Modularity above a bipartite (performer-preserving) null | clearly above (z ≥ 3) | z = 3.6 |
| Owner legibility review | ≥ 7 of 10 clusters | **approved by the owner, 2026-11-18** |

Twelve clusters qualify. Readable examples include London sessions around the former Beatles,
the Los Angeles singer-songwriter section, Steely Dan and Toto's Los Angeles studio players,
San Francisco and Crosby, Stills, Nash & Young, Quincy Jones's productions, the Heartbreakers'
orbit and 1960s New York jazz.

Consequences:

- Clusters are now **candidate** Collections. Each still needs its own title, introduction,
  journey and owner approval through `promote-collection` (ADR 0074). Passing the gate approves
  no Collection and publishes nothing.
- Not every cluster is a scene. Two of the twelve are held together by orchestral string
  sections rather than a shared band or studio; they stay candidates only if a human finds a
  musical story in them.
- The result is stable only at the default threshold. At three or more shared performers,
  coverage falls to 24 %, below the gate, so the threshold is part of the result and is
  recorded with it.
- The study is re-run after each expansion round. A round that drops coverage below the gate
  returns Collections to seed-driven selection until the gate passes again.
- ADR 0070's denials (Leiden on the performer graph, tiles) and ADR 0063's (betweenness) still
  stand. This addendum concerns only the album projection.
