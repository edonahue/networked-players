# Phase 6 report: from game to music universe (cross-linking + a real discovery signal)

**Status: complete.** All planned PRs shipped, each its own branch/PR,
merged once `make check` (and, for `apps/web` changes, the full local
Playwright suite plus CI) was green — the same continuous discipline
Phase 3/4/5 established. This report is the closing summary: what
shipped, what was measured, what was rejected or deferred, and what's
left.

## What shipped

| PR | # | What it is |
|---|---|---|
| 6-00 | [#122](https://github.com/edonahue/networked-players/pull/122) | Corrected `docs/NEXT_PATH_BRIEF.md`'s title/date and two real overstatements (Phase 4/5 having shipped without the brief being updated; a wrong claim about what `contributor_network` actually consumes) before building anything new on top of it. |
| 6-01 | [#123](https://github.com/edonahue/networked-players/pull/123) | Album pages' documented connections link directly into Connect Two Records, pre-filled. |
| 6-02 | [#125](https://github.com/edonahue/networked-players/pull/125) | Album pages link directly into the Network Explorer. |
| 6-03 | [#126](https://github.com/edonahue/networked-players/pull/126) | Explorer gained read-only `?center=` deep-link support. |
| 6-04 | [#127](https://github.com/edonahue/networked-players/pull/127) | Contributor pages link into the Network Explorer, centered on that contributor. |
| 6-05 | [#128](https://github.com/edonahue/networked-players/pull/128) | Explorer's center node links back to its own contributor page. |
| 6-06 | [#129](https://github.com/edonahue/networked-players/pull/129) | Shared evidence-hop contributor links, reused across Explorer and Connect. |
| 6-07 | [#130](https://github.com/edonahue/networked-players/pull/130) | Cross-link audit sweep (closing gaps the prior six PRs left) + `/about/` update describing the now-connected surfaces. |
| 6-08 | [#124](https://github.com/edonahue/networked-players/pull/124) | Album-candidate review report — a planner that surfaces candidates for human review, deliberately not an executor. |
| 6-09 | [#131](https://github.com/edonahue/networked-players/pull/131) | `interesting_next_step`: a real, measured, anti-hub-bias discovery signal added to the contributor index. ADR 0060. |
| 6-10 | [#132](https://github.com/edonahue/networked-players/pull/132) | Surfaces `interesting_next_step` on `/contributors/` (a callout + badge) and in the Network Explorer (a highlighted node). |
| 6-11 | [#133](https://github.com/edonahue/networked-players/pull/133) | `research-scope-tier` CLI command — turns the hand-run five-artist scope-tier measurement into reusable, tested tooling. |
| 6-12 | [#134](https://github.com/edonahue/networked-players/pull/134) | ADR 0061 — deliberately defers the scope-tier corpus contract question rather than picking a shape. |

Two real strands: **6-00 through 6-08** made the site's existing surfaces
(album pages, contributor pages, Explorer, Connect) actually link to each
other — closing gaps where a page *referenced* related content without a
real `<a href>` to it. **6-09 through 6-12** added one new, real discovery
signal on top of the now-connected graph, and resolved (by deferring,
with reasoning) the standing corpus-scope design question from
`docs/NEXT_PATH_BRIEF.md`.

## What was measured before being built

- **6-09 (`interesting_next_step`)**: before designing anything, checked
  what raw-degree ranking would produce — exactly the hub-bias ADR 0059
  already killed once in Connect's route scorer. Measured the real,
  committed 549-contributor index instead: median `connection_count` is
  2 (max 52); 366 of 549 (67%) have only 1-2 neighbors; 246 of 549 (45%)
  carry more than one `role_categories` value; 376 of 549 (69%) have at
  least one neighbor whose role set is entirely disjoint from their own.
  The shipped signal (role-disjoint neighbor, tie-broken toward *lower*
  `connection_count`) came directly from these numbers, not a hunch.
  Betweenness centrality and community detection were ruled out up front
  by tracing ADR 0054's research/publication boundary: both need the
  private full corpus + `igraph`, neither of which the public contributor
  index can use.
- **6-10 (surfacing the signal in Explorer)**: a test built against the
  contributor index alone failed even after the feature was implemented
  correctly — investigation found the contributor index and the
  published pathfinding graph (`graph.v2.json`) are two different
  artifacts built from different source data with different edge sets.
  Measured the real mismatch rate: 277 of 379 (73%) of real
  `interesting_next_step` picks are genuine edges in the pathfinding
  graph; the other 27% is real and expected, not a bug — Explorer
  silently doesn't highlight a pick that isn't a real edge in *its own*
  graph, consistent with the field's own null-is-valid contract.
- **6-11/6-12 (scope-tier tooling + the deferred decision)**: re-running
  the new `research-scope-tier` tool against the real, already-built
  Jamiroquai corpus reproduced the original hand-measurement's Tier A
  exactly (656 nodes/680 edges/13 components/617 largest), but found
  *more* real graph structure at Tiers B/C than the original one-off
  script had recorded (292 vs. 291 nodes at B; 149 vs. 55 at C) — a real
  correction, most likely because the hand-rolled script hadn't exercised
  the full production `credit_edges_sql` rule set. The qualitative
  star/tree-topology finding held at the corrected numbers too. This
  measurement, plus the fact that every scope-sensitive analysis
  consumer is research-lane-only (ADR 0054), is what ADR 0061's deferral
  decision rests on — not a guess.

## Rejected or descoped approaches

- **A learned or weighted "interesting next step" score** — explicitly
  rejected in ADR 0060's decision section. The shipped signal is a plain
  structural fact (role-disjointness + a documented tie-break), never a
  model, embedding, or popularity score.
- **Reproducing scope-tier Tier D ("studio albums only") in
  `research-scope-tier`** — the original measurement's Tier D was a
  hand-curated release-title list, not a data-derived filter. Automating
  it would mean guessing at an "official studio album" signal the
  dataset doesn't actually carry. Stays a manual follow-up.
- **A scope-tier corpus contract change (two corpora, or a scope-tier
  field)** — ADR 0061. Every current consumer of scope-sensitive
  analysis is research-lane-only; nothing public-facing is blocked by
  leaving the Topic Corpus contract as it is. Deferred with two concrete
  revisit triggers, not closed.
- **Forcing the Explorer highlight to always land on a real graph edge**
  (e.g., by re-deriving `interesting_next_step` from the pathfinding
  graph instead of the contributor index) — considered after discovering
  the 73% match rate, and rejected: the field's contract already treats
  `null` as a valid, honest answer, and a 73% real-match majority is
  consistent with the "not trivial" bar ADR 0060 set for the underlying
  signal. Documented as an expected, graceful no-op rather than either
  forced or hidden.

## Tests run

- Backend: `make check` (Ruff lint/format, mypy, pytest, both
  public-artifact-gate validators) — green at every backend-touching PR
  merge; 1,071 backend tests passing at this report's close.
- Frontend: full local Playwright suite (`npx playwright test`, no
  filter) — 436 passed, run at PR 6-10 (the last PR in this phase that
  touched `apps/web`); CI (`npm run format:check`, TypeScript build,
  Workers Build) green on every `apps/web`-touching PR.
- New coverage this phase: `packages/graph-core/tests/test_contributor_index.py`
  (role-disjoint selection, tie-break correctness), `packages/contracts/tests/`
  (six new `interesting_next_step` contract-validation cases),
  `apps/web/tests/contributors.spec.ts` and `game-networkexplorer.spec.ts`
  (the callout/badge and the Explorer highlight, the latter cross-checked
  against the real pathfinding graph's own CSR offsets rather than
  assumed), and `packages/research/tests/test_scope_tier.py` (11 tests
  over a synthetic fixture covering tier boundaries, role-coverage
  direction, and graph-structure collapse).
- Fail-then-pass discipline applied throughout: every new test was
  verified to genuinely fail against a `git stash`-restored prior state
  of the relevant source file before being trusted, catching real,
  non-obvious bugs (the pathfinding-graph mismatch above) rather than
  just a green run.

## Not exercised at Phase 6's close (explicitly out of scope or deferred)

- Tier D ("studio albums only") scope-tier automation — stays a manual,
  per-artist follow-up; not built (see above).
- Any promotion of `contributor_network`/`community_detection`/
  `bridge_analysis` to a public surface — `docs/NEXT_PATH_BRIEF.md`'s
  "Most-connected-contributors view" entry remains open; this phase did
  not touch it beyond correcting its own prior overstatement (6-00).
- The scope-tier corpus contract redesign itself — deliberately deferred
  by ADR 0061, with two concrete, named revisit triggers.
- Any new public artifact or contract version bump — this phase's one
  schema change (`interesting_next_step` on the contributor index) was
  additive within the existing `contributor-index-v1` schema version,
  deliberately not a v2.

## Remaining, after this phase

1. **Whether `interesting_next_step` earns a second surface** (e.g. a
   dedicated "discover something different" entry point beyond the
   contributor-page callout and the Explorer highlight) — not designed,
   not requested by any measurement in this phase.
2. **The scope-tier corpus contract question** — ADR 0061's two revisit
   triggers (a real promotion candidate, or a caching need the on-demand
   filter can't satisfy) are the honest condition for reopening it.
3. **`docs/NEXT_PATH_BRIEF.md`'s remaining open candidates** — Compute/
   platform and Publication/data-operations sections were untouched by
   this phase and remain exactly as they were at the 2026-08-16
   correction pass.
