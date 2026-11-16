# Campaign "Atlas" — status

The working status page for the campaign decided in
[ADR 0072](decisions/0072-campaign-atlas-lineage-approved-pool-collections.md).
[ROADMAP.md](ROADMAP.md) stays the canonical "where we are / what's next" page and points here
for the detail. Update the Status column in the same pull request that ships a work package.

**Reading rule:** anything not marked `done` below does not exist yet. Do not describe it as
shipped anywhere else.

## Aim

Collection-seeded catalog growth on a lineage-checked pipeline, presented record-first:

- each expansion round is seeded by owner-chosen musical themes;
- the reviewed evidence for those albums becomes a published **Collection** (the public name
  for a real cohort);
- artifacts declare their inputs and CI checks them;
- the home fleet does sharded scoring and a second-node re-check of published hops;
- the site reorganises around records, players and collections, with games as entry points.

Near-term milestone: about 500 published studio albums, reached in four more rounds, each gated
on the previous one's measurements.

## Owner decisions (2026-11-15)

| Decision | Answer |
|---|---|
| Public name for real cohorts | Collections (code keeps `cohort`) |
| Round 2 themes | Acid jazz / Jamiroquai orbit, desert rock, jazz fusion — names approve no album |
| Two albums added by Round 1's `--editorial-albums` fallback | Approved retroactively |
| Six Round 1 graph-rich picks | Awaiting a one-line owner confirmation (work package F2) |
| Branch protection on `main` | Yes, required checks |
| ADR 0018 and figures already in public docs | Grandfathered; new measurements stay local |
| Hardware model of the x86 worker | Owner states it differs from `docs/HARDWARE.md`; verify before changing docs (I0) |
| Fleet actions during execution | Documented `make` targets and job submissions may run unattended; Swarm membership, mounts, networking, installs and service restarts outside the runbook still need explicit approval |

## Work packages

Status values: `todo`, `in progress`, `done`, `deferred`.

### Tranche 1 — safe to rebuild, worth arriving at

No catalog growth, no real collection published, no public data regenerated.

| ID | Deliverable | Depends on | Acceptance | Status |
|---|---|---|---|---|
| F0 | ADR 0072, ADR 0018 addendum, this page, roadmap update | — | merged | done (#260) |
| F1 | Catalog-aware checks for the Guesser, Routes and challenge album sets; registry covers every cited release; `provenance.inputs` and `build_parameters` stamped by builders; generic input-version rule with `live` / `frozen` / `appended` classes; `challenge_version` | F0 | a test that stales each of Guesser, Routes, challenge and registry turns validation red; committed artifacts unchanged and still valid | todo |
| F2 | `data/albums/approved-pool-v1.json` (cumulative, public labels only); two-way catalog check; builder fails on a dropped approved album; `--underrepresented-buckets` shape fix; unread policy keys enforced or removed; rounds 2–5 in the expansion policy | F0 | unapproved album and dropped approved album both fail in tests; committed catalog equals committed pool | todo |
| F3 | `round plan / run / verify` runner: required inputs, inherited parameters, freeze guard, calendar check, restart from a stage, progress output; `EXPANSION_PIPELINE.md` rewritten as the runner's stages | F1, F2 | a synthetic round run twice gives identical content versions; a rebuild with an unfrozen live daily generation is refused | todo |
| F4 | Digest pin for already-played daily dates; payload budgets as a CI test; determinism tests for the catalog and challenge builders | F1 | fail-then-pass shown for each | todo |
| F5 | Required checks on `main`; post-deploy smoke workflow; pin remaining runner images | — | a failing pull request cannot merge; smoke runs after a deploy | in progress |
| F6 | Tests no longer pinned to specific real albums or pairs | — | no test names a real album except through an artifact lookup | todo |
| P1 | Album page as a record: performer roster in static HTML, "where these players lead", evidence readable without JavaScript, guessing as an opt-in | — | a JavaScript-disabled test reads roster and evidence; axe clean in both themes | todo |
| P2 | Site-wide search over records and players with an honest empty state | — | keyboard only: search to Explore centred on the result | todo |
| P3 | Navigation in four groups plus search, homepage led by Explore, mobile menu | — | at 390 px the header is one row; the primary action lands in Explore | todo |
| I0 | Read-only verification of every node's model, memory and disk; correct topology docs | — | public docs consistent with verified facts; instance-specific numbers stay local | todo |
| RP | Local review-packet generator shared by rounds and collections | F2 | opens offline; exports only public fields | todo |
| S1 | Album-projection study (ADR 0072 §6 gate) and a private candidate packet for a first collection | RP | gate result recorded as an ADR 0072 addendum | todo |

### Tranche 2 and later

| ID | Deliverable | Depends on | Status |
|---|---|---|---|
| SS | Theme-seed supply from the full corpus; re-widen the one-hop corpus after approval | F3 | todo |
| S2 | ADR plus `collection-v1` and `playable-cohort-v2` on the performer graph; collection validator group | F1 | todo |
| S3 | Collection page and guided journey; retire the synthetic `/cohorts/` example | S2, P1 | todo |
| S4 | Owner approves and publishes the first real collection | S1–S3 | todo |
| G1a | One evidence-release selection policy for graph, challenge and routes (ships only with a rebuild) | F3 | todo |
| G1b | Align the challenge edge rule with the graph's | F3 | todo |
| G1c | ADR plus graph-derived contributor index; owner reviews the page-set diff | F3 | todo |
| G2 | Record-centred Explore prototype and decision | P1 | todo |
| G3 | Album-level atlas prototype and decision | S1 | todo |
| G4 | Graph format change, only if a size or load-time trigger fires | F1 | todo |
| P4 | Games link onward; player page leads with performance; copy pass | P1 | todo |
| P5 | Self-hosted body and mono faces, motif consistency, structured data, text-only share images, retire `/demo/` | P3 | todo |
| P6 | "How it's built" page from published-artifact facts | F1 | todo |
| I1 | Runtime digest in place of exact-commit matching; skew report; honoured retries; `jobs` commands | I0 | todo |
| I2 | Multi-worker shard dispatch; sharded supply and scoring | I1 | todo |
| I3 | ADR plus platform migration and extension of the sharded hop re-check | I2 | todo |
| I4 | Parse resume and atomic part writes | — | todo |
| R2 | Round 2, 217 → about 277 albums | F1–F4, RP, SS, G1a, I0 | todo |
| R3–R5 | Rounds to about 500, each gated on the previous round's measurements | R2 | todo |

## Research questions that must earn implementation

| ID | Question | Decision recorded in |
|---|---|---|
| E1 | Do album-projection clusters read as musical scenes? | ADR 0072 addendum |
| E2 | Is an album-level atlas legible and useful? | new ADR if adopted |
| E3 | Does a record-centred Explore beat the artist-centred one? | ADR 0052 addendum |
| E4 | Do different prominence weights surface more interesting players? | ADR 0070 addendum |
| E5 | Is repeated collaboration worth showing as an evidence fact? | work-package notes |
| E6 | Is a time-filtered Explore legible? | work-package notes |
| E7 | What do real low-end devices cost? Method public, numbers local | `SITE_REPROFILE_METHOD.md` |

Not reopened without their own stated triggers: betweenness promotion (ADR 0063), community
detection on the performer graph and tiles (ADR 0070).

## Standing rules for this campaign

- No album, collection or pair is published without an explicit owner action on record.
- The approved pool and every public artifact carry public labels only.
- Public data changes only through the round runner, operator-run, in one pull request per round.
- Rolling back a round never reverts the daily manifest past a cutover that has already passed
  (ADR 0072 §4).
- Raspberry Pi jobs stay bounded; no raw dump parsing on a Pi.
- No new service, database, queue, graph engine or parser without a measurement and an ADR.
- No Discogs image bytes are downloaded, stored or rehosted.
- New timing and memory measurements stay in `local/benchmarks/` (ADR 0018).

## Log

- 2026-11-15 — Campaign planned and approved; ADR 0072 written; F0 opened.
