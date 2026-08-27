# Next-path decision brief (originally post-Phase-3 cleanup, 2026-08-04; last corrected 2026-08-17)

A factual decision-support document, not a plan for a next phase. The
repository is now internally coherent (see `docs/PHASE3_REPORT.md`'s
follow-up section and ADR 0056) — this names the strongest real next
directions the current, clean architecture supports, with the evidence
behind each, and does not select one. None of the items below were
started as of this document's own most recent prior edit (2026-08-09).

**Correction (2026-08-16):** this document's title/date was never
updated as its own body accumulated post-Phase-3 material through
2026-08-09, and it was never updated at all for Phase 4 (ADR 0058 —
album-credit membership, evidence-release registry v2, record-to-record
pathfinding) or Phase 5 (ADR 0059 — recommended-route ranking, canonical
names, evidence-release registry v2 extended with caveat flags,
Connect Two Records' shareable URL state/Swap/accessible combobox, and
the codebase's first Web Worker), both of which fully shipped and are
live in production (Phase 5: PRs #112–121, 2026-08-09 through
2026-08-15). None of the five candidate directions below were touched by
either phase. A second correction, to the "Most-connected-contributors
view" entry below, fixes a real overstatement about what
`contributor_network` actually consumes — see that entry.

**Phase 6 close (2026-08-17):** this document is what Phase 6 was
scoped from. It shipped: (1) a cross-link audit closing real gaps
between album pages, contributor pages, the Network Explorer, and
Connect Two Records; (2) `interesting_next_step` (ADR 0060), a real,
measured, anti-hub-bias discovery signal on the contributor index,
surfaced on `/contributors/` and in the Explorer; and (3)
`research-scope-tier` tooling plus ADR 0061, which deliberately defers
(rather than answers) the "Core-discography vs. exploration-neighborhood
corpus split" entry below. Full detail in `docs/PHASE6_REPORT.md`
(PRs #122–134). The "Most-connected-contributors view" entry below is
now partially addressed — see the note added there — and every other
entry in this document is untouched by Phase 6 and remains open.

## Research quality / data model

**Core-discography vs. exploration-neighborhood corpus split.** Real,
measured evidence (see `local/research/jamiroquai/scope-tier-analysis.md`,
gitignored) found a dramatic, real tradeoff at different topic-corpus
scopes: role-classification coverage rises from 35.6% (the current full
1-hop corpus) to 93.5% (a studio-albums-only scope), while the co-credit
graph inverts from a real, richly-connected 13-component network to a
bare star graph with **zero** contributor-to-contributor edges at every
tighter tier. Neither scope alone serves both "clean personnel/role
analysis" and "who bridges to the wider world" — the current single Topic
Corpus contract asks one artifact to do both jobs.
- *User value*: cleaner, more trustworthy personnel/role findings for a
  subject's own discography, without losing the wider-network exploration
  the current corpus already does well.
- *Backend leverage*: `corpus.py`'s existing artist-seeded expansion
  already computes most of what a tighter tier needs (it's a filter on
  what's already retained, not new ingestion).
- *Biggest uncertainty*: whether "two corpora" is the right shape, or a
  single corpus with a scope-tier field per analysis is cleaner —
  **deliberately deferred, see ADR 0061**: every current consumer of
  scope-sensitive analysis is research-lane-only (ADR 0054), so no
  public-facing feature is blocked by leaving the contract as-is; revisit
  when a real promotion candidate or a caching need actually requires it.
- *Prerequisite measurement*: done for Jamiroquai (this cleanup pass) and
  four more real, structurally different catalog artists (Wu-Tang Clan,
  D'Angelo, Nirvana, Miles Davis — 2026-08-09, see the summary paragraph
  below); real evidence across five artists now supports the tradeoff
  being general, not Jamiroquai-specific — still not yet a decision on
  contract shape.
- *What not to build yet*: don't touch the Topic Corpus contract itself
  without a real design pass — this cleanup pass deliberately only
  measured, per its own scope boundary.
- *2026-08-16 update*: the hand-run measurement above is now reusable,
  tested tooling (`networked-players-research research-scope-tier`,
  `packages/research/src/networked_players_research/scope_tier.py`) —
  tiers A/B/C (full corpus, direct-billed, main-release-only) over any
  already-built topic corpus, reusing `graph.py`'s own production
  `credit_edges_sql`. Running it against the real Jamiroquai corpus
  reproduces Tier A exactly (656 nodes/680 edges/13 components/617
  largest) but finds MORE graph structure at Tiers B/C than the original
  hand script recorded (292 vs. 291 nodes at B; 149 vs. 55 at C) — the
  original script under-counted edges, most likely by not exercising the
  full `credit_edges_sql` rule set; this tool supersedes those numbers as
  the more complete, tested measurement, while confirming the same
  qualitative star/tree-topology finding at both narrowed tiers. Tier D
  ("studio albums only") is NOT reproduced by this tool — it was a
  hand-curated release-title list, not a data-derived filter, and stays
  a manual follow-up. This is measurement tooling, not a design change —
  see ADR 0061 for the deliberate decision to defer the contract
  question itself.

**Multi-artist follow-up measurement (2026-08-09).** Extended the
Jamiroquai scope-tier measurement above to four more real catalog
artists — Wu-Tang Clan, D'Angelo, Nirvana, and Miles Davis, chosen for
structural contrast (hip-hop, R&B/neo-soul, a short 3-album discography,
and a 40+-year session-heavy jazz catalog respectively). Full real results
and analysis in `local/research/{wu-tang-clan,d-angelo,nirvana,miles-davis}/scope-tier-analysis.md`
(gitignored). Two real findings not visible from Jamiroquai alone: (1)
the star/tree graph-structure finding (edges = nodes − 1, one component)
replicated cleanly across all five artists at every narrowed tier — the
single most consistent finding across this whole measurement; (2)
"narrower scope always improves role coverage" does **not** hold
universally — Jamiroquai and Wu-Tang Clan both rose monotonically, but
D'Angelo and Nirvana each show a real, measured *dip* at an intermediate
tier before recovering at the narrowest one, and Miles Davis peaks at
Tier B rather than Tier D. Role-coverage *ceilings* also vary
meaningfully by artist even at the narrowest tier (70.3% for Wu-Tang Clan
vs. 93.5% for Jamiroquai), suggesting genre/production style shapes
`role_taxonomy.py` coverage independently of corpus breadth — a real,
new, still-unconfirmed hypothesis for that section's own "biggest
uncertainty." No design decision was made from any of this; it remains
evidence, not a commitment to a specific corpus-tier or taxonomy design.

**`role_taxonomy.py` coverage.** Real, current gap: even after this
pass's fix, the majority of classified role components at Jamiroquai's
corpus scale are still `unknown`. Most remaining frequent unknown strings
(`Compiled By`, `Commissioned By`, `Featuring`, etc.) can't be safely
added without also touching `graph.py`'s `_NON_COLLABORATIVE_ROLE_TOKENS`
denylist (a materially bigger, higher-stakes change to the flagship
game's own credit-edge traversal) — a real, structural reason this is
slow going, not neglect.
- *User value*: better role-based findings and displays across the whole
  product, not just research.
- *Backend leverage*: the taxonomy is already the shared source of truth
  for both `eligibility_engineering.py` (Behind the Glass) and the
  contributor index — one fix benefits multiple surfaces at once.
- *Biggest uncertainty*: whether the flagship game's denylist should
  change at all for tokens like `Compiled By`/`Commissioned By`, or
  whether a fourth taxonomy category (e.g. a "curatorial/business" bucket
  distinct from `PACKAGING_BUSINESS`) is the honest fix.
- *Prerequisite measurement*: real token frequency data already exists
  (`classify-roles` diagnostic); a fresh run against a second real topic
  would show whether the same tokens dominate everywhere or if this is
  partly Jamiroquai-specific.
- *What not to build yet*: don't touch `graph.py`'s denylist speculatively.

## Compute/platform

**Full RQ-based Pi fleet maturity.** The Pi fleet is now a real live
capability-platform participant (this cleanup pass's own onboarding
work), but only for validation-class jobs. `scripts/enqueue_verify_challenge.py`
(a genuinely different, sharded-batch pattern) and the legacy
`rounds_check_job.py` remain outside the ADR 0034 path entirely —
deliberately untouched by this pass, real remaining migration surface.
- *User value*: operator confidence, not end-player-visible.
- *Backend leverage*: the capability platform already exists; this is
  wiring more workloads onto it, not new architecture.
- *Biggest uncertainty — resolved (ADR 0062, 2026-08-17)*: confirmed
  `select_worker()`/`RunRequest` support only single-worker dispatch, and
  the existing "fan-out" (`submit_artifact_check.py`) is sequential and
  redundant (same payload to every worker), not parallel and sharded — the
  opposite of `enqueue_verify_challenge.py`'s already-correct pattern.
  Migrating it would mean building a genuinely new primitive for a single
  consumer; deliberately deferred, with real test coverage added for
  `enqueue_verify_challenge.py`'s previously-untested dispatch logic
  instead. `rounds_check_job.py` is fully dead on the fleet (no deploy
  playbook, no live caller) and named as a deletion candidate, not a
  migration one. See ADR 0062 for the full investigation and revisit
  triggers.
- *Prerequisite measurement*: none — this is mostly known, bounded work.
- *What not to build yet*: don't build a new scheduler; reuse what's there.
  Per ADR 0062, don't build the new sharded-dispatch primitive either,
  until a second real consumer justifies it.

**zimaworker1 disk capacity — resolved (ADR 0057, 2026-08-05).** The
100%-full incident named here previously is closed: root-caused as
structural (unbounded dataset replicas, unpruned platform release
bundles, and `/var/log` growth all sharing one small partition with no
governance), not one oversized dataset. Fixed with an explicit,
real-measured DuckDB spill ceiling, release-bundle pruning, a raised
health-check floor, a dispatch preflight, and operator-authorized removal
of the unused full `discogs` replica. Real, confirmed end to end: the
exact `cohort.score` run that originally failed now completes on the same
hardware (free space actually rose after the run, not fell). No hardware
change was needed. One small item remains open, tracked by ADR 0057's own
Revisit trigger, not re-listed here as a next direction: `/var/log`'s
exact spam source still needs root access to confirm (non-privileged
diagnosis narrowed it to routine chatter from unneeded desktop/peripheral
daemons on what should be a headless worker).

## Public product

**Most-connected-contributors view (raw co-credit degree) — resolved
(2026-08-17, ADR 0063).** A real, already-built research-pack addition
(Phase 3 Slice G).
- **Resolved (2026-08-17, ADR 0063):** the entry's own "biggest
  uncertainty" (below) is answered, and the answer closes the entry
  rather than opening more work. Real measurement against the actual
  published production graph (`graph.v2.json`, 36,959 nodes/65,133 real
  edges) found betweenness centrality (`bridge_analysis()`) takes ~21
  minutes at this scale and, more decisively, that the graph has **zero**
  real multi-node "bridge" structure — every one of its 140 cut vertices,
  on removal, only sheds a single isolated leaf node, and the
  highest-degree ones are exactly the most famous artists in the catalog.
  A "bridge contributors" feature built from this data would just be an
  expensive way to re-rank by fame, redundant with the already-published
  `connection_count`. **Not promoted** — a measured "no," not a deferral.
  `community_detection()`/Leiden is explicitly untouched by this finding
  and remains its own, still fully open question. See ADR 0063 for the
  full measurement.
- **Partial update (2026-08-17, Phase 6):** the *user value* named below
  — "a second, simpler, complementary lens on contributor connectivity"
  — shipped, but via a genuinely different mechanism, not this entry's
  `contributor_network`/betweenness path: ADR 0060's `interesting_next_step`
  (PRs 6-09/6-10) is a role-disjointness signal computed entirely from
  the already-published contributor index, no research-lane promotion
  needed. `contributor_network`/`community_detection`/`bridge_analysis`
  themselves remain exactly as described below — real, working,
  research-lane-only, not promoted. This entry stays open for that
  specific promotion question.
- **Correction (2026-08-16):** this entry previously claimed
  `contributor_network` "uses only already-public production `graph.py`
  data — not research-only data" and "already exists and runs against
  production data today." Verified against the actual function signature
  (`packages/research/src/networked_players_research/graph_analysis.py`):
  `contributor_network(corpus_snapshot_root: Path)` reads
  `table=credits/*.parquet` under a research-lane Topic Corpus snapshot,
  not any published `apps/web/public/data/**` artifact. It is real,
  working, tested code — but it is a research-lane consumer, not a
  production one, and promoting it to a public surface is real new work
  (a public artifact + contract + validator), not a data-boundary
  non-issue as this entry previously implied.
- *User value*: a second, simpler, complementary lens on contributor
  connectivity alongside the existing betweenness-based "bridge
  contributors" signal (also research-lane only today, see
  `bridge_analysis` in the same module).
- *Backend leverage*: the algorithm exists and is proven in the research
  lane; the published `contributors/index.v1.json` already carries a
  cheaper substitute (`connection_count`, a raw degree count computed
  from the same two published artifacts the index itself is built from,
  no corpus snapshot needed) that already powers `/contributors/`'s
  "most connected" view today — the real gap is a richer signal beyond
  raw degree, not raw degree itself.
- *Biggest uncertainty — resolved (ADR 0063)*: was "whether this belongs
  on the existing Network Explorer or as a new view." Turned out moot —
  the underlying betweenness signal doesn't hold up on real data (see
  above), so there's no feature left to place. Had it held up, real
  investigation found `/contributors/`'s directory (already list-shaped,
  already sorts by a connectivity metric) would have been the fit, not
  the Explorer (whose entire rendering model is one-center-plus-neighbor-
  circle, structurally wrong for a global ranked list) — recorded here in
  case `community_detection` or a future signal revives the question.
- *Prerequisite measurement*: done (ADR 0063) — real production-scale
  igraph measurement, the first at this scale for any of
  `packages/research`'s graph tooling.
- *What not to build yet*: nothing — not promoted, per ADR 0063.

**Any Jamiroquai-specific public feature.** Explicitly reviewed and not
promoted twice now (Phase 3 Slice G, and implicitly again by this
cleanup pass not revisiting the decision). The real findings (compilation-
heavy corpus scope, low role coverage) are corpus-scope limitations, not
Jamiroquai-specific — the "core vs. exploration corpus" direction above
is the more honest prerequisite, not a reason to avoid Jamiroquai
specifically.
- *What not to build yet*: nothing here until the corpus-scope question
  above has a real answer.

**Catalog-expansion readiness (2026-08-17) — measured, not acted on.**
Ran the existing `rank-album-candidates` → `review-album-candidates`
pipeline (`packages/graph-core/.../candidate_review.py`, real, already
built, never mutates any catalog artifact — structurally guarded by its
own test) against the real private one-hop corpus, producing a
local-only, 200-candidate report. `review-album-candidates`'s own input
is the collection-seeded one-hop corpus, so per-candidate detail
(titles, master ids, individual counts) is collection-membership-
adjacent and stays local-only (`local/research/catalog-expansion/`,
gitignored) — only aggregate counts and method are recorded here, per
`docs/PUBLIC_PRIVATE_BOUNDARY.md`'s own checklist.
- *Real, aggregate findings*: of 200 ranked candidates, a third (33.5%)
  would add zero new contributors beyond the already-published graph —
  low-value additions structurally, not worth prioritizing. Only 9%
  would add more than 10 new contributors each; only 4% more than 20.
  A hypothetical top-20-by-value pilot would add ~448 new contributors
  total (~22/album average); a top-40 pilot ~570 total (~14/album
  average — real, measured diminishing returns past the first 20). No
  format-descriptor caveats were found on any of the 200 candidates'
  main releases at all — a real, measured result, not a positive
  quality claim (the tool's own method note is explicit that an empty
  caveat list is never confirmation of clean provenance, only absence
  of a known red flag).
- **Two corrections to the paragraph above (2026-08-27, Phase 7
  preflight).** Both were found by re-deriving these numbers from the same
  still-present local report, not by re-running the pipeline.
  1. **The ~448 figure counts albums already in the catalog.**
     `rank-album-candidates` has no already-published exclusion and
     `review-album-candidates` does not flag one, so 76 of the 200 candidates
     (38%) are masters already in
     `apps/web/public/data/catalog/albums.v1.json` — including 7 of the top 20
     by value. Restricted to the 124 genuinely-unpublished candidates, a
     top-20 pilot adds **285** new contributors, not 448 (~36% lower). The
     33.5%/9%/4% distribution figures are unaffected in kind, but they too are
     computed over the mixed set.
  2. **"Zero format-descriptor caveats" is a dataset artifact, not a
     measurement.** That run used `local/processed/discogs-onehop/` — the
     **v1** corpus, which has no `table=release_formats`. `graph.py`
     deliberately substitutes an empty `release_formats` view when no parquet
     files exist, and `caveat_flags_for_descriptors` returns 0 for an empty
     descriptor set — so an empty caveat list across all 200 was structurally
     guaranteed before a single candidate was read. `graph.py`'s own docstring
     anticipates exactly this ("callers must treat as 'no descriptors known'
     rather than 'no caveats'"). Cross-checked against the **v3** corpus,
     which does carry `release_formats`, the same 200 main releases yield
     **1** `reissue` caveat. The run followed the documented procedure —
     `docs/OPERATOR_SETUP.md`'s catalog-regen runbook pointed at the v1 path —
     so the runbook is what was wrong, and it has been corrected rather than
     this being recorded as operator error.
- *What this does NOT do*: propose, rank-and-ship, or even name any
  specific candidate publicly. No catalog artifact
  (`data/albums/top-albums-v1.json`, `apps/web/public/data/catalog/
  albums.v1.json`) was touched — confirmed via `git status` before and
  after this run.
- *Biggest uncertainty*: whether a +20/+40 pilot is worth the editorial
  review cost this measurement doesn't capture (each candidate still
  needs a human look before promotion, per `build-public-album-catalog`'s
  own required-inputs contract) — a real, unmeasured cost, not decided
  here.
- *What not to build yet*: no catalog expansion. This is readiness
  measurement only; promotion stays the explicit human editorial
  decision `candidate_review.py`'s own `method_note` already states.

## Publication/data operations

**Repeated publication and rollback verification -- done.** This was a real, open,
never-measured item as of the Phase 4 plan's original authoring; it is no longer
open. A real rollback drill was performed 2026-08-08 (revert-and-restore against a
live Phase-4 artifact, PRs #96/#97, ADR 0058 Slice 11) — see `docs/ROADMAP.md` §6
(checked off) and `docs/OPERATOR_SETUP.md`'s Rollback section for the real,
dated record. This entry previously contradicted both of those; corrected during
the post-Phase-4 cleanup audit rather than left stale.

**Reviewed-cohort promotion.** ADR 0031's mechanism is real and fully
implemented (`promote-playable-cohort` CLI); no real cohort has ever been
reviewed and promoted through it (confirmed by this cleanup pass's
tracker audit — no `playable-cohort-v1.json` artifact exists anywhere in
the repo). This is a human review step, not missing code.
- *What not to build yet*: nothing — this needs a human to actually do
  the review, not more engineering.

## Explicitly not evaluated here

Per this cleanup pass's own scope boundary: no second data source
(MusicBrainz/Wikidata), no LLM/vector/embeddings infrastructure, no GPU
or x600 compute, no new game mode, no live API, no site redesign. These
remain real candidates the original Phase 3 plan named and rejected for
lack of a measured workload — nothing in this cleanup pass changes that
calculus.
