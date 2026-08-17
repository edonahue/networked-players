# ADR 0061: corpus scope-tier design stays deferred — no contract change yet

- **Status:** Accepted
- **Date:** 2026-08-16
- **Depends on:** [ADR 0054](0054-research-lane-and-promotion-boundary.md) (research lane / promotion boundary), [ADR 0059](0059-recommended-route-selection.md) (measurement-before-design precedent for a graph-derived signal)

## Context

`docs/NEXT_PATH_BRIEF.md`'s "Core-discography vs. exploration-neighborhood
corpus split" section has carried an open question since 2026-08-04: the
Topic Corpus Builder's single 1-hop scope serves personnel/role analysis
and network/community analysis with opposite needs. Real measurement
across five structurally different real artists (Jamiroquai, Wu-Tang Clan,
D'Angelo, Nirvana, Miles Davis; `local/research/*/scope-tier-analysis.md`,
gitignored) established:

- Narrowing scope (full corpus → direct-billed → main-release-only)
  raises role-classification coverage in four of five artists (peaking
  70.3%–93.5% at the narrowest tier measured), while collapsing the
  co-credit graph to a pure star/tree centered on the seed artist —
  losing essentially all cross-community structure.
- `contributor_network`/`community_detection`/`bridge_analysis` need the
  wide corpus; a clean personnel timeline needs the narrow one. No single
  tier serves both.
- PR 6-11 (`research-scope-tier`, this phase) turned the hand-run
  five-artist measurement into reusable, tested tooling
  (`packages/research/src/networked_players_research/scope_tier.py`) —
  any topic corpus can now be measured at tiers A/B/C on demand, without
  a new script per artist. Re-measuring Jamiroquai with it reproduced
  Tier A exactly and found *more* real graph structure at Tiers B/C than
  the original hand script had (292 vs. 291 nodes at B; 149 vs. 55 at
  C) — the earlier ad hoc script likely didn't exercise the full
  `credit_edges_sql` rule set. The qualitative star/tree finding held at
  the corrected numbers too.

What PR 6-11 did **not** do, and what this ADR is about: decide whether
the Topic Corpus contract itself should change (a second corpus, a
scope-tier parameter, or something else) to make a narrow-scope view a
first-class, buildable thing rather than a post-hoc measurement over an
already-built full corpus.

## Decision

**Defer the contract change. Measurement tooling is enough for now; no
new corpus shape ships in this phase.**

Every consumer of scope-sensitive analysis today is research-lane-only
under ADR 0054: `role_distribution`, `personnel_timeline`,
`contributor_network`, `community_detection`, and `bridge_analysis` all
run locally, against a corpus an operator builds by hand, for one
subject at a time, and their output never crosses into
`apps/web/public/data/**`. Nothing currently blocked by the single-tier
corpus is public-facing. Concretely:

- If an operator wants a cleaner personnel view for one artist today,
  `research-scope-tier` already tells them exactly which release_ids
  belong to Tier B/C for that corpus — a five-line follow-up DuckDB
  query filters `personnel_timeline`'s own output to that release_id
  set, with no new code. This need is served by the tool PR 6-11 already
  shipped; a full re-architecture doesn't unlock anything that isn't
  already one query away.
- No promotion candidate (per ADR 0054's promotion boundary) currently
  proposes shipping a personnel-timeline or role-distribution view as a
  public artifact. Designing a two-corpus or scope-tier-parameterized
  contract now would be building for a consumer that doesn't exist yet
  — the exact anti-pattern ADR 0059's own postmortem on the first
  `scorePath` attempt (coverage failure from designing against
  1.46%-complete data) warns against repeating in a different shape.
- The two candidate shapes named in `NEXT_PATH_BRIEF.md` ("two corpora"
  vs. "one corpus with a scope-tier field") have real, different
  storage/versioning/self-check implications (`corpus.py`'s manifest,
  `TOPIC_CORPUS_TABLES`, `_self_check`'s provability checks would all
  need to either duplicate or branch) — worth resolving against a real
  consumer's actual requirements, not against a hypothetical one.

**What this is not**: not a claim that the tradeoff is unimportant, not a
claim that Tier D ("studio albums only") tooling will never be built, and
not a closure of the `NEXT_PATH_BRIEF.md` section — it stays open,
updated with a link to this ADR and PR 6-11's tooling.

## Consequences

- No code change beyond this document. `corpus.py`, the Topic Corpus
  contract, and every existing analysis stay exactly as they are.
- `docs/NEXT_PATH_BRIEF.md`'s scope-tier section gets a pointer to this
  ADR, replacing "not yet designed" with "deliberately deferred, see ADR
  0061" — an honest state change, not a resolution.
- Phase 6 closes this investigation thread without a redesign, per the
  phase's own standing permission to reject or defer a feature when
  measurement shows it premature, recording why.

## Validation

No new code to validate — this ADR only records a decision and updates
`docs/NEXT_PATH_BRIEF.md`'s prose. `research-scope-tier` itself (the
measurement tool this decision relies on) was validated in PR 6-11: 11
tests over a synthetic fixture, fail-then-pass verified, plus a real run
against the already-built local Jamiroquai corpus.

## Revisit trigger

Re-open this decision when either becomes true:

1. A concrete promotion candidate (ADR 0054's promotion path: pick one
   research output, write it up as its own slice) proposes shipping a
   personnel/role-distribution view as a public artifact, OR
2. A second research workload needs a *pre-built*, cached narrow corpus
   (not a post-hoc filter of an already-built one) for performance or
   repeated-query reasons `research-scope-tier`'s on-demand filtering
   can't satisfy — not yet measured, and not assumed.

At that point, design the contract shape against that consumer's real
requirements, informed by the measured tradeoff above and by
`research-scope-tier`'s own tier-boundary SQL, which already encodes a
working definition of B/C that a materializing builder could reuse
directly.
