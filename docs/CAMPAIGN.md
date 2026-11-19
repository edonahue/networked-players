# Campaign "Atlas" — status

The working status page for the campaign decided in
[ADR 0072](decisions/0072-campaign-atlas-lineage-approved-pool-collections.md).
[ROADMAP.md](ROADMAP.md) stays the canonical "where we are / what's next" page and points here
for the detail. Update the Status column in the same pull request that ships a work package.

**Reading rule:** anything not marked `done` below does not exist yet. Do not describe it as
shipped anywhere else.

> Round 2 execution plan: [docs/ROUND_2_PLAN.md](ROUND_2_PLAN.md).

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
| Six Round 1 graph-rich picks | Confirmed by the owner 2026-11-16; recorded in the approved pool |
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
| F1 | Catalog-aware checks for the Guesser, Routes and challenge album sets; registry covers every cited release; `provenance.inputs` and `build_parameters` stamped by builders; generic input-version rule with `live` / `frozen` / `appended` classes; `challenge_version` | F0 | a test that stales each of Guesser, Routes, challenge and registry turns validation red; committed artifacts unchanged and still valid | done (#262 cross-checks, #267 declared inputs, `challenge_version`, generic rule). Committed artifacts declare no inputs until their next rebuild; `validate-public-artifacts` lists them under `lineage.undeclared_inputs` |
| F2 | `data/albums/approved-pool-v1.json` (cumulative, public labels only); two-way catalog check; builder fails on a dropped approved album; `--underrepresented-buckets` shape fix; unread policy keys enforced or removed; rounds 2–5 in the expansion policy | F0 | unapproved album and dropped approved album both fail in tests; committed catalog equals committed pool | done (#264) |
| F3 | `round plan / run / verify` runner: required inputs, inherited parameters, freeze guard, calendar check, restart from a stage, progress output; `EXPANSION_PIPELINE.md` rewritten as the runner's stages | F1, F2 | a synthetic round run twice gives identical content versions; a rebuild with an unfrozen live daily generation is refused | done (#272). Exercised on a synthetic round only: the album-art and formatting stages ran as stand-ins, and no real round has been run through it |
| F4 | Digest pin for already-played daily dates; payload budgets as a CI test; determinism tests for the catalog and challenge builders | F1 | fail-then-pass shown for each | done (#271) |
| F5 | Required checks on `main`; post-deploy smoke workflow; pin remaining runner images | — | a failing pull request cannot merge; smoke runs after a deploy | done (#261); required checks `python` and `web` enabled on `main` 2026-11-16 |
| F6 | Tests no longer pinned to specific real albums or pairs | — | no test names a real album except through an artifact lookup | in progress |
| P1 | Album page as a record: performer roster in static HTML, "where these players lead", evidence readable without JavaScript, guessing as an opt-in | — | a JavaScript-disabled test reads roster and evidence; axe clean in both themes | done (#263) |
| P2 | Site-wide search over records and players with an honest empty state | — | keyboard only: search to Explore centred on the result | done (#266, follow-up fixes in #268) |
| P3 | Navigation in four groups plus search, homepage led by Explore, mobile menu | — | at 390 px the header is one row; the primary action lands in Explore | done (#266 navigation, #268 homepage) |
| I0 | Read-only verification of every node's model, memory and disk; correct topology docs | — | public docs consistent with verified facts; instance-specific numbers stay local | in progress — partial: health check ran; the x86 worker failed its disk floor before reporting hardware facts, so its model is still unverified |
| RP | Local review-packet generator shared by rounds and collections | F2 | opens offline; exports only public fields | done (#273) |
| S1 | Album-projection study (ADR 0072 §6 gate) and a private candidate packet for a first collection | RP | gate result recorded as an ADR 0072 addendum | Done: gate passed, owner approved legibility 2026-11-18 (ADR 0072 addendum); clusters are candidate Collections only |

### Tranche 2 and later

| ID | Deliverable | Depends on | Status |
|---|---|---|---|
| SS | Theme-seed supply from the full corpus; re-widen the one-hop corpus after approval | F3 | Done (#284); synthetic-proven only, real Round 2 seed spec still to write |
| S2 | ADR plus `collection-v1` and `playable-cohort-v2` on the performer graph; collection validator group | F1 | todo |
| S3 | Collection page and guided journey; retire the synthetic `/cohorts/` example | S2, P1 | Done (#285); renders nothing until a Collection is promoted |
| S4 | Owner approves and publishes the first real collection | S1–S3 | todo |
| G1a | One evidence-release selection policy for graph, challenge and routes (ships only with a rebuild) | F3 | todo |
| G1b | Align the challenge edge rule with the graph's | F3 | Done (#288). Challenge path search now restricted to seed-touching edges via one shared scope predicate; carry-forward re-searched and counted; opt-in `check-challenge-hops-in-graph` (runner enables it for new rounds). Becomes mandatory, and the committed challenge.v3's 119 out-of-scope hops go away, only with the Round 2 rebuild (see docs/EXPANSION_PIPELINE.md) |
| G1c | ADR plus graph-derived contributor index; owner reviews the page-set diff | F3 | todo |
| G2 | Record-centred Explore prototype and decision | P1 | Decided 2026-11-18: the artist view stays the default; the record-centred prototype stays unlinked at `?mode=record` for later comparison (#290). |
| G3 | Album-level atlas prototype and decision | S1 | todo |
| G4 | Graph format change, only if a size or load-time trigger fires | F1 | todo |
| P4 | Games link onward; player page leads with performance; copy pass | P1 | todo |
| P5 | Self-hosted body and mono faces, motif consistency, structured data, text-only share images, retire `/demo/` | P3 | P5a done (#283): fonts, JSON-LD, canonical, sitemap, demo retired; motif consistency (P5b: liner-note paper panel + groove rules on record/player/Explore/directories/collections, 45 inline styles replaced by utility classes and guarded by tests/no-inline-styles.spec.ts) done; text-only share images done (P5c: build-time satori + resvg PNG per record, reused for `/explore/<id>/`; player pages keep the site-wide image, since 639 more cards would add ~30 MB to dist) |
| P6 | "How it's built" page from published-artifact facts | F1 | todo |
| I1 | Runtime digest in place of exact-commit matching; skew report; honoured retries; `jobs` commands | I0 | Done and rolled out to the real fleet 2026-11-18 (ADR 0073 Accepted) |
| I2 | Multi-worker shard dispatch; sharded supply and scoring | I1 | Done in code (#289): select_workers, shard plan/gather, sharded scoring byte-identical to single-node; worker workload not registered and nothing deployed |
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
- 2026-11-16 — F0, F5, F1 (cross-checks), F2 and P1 merged. `main` now requires the `python`
  and `web` checks. The post-deploy smoke check passed on its first runs. Note for the fleet:
  the default artifact check now passes the catalog as a third input for the Guesser and Routes
  pools, so workers need the platform runtime redeployed and contracts reinstalled before that
  check is run again; the x86 worker's root disk must be brought back above its floor first.
- 2026-11-16 (later) — F1 completed (#267), navigation, site-wide search and the homepage
  shipped (#266, #268), and the album-projection study merged (#269). The study's numeric
  criteria hold at its default parameters and fail when a link requires three or more shared
  performers; the legibility criterion is the owner's and is still open, so no gate decision
  is recorded yet. Before a lineage-stamped rebuild is validated on the fleet, contracts must
  be reinstalled on every worker (`data/contracts/artifact-lineage-v1.md`, "Fleet ordering");
  recording the contracts version in the worker's validation report is added to I1's scope.
- 2026-11-17 — Round runner (#272), review-packet generator (#273) and the played-date pin,
  payload budgets and determinism tests (#271) merged. The runner takes the pin and budgets as
  explicit round inputs. Its first real use will be Round 2; until then it is proven only on
  synthetic fixtures. The old hand-run runbook it replaces omitted `--albums` on the challenge
  build and had no daily-manifest freeze or migrate step.
- 2026-11-17 (later) — F6 merged (#275); all tranche 1 code is on `main`. Report:
  [ATLAS_TRANCHE_1_REPORT.md](ATLAS_TRANCHE_1_REPORT.md). Tranche 1 stays open on two owner
  items (cluster legibility, the x86 worker's disk). The owner gave a standing go-ahead for
  tranche 2 work that publishes nothing and deploys nothing; P4 and I4 started.
- 2026-11-17 (later still) — P4 (#278, #279), I4 (#277), I1 (#280) and S2 (#281) merged, each
  after an independent review whose findings were fixed before merge. Nothing was deployed and
  no real data was rebuilt. Fleet rollout of I1 is an operator step listed in
  `docs/OPERATOR_SETUP.md`; it waits on the x86 worker's disk. Fixed an intermittent Record
  Routes test that clicked before its round had loaded.
