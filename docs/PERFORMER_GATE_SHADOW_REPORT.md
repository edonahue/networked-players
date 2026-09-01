# Performer graph shadow-build report (ADR 0068 PR 2, 2026-09-01)

Real, measured comparison between `credit_edges_sql`'s current (ADR 0068,
performer-gated) output and a frozen reconstruction of its pre-ADR-0068
(broad) behavior, run against the real one-hop working set
(`local/processed/discogs-onehop-v4/snapshot=20260601`, 49,337,976 credit
rows, 949,805 distinct artists). **No production artifact or public site
behavior changes as a result of this PR** — `graph.v2.json`, `challenge.v2.json`,
and every other published artifact are still built from the pre-cutover
process; this report exists to measure the real shape of the change before
PR 3 regenerates any artifact from it.

> **Machine-readable companion:**
> [`docs/data/performer-gate-shadow-report-v1.json`](data/performer-gate-shadow-report-v1.json)
> is the full committed output of
> `networked-players-catalog performer-gate-shadow-report`
> (`packages/graph-core/.../shadow_report.py`), run 2026-09-01 against the
> command above. This document summarizes and interprets it; the JSON is the
> record.

## Method

`shadow_report.build_shadow_comparison_report` runs two edge relations over
the identical `credits`/`releases` views:

- **`gated_adr0068`** — the real, current `credit_edges_sql()`, unmodified,
  imported directly from `graph.py`.
- **`broad_pre_adr0068`** — a deliberately frozen reconstruction of
  `credit_edges_sql` as it stood at commit `000a506` (the last commit before
  ADR 0068), kept in `shadow_report.py` as a one-time comparison copy that
  must never track future changes to the real function. It reuses `graph.py`'s
  current, ADR-0068-unrelated helpers (placeholder/compilation/studio-format
  guards) verbatim — only the two `AND is_performer_role(...)` conditions the
  real function gained are omitted, on purpose.

For each relation: node/edge/component counts via a Python union-find over
the real undirected edge set; "catalog-albums-in-largest-component" and
"isolated anchors" by checking each of the 179 real catalog albums' primary
`artist_id` (`apps/web/public/data/catalog/albums.v1.json`) against graph
membership and the largest component — one entry per real album, not
deduplicated by artist (round-1 Codex review finding on PR #204: the
catalog's 179 albums span only 173 distinct primary artists, e.g. 5
Jamiroquai albums, and an earlier version of this report incorrectly
collapsed that multiplicity into a set, undercounting both fields);
degree distribution and the top 15 highest-degree nodes. "Excluded edges by role text" is a real frequency
count of `track_credit`/`release_credit`-scope role texts that fail
`is_performer_role` today, sampled from the top 500 most frequent
`track_credit`/`release_credit` role texts in the corpus (not a per-dropped-
pair join, which is a materially heavier query for a diagnostic that only
needs "what kinds of roles are now correctly excluded").

Route-length distribution and no-path frequency are **not** measured in this
report — computing them meaningfully needs the bounded, catalog-scoped
pathfinding graph PR 3 will regenerate (`graph.v3.json`), not the full
949K-artist one-hop corpus; that comparison belongs in PR 3's own report,
against the real regenerated artifact. Route-length/no-path are the only
plan-listed metrics deferred to a later PR's shadow diagnostic; the plan's
"non-goals" list this as acceptable since the full one-hop corpus is not
what `graph.v3.json` is bounded to.

## Headline numbers

| Metric | Broad (pre-ADR-0068) | Gated (ADR 0068) | Change |
|---|---:|---:|---:|
| Nodes (distinct artists with ≥1 edge) | 371,536 | 253,448 | −31.8% |
| Undirected edges | 1,329,707 | 838,567 | −36.9% |
| Directed edges | 2,659,414 | 1,677,134 | −36.9% |
| Connected components | 835 | 1,398 | +67.5% |
| Largest component size | 367,897 | 246,496 | −33.0% |
| Max degree (single hub) | 3,592 | 1,800 | −49.9% |
| Mean degree | 7.16 | 6.62 | −7.5% |
| Median degree | 1.0 | 1.0 | unchanged |

**Every one of the 179 real, published catalog albums stays in the largest
component under both the broad and the gated relation — zero isolated
catalog anchors either way.** The performer gate roughly halves the
corpus-wide hub degree of the single largest hub (3,592 → 1,800) without
disconnecting any catalog album, which is the shape of result ADR 0068 set
out to produce: real, non-performing "everyone connects to the prolific
producer/engineer" hubs shrink; the catalog's actual musical connectivity
survives.

## Correcting the plan's preliminary hypothesis

The approved plan's Context section carried a preliminary hypothesis —
"~24K/76K undirected edges, ~170/179 albums retained, ~6 isolated anchors" —
explicitly flagged there as unverified. That hypothesis was written against
the wrong scale: it describes numbers in the shape of the **bounded,
catalog-scoped pathfinding graph** (ADR 0050's ~41K-node ego network around
179 catalog albums), not the full one-hop corpus this shadow report measures
(949,805 artists, of which 371,536 have at least one real co-credit edge
under the broad relation). The real full-corpus numbers are two orders of
magnitude larger than the hypothesis. Per the plan's own instruction to
"report what the source data actually shows" rather than preserve an
unverified guess: **the hypothesis is discarded, not reconciled.** The
bounded pathfinding-graph-scale comparison this hypothesis was actually
gesturing at is PR 3's job, once `graph.v3.json` exists to measure.

## What's now excluded (real corpus role-text frequency)

This list is restricted to role texts that **survived** ADR 0035's
pre-existing denylist (`_NON_COLLABORATIVE_ROLE_TOKENS`, applied to both the
broad and gated relations identically) but fail ADR 0068's new
performer-only allowlist — the actual delta the performer gate introduces,
not every non-performance role text in the corpus (round-2 Codex review
finding on PR #204: an earlier version of this report counted every
`track_credit`/`release_credit` role text unconditionally, so Written-By
appeared as the #1 "now-excluded" role at 8.68M rows despite having been
excluded from both relations since ADR 0035, long before this PR).

The corrected top exclusions are all genuinely new: Producer (1,921,760
rows), Engineer (766,734), Mixed By (604,678), Arranged By, Engineer
[Assistant], Recorded By, Mastered By, Co-producer, Conductor, Arranged By
[Strings], Programmed By, Remastered By — matching ADR 0068's own audit
exactly, and none of them were excluded before this PR. Full list:
`docs/data/performer-gate-shadow-report-v1.json`'s
`excluded_edges_by_role_text`.

## A real finding: "Horns" was missing from ADR 0068's own token set

Running this diagnostic against the real one-hop corpus (rather than the
`discogs-v3-full` corpus ADR 0068's original PR 1 audit used) surfaced one
real, currently-excluded token with real volume that PR 1's audit missed:
**"Horns" (124,760 rows)** — a real collective brass-section performance
credit, the identical case as "Strings" (already included). Fixed in this
PR: added to `_PERFORMER_ROLE_TOKENS`/`roleTaxonomy.ts` (109 tokens on both
sides now), documented as an addendum to ADR 0068 rather than silently
editing its original audit table, with a pinned test on each side. The
headline numbers above already reflect this fix (re-run after the addition,
not the pre-fix numbers). This is the shadow-diagnostic process catching a
real gap before production cutover, exactly as intended — not a defect in
either PR.

## A real finding: album-anchor eligibility missed the quotation guard

Code review caught a second real bug during this PR, separate from the
shadow report's own numbers: `pathfinding_graph.py`'s
`edge_eligible_membership_artist_ids` (which decides who an album's virtual
anchor node can reach) was rewritten to check `is_performer_role` directly,
but `is_performer_role`'s bracket-stripping alone cannot tell "played the
sampler as an instrument" from "quoted someone else's recording" —
`Performer [Sample]` normalizes to the real performer token `performer`.
`credit_edges_sql` never has this problem because its universal
`edge_ineligible_role` entry gate (which DOES check for quotation patterns)
runs before the performer condition; the album-anchor function needed the
same two-part check and didn't have it. Fixed: `edge_eligible_membership_
artist_ids` now requires both `not edge_ineligible_role(...)` and the
credit-scope-aware performer check, with a regression test. This function
is not exercised by this report's own numbers (it's used only when
`pathfinding-graph.v3.json` is built, in PR 3) — noted here because it was
found during this PR's review, not because it changes any number above.

## Non-goals of this report

No production artifact changes, no schema version bump, no Connect/Explore
behavior change — all deferred to PR 3/PR 4 per the approved plan. This
report's numbers describe the full one-hop corpus, not any bounded or
catalog-scoped derivative; PR 3's own report, once `graph.v3.json` exists,
is the comparison that actually predicts Connect/Explore-visible behavior.
