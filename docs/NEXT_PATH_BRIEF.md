# Next-path decision brief (post-Phase-3 cleanup, 2026-08-04)

A factual decision-support document, not a plan for a next phase. The
repository is now internally coherent (see `docs/PHASE3_REPORT.md`'s
follow-up section and ADR 0056) — this names the strongest real next
directions the current, clean architecture supports, with the evidence
behind each, and does not select one. None of these are started.

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
  single corpus with a scope-tier field per analysis is cleaner — not yet
  designed.
- *Prerequisite measurement*: done (this cleanup pass) for Jamiroquai
  alone; a second, structurally different real artist would strengthen
  the case before committing to a contract change.
- *What not to build yet*: don't touch the Topic Corpus contract itself
  without a real design pass — this cleanup pass deliberately only
  measured, per its own scope boundary.

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
- *Biggest uncertainty*: whether `enqueue_verify_challenge.py`'s sharded
  pattern needs its own new primitive in `packages/platform`, or fits the
  existing `select_worker()`/`RunRequest` shape as-is.
- *Prerequisite measurement*: none — this is mostly known, bounded work.
- *What not to build yet*: don't build a new scheduler; reuse what's there.

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

**Most-connected-contributors view (raw co-credit degree).** A real,
already-built research-pack addition (Phase 3 Slice G) uses only
already-public production `graph.py` data — not research-only data — so
it isn't blocked by the research/publication boundary. Not promoted
during Phase 3 because it was new UI/design scope, not because of a data
concern.
- *User value*: a second, simpler, complementary lens on contributor
  connectivity alongside the existing betweenness-based "bridge
  contributors" signal.
- *Backend leverage*: the underlying computation (`contributor_network`)
  already exists and runs against production data today.
- *Biggest uncertainty*: whether this belongs on the existing Network
  Explorer or as a new view — a real design decision, not yet made.
- *Prerequisite measurement*: none additional needed.
- *What not to build yet*: don't build a whole new page speculatively;
  scope it as an addition to an existing surface first.

**Any Jamiroquai-specific public feature.** Explicitly reviewed and not
promoted twice now (Phase 3 Slice G, and implicitly again by this
cleanup pass not revisiting the decision). The real findings (compilation-
heavy corpus scope, low role coverage) are corpus-scope limitations, not
Jamiroquai-specific — the "core vs. exploration corpus" direction above
is the more honest prerequisite, not a reason to avoid Jamiroquai
specifically.
- *What not to build yet*: nothing here until the corpus-scope question
  above has a real answer.

## Publication/data operations

**Repeated publication and rollback verification.** `docs/ROADMAP.md` §6
still has this as a real, open, never-measured item — every publication
to date has been additive, never a real rollback drill.
- *User value*: confidence the publication pipeline can recover from a
  bad push, not just make one.
- *Backend leverage*: `diff-artifact-version` (Phase 2 Slice L) already
  exists; a rollback drill would exercise it plus the existing content-
  hash versioning, not build anything new.
- *Biggest uncertainty*: none real — this is mostly "actually do the
  drill," not a design question.
- *Prerequisite measurement*: none.
- *What not to build yet*: n/a.

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
