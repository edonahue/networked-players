# Performer Graph migration — final report

**ADR:** `docs/decisions/0068-performer-only-public-graph.md`
**Completed:** 2026-09-02
**Baseline:** `000a506` (PR #202, merged) — the last commit before the migration.

The public site's traversable network now means **documented musical
performance**, not "these two names appear somewhere in the same release's
credits". This report records what changed, what was measured, and what is
deliberately left open.

## The contract

> A connection exists because the linked artists or groups are documented as
> performing on the same recording or release — not merely because their
> names appear somewhere in the release credits.

One canonical predicate, applied once, at the edge-construction layer
(`graph.py`'s `credit_edges_sql`), `credit_scope`-aware:

- **Billing scope** (`track_artist` / `release_artist`) is always implicitly
  performer-qualifying, regardless of role text — including a bare `NULL`
  role. This is the correct treatment of main-release anchors, groups and
  bands billed as artists, and a release's primary billed artist on their
  own record.
- **Extra-credit scope** (`track_credit` / `release_credit`) must pass
  `eligibility.py`'s `is_performer_role` / `is_performer_role_sql`.
- `co_performers` needed no change: both endpoints are always `track_artist`
  scope, which is inherently performer-qualifying.

ADR 0035's denylist (`edge_ineligible_role`) still applies underneath in
both modes; ADR 0068 adds an allowlist on top for extra-credit rows. ADR
0039's "`eligibility.py` must never be imported by `graph.py` /
`challenge.py` / the cohort pipeline" restriction is explicitly superseded
(addendum added to ADR 0039 itself). ADR 0047 is not violated:
`role_taxonomy.py` remains presentation-only and `is_performer_role` never
became part of it.

## PR sequence and merge SHAs

| PR | Title | Merge SHA |
| --- | --- | --- |
| [#203](https://github.com/) | Policy measurement and superseding ADR 0068 | `b205c1a` |
| [#204](https://github.com/) | Shared eligibility cutover + shadow-build diagnostic | `88a0d94` |
| [#205](https://github.com/) | Dual-live `graph.v3.json` + `challenge.v3.json` | `f4a0a3f` |
| [#206](https://github.com/) | Connect and Explore cutover to `graph.v3.json` | `dc1e716` |
| [#207](https://github.com/) | Pages cut over to `challenge.v3.json`, Behind the Glass retired | `93683b5` |
| [#208](https://github.com/) | Contributor-index regeneration, background-only retirement | `4e58b28` |
| [#209](https://github.com/) | `graph.v2.json` / `challenge.v2.json` retirement | `e4a9eff` |

The plan's PR 6 was split in two. #208 retired the background-only machinery
and regenerated the stale derived artifacts; #209 deleted the v2 files and
collapsed their registration groups. That split follows ADR 0058's own
precedent that retirement is a separate, explicit step from cutover — and it
kept each PR reviewable, since the v2 retirement alone touched ~40 files.

## Before / after measurements

### Full public one-hop corpus (PR 2 shadow diagnostic)

Measured against the real corpus, not hypothesized —
`docs/PERFORMER_GATE_SHADOW_REPORT.md`:

| Metric | Broad (pre-0068) | Gated (0068) | Change |
|---|---:|---:|---:|
| Nodes with ≥1 edge | 371,536 | 253,448 | −31.8% |
| Undirected edges | 1,329,707 | 838,567 | −36.9% |
| Connected components | 835 | 1,398 | +67.5% |
| Largest component | 367,897 | 246,496 | −33.0% |
| Max degree (single hub) | 3,592 | 1,800 | −49.9% |

The halved max degree is the clearest signal that the gate removed the
intended thing: the biggest hubs were prolific engineers and producers
connecting otherwise-unrelated records.

### Shipped pathfinding graph

| Metric | v2 (broad) | v3 (gated) | Change |
|---|---:|---:|---:|
| Nodes | 41,736 | 20,845 | −50.0% |
| Directed edges | 151,726 | 76,646 | −49.5% |
| Album anchors | 179 | 179 | unchanged |
| Isolated album anchors | 0 | 0 | unchanged |
| Connected components | 1 | 1 | unchanged |

**All 179 of 179 catalog albums remain in the largest component.** Zero
albums newly isolated, zero disconnected, zero edges fabricated to preserve
connectivity. The gate roughly halved the graph without severing a single
real catalog album.

### Shipped artifacts

| Artifact | Version | Shape |
|---|---|---|
| `pathfinding/graph.v3.json` | `pathfinding-graph-v3-20260601-93b440839c39` | schema 3, `graph_policy_version: 1` |
| `challenge.v3.json` | (content-hash provenance) | 300 paths, 179 albums, 290 artists, 367 releases |
| `contributors/index.v1.json` | `contributor-index-v1-20260601-9ad4c9cd1817` | 445 contributors (was 521) |
| `contributors/album-hop-distances.v1.json` | `album-hop-distances-v1-20260601-832c54f947ba` | 2,375 entries |

`challenge.v2.json` reported 348 artists; `challenge.v3.json` reports 290.
The 58 artists that dropped out were reachable only through non-performing
credits. The contributor index fell 521 → 445 for the same reason — most
visibly Stuart Hawkes (#300468), the mastering engineer whose page the
original request cited as connecting *The Dark Side Of The Moon*,
*Synkronized*, *Post*, and *1989*. He is no longer a graph contributor. His
mastering credits are still fully published as evidence.

### Artifact lineage

`graph_policy_version` (new, currently `1`) is carried in both the
pathfinding graph and challenge provenance, and is hashed into
`pathfinding_graph_version` at `schema_version >= 3`. It tracks the
traversal *rule architecture*, not the token set — so a policy-only
regeneration is detectable by a validator or a stale cached client even
when the schema shape is unchanged. `cohort_connectivity.SCORER_VERSION`
was bumped 4 → 5 for the same reason.

## Component and catalog impact

No album was deleted, and no album was added. An album that would have
become isolated stays in the catalog, honestly represented — none did.
The catalog remains 179 albums.

Three contributors in the index are not nodes in `graph.v3.json` (Haruomi
Hosono #19132, Erik Friedlander #146031, T-Square #1249160). All three are
present in `challenge.v3.json`; this is the previously documented,
pre-existing scope difference between the contributor index (built from
challenge + routes hops) and the pathfinding graph (bounded to the
album-anchored neighborhood), not a policy violation.

## Games

Revalidated, not rebuilt — and the revalidation is measured, not asserted:

- **Record Routes** (343 rounds, 543 hops, 290 artists): all **1,086**
  edge-defining `role_a` / `role_b` fields pass `is_performer_role`. Every
  artist is present in `graph.v3.json`. One hop (69722 "Backing Vocals" ↔
  249449 "Guitar") has no corresponding `graph.v3.json` edge — both roles
  are genuine performer roles, and the absence is the same bounded-scope
  difference noted above, not a policy failure.
- **Connection Guesser** (500 rounds): its rounds carry shared-artist answer
  sets rather than traversal hops. All **1,958** evidence rows
  (809 `release_credit`, 1,149 `track_credit`) satisfy the ADR 0068 rule —
  zero violations.

`rounds.py`'s `build_round_hop` already required `is_performer_role` on both
sides before this migration, which is why both artifacts were already
compliant as published and needed no regeneration.

**Frozen daily history is untouched.** `game/daily-manifest.v1.json` has no
commits anywhere in the migration range (ADR 0043's frozen-history rule).

## Machinery removed

PR #202's mitigation layer existed because a background-engineering-only
pair *could* be a connection. It no longer can, so it was deleted rather
than kept as a dormant safety net.

Verified fail-closed before deleting anything:

- **0 of 891** contributor pairs in `challenge.v3.json` +
  `routes/rounds.v1.json` classify as background-only.
- **0** contributors in the regenerated index have an entirely
  background-only role vocabulary.
- All **12** artist ids the old artifact flagged are absent from the
  regenerated index.

Removed:

- `background-only-profiles.v1.json` and its builder
  (`build_background_only_profiles`), contract module, validator, both CLI
  commands, registration entries in `PUBLIC_ARTIFACT_GROUPS` /
  `_artifact_validators()` / `_DEFAULT_ARTIFACTS`, contract doc, and tests.
- `is_background_engineering_role`, `is_background_only_role_profile`,
  `_BACKGROUND_ENGINEERING_TOKENS`, `_ROLE_COMPONENT_SPLIT` and their TS
  mirrors (`isBackgroundEngineeringRole`, `BACKGROUND_ENGINEERING_TOKENS`,
  `PACKAGING_BUSINESS_TOKENS`, `matchesBackgroundOrNonSubstantive`).
- ADR 0060's `background_only_by_pair` exclusion from
  `interesting_next_step` — `null` again means exactly "no role-disjoint
  neighbor exists".
- `.album-card--muted` / `.contributor-card--muted` styling, `AlbumCard`'s
  `muted` prop, and `backgroundOnlyProfiles.ts`.
- Behind the Glass in full (PR #206): `ROLE_FILTER_MODES` entry, its chip,
  `behindTheGlassEdgeFilter`, `isEngineeringOrProductionRole`,
  `PRODUCTION_AND_ENGINEERING_TOKENS`, and `eligibility_engineering.py`.
  An old `?mode=behind-the-glass` link degrades to a genuinely fresh,
  correctly-labelled default search — `parseConnectUrlParams` already
  normalized unrecognized modes, so no new code and no stale result.
- `recommendedRoute.ts`'s `backgroundHopCount` axis and its `compareRanked`
  tie-break (PR #206). `explainRoute` changed from a measurement ("N of M
  hops bridged by a documented performer") to a guarantee ("every hop is
  backed by documented performance"), which is now structurally true rather
  than merely well-ranked.
- Explore's `isDimmed` background-edge branch — there is nothing left to
  dim.

ADR 0048's and ADR 0060's addenda were amended in place to record the
retirement rather than left describing removed machinery as current.

## Private research

`packages/research` keeps a clearly-labelled broader view. Traversal breadth
is chosen once, at graph construction: `CreditGraph.open(...)` takes
`performer_only: bool = True`, which matches the public product exactly, so
a private result is always reconcilable with what the site would show.
`performer_only=False` restores the pre-0068 relation for research questions
the performer graph cannot answer. It must never produce a public artifact.
`compare.py`'s functions inherit this from the graph they are handed rather
than re-implementing the gate — one parameter, no second graph engine.

Covered by a real fail-then-pass test
(`test_graph_view_traversal_breadth_follows_the_graphs_own_performer_gate`):
Bob, a `release_credit` "Engineer", is invisible to the default graph and
visible in the broader one, with the performer graph asserted to be a strict
subset.

## Validation

Every PR ran the full gate. Final state on this branch:

- `make check`: **1,447 Python tests green**; `validate-public-artifacts`
  `ok: true` across all 13 registered groups; `validate-album-catalog-audit`
  `ok: true`.
- `apps/web`: **0 Astro errors, 0 warnings**, 990-page production build,
  `format:check` clean, full Playwright suite green.
- Fail-then-pass discipline held for every new and changed test. No skips,
  blanket retries, arbitrary sleeps, timeout inflation, semantics-hiding
  snapshots, or weakened assertions were used to reach green.

One notable case: the contributor page's a11y scan began timing out after
the cutover. The cause was duplicate evidence cards (pre-existing — v2's
worst page rendered 172 hops for 62 distinct pairs), not a violation and not
a slow scan. It was fixed with a `dedupeHops` helper keyed on
`(release_id, artist_a_id, artist_b_id)` — explicitly *not* a timeout bump.

## Review

Codex review ran on every PR and found real defects at a rate that argues
against assuming diminishing returns. Findings verified against real code
and fixed, or pushed back on with reasoning:

- **SCORER_VERSION not bumped** (PR #204) — real; bumped 4 → 5.
- **Catalog set collapsed 179 albums into 173 artists** (PR #204) — real
  (Jamiroquai has 5 albums); renamed the parameter to
  `catalog_album_artist_ids`, added `isolated_catalog_album_count`, re-ran
  the corpus report.
- **Quotation-guard gap** (PR #204) — real: `is_performer_role("Performer
  [Sample]")` returns `True` because bracket-stripping yields "performer".
  Fixed by also requiring `not edge_ineligible_role(...)` in
  `edge_eligible_membership_artist_ids`.
- **Excluded-roles query counted already-excluded roles** (PR #204) — real;
  Written-By (8.68M) appeared as the top "newly excluded" role when ADR 0035
  had always excluded it. Fixed by adding `AND NOT {denylist_ineligible}`.
- **Behind the Glass** (PR #204) — pushed back: it describes PR 4's intended
  consequence, not a defect in PR 2. Accepted.

Two failures were mine, caught in self-review and worth recording: a
parity test that passed even under `sorted(expand_from, reverse=True)`
(the shared fixture had no diamond — I built one, which made the test
genuinely fail under reversal), and a timing benchmark that accidentally
measured the slow name-matching path rather than the path the CLI takes.

## Deployment

Every site-changing merge was live-verified against
`networked-players.com`. Final state after #209:

| Check | Result |
|---|---|
| `challenge.v3.json`, `pathfinding/graph.v3.json` | 200 |
| `challenge.v2.json`, `pathfinding/graph.v2.json` | **404** |
| `contributors/index.v1.json` | 200, 445 contributors, `source` names `challenge.v3.json` |
| `evidence/release-registry.v1.json` | 200, 10,232 release ids, `source` names `graph.v3.json` |
| `/contributors/300468/` (Stuart Hawkes) | **404** — no longer a graph contributor |
| `/play/connect/` route filters | Any documented route, Rhythm Section, Guitar Paths — no Behind the Glass |

Live verification caught a real miss after #207: Stuart Hawkes' page still
showed 7 connected albums and "is co-credited on the releases connecting the
albums below", because `contributors/index.v1.json` was still derived from
`challenge.v2.json`. PR 5's plan text had called for exactly this
recomputation and I had not done it. Every gate was green while the
migration's headline promise was still visibly unfulfilled in production.

## v2 retirement (completed in #209)

`graph.v2.json` and `challenge.v2.json` are deleted, along with
`data/contracts/challenge-v2.md` and `pathfinding-graph-v2.md`. Both URLs
now return **404** in production; `graph.v3.json` and `challenge.v3.json`
return 200. The `challenge`/`challenge_v3` and
`pathfinding_graph_v2`/`pathfinding_graph_v3` registration groups collapsed
into `challenge` and `pathfinding_graph` — the same in-place flip
`test_artifact_registration_completeness.py`'s own comment had predicted for
the v1→v2 transition. `pathfinding_graph_failures` still accepts v1- and
v2-shaped payloads: the validator never narrowed, only the published
artifact set did.

`smoke.spec.ts`'s "static challenge.v2 artifact is reachable" test became
"the retired v2 artifacts are no longer served" — a stale v2 file left
deployed would be a valid-looking artifact carrying pre-0068 semantics,
so asserting absence is the real check.

### A second defect live verification caught

The artifacts #208 regenerated were **built** from `challenge.v3.json` but
their published `source` strings still **claimed** `challenge.v2.json`;
`evidence/release-registry.v1.json` named `graph.v2.json`. All three pointed
at files #209 deletes. Provenance strings are not content-hashed, so no
version changed and every gate stayed green while the wrong claim sat live
in production — precisely the "valid but stale combination" this migration's
lineage rules exist to prevent.

Fixed by a real rebuild in dependency order rather than a string patch:

| Artifact | Before | After |
|---|---:|---:|
| `evidence/release-registry.v1.json` | 21,062 release ids | **10,232** |
| `contributors/index.v1.json` | 445 | 445 (hash unchanged) |
| `contributors/album-hop-distances.v1.json` | 2,375 | 2,375 (hash unchanged) |

The registry's drop is a genuine consequence of the performer-gated graph's
smaller evidence set. Verified it still covers everything the site
references: **0 missing** across `challenge.v3`'s 367 hops, routes' 367
hops, and `graph.v3`'s 9,950 evidence release ids.

**This is the second time live verification found something CI structurally
could not.** Both misses shared a shape: a derived artifact was internally
valid, passed every contract check, and was wrong about the world. Worth
carrying forward as a standing habit rather than a one-off — content hashes
prove an artifact is self-consistent, not that it describes reality.

## Remaining limitations and follow-ups

- **No vocals/keys route filter.** Rhythm Section and Guitar Paths survive
  as narrower filters within the performer baseline (their token sets are
  already subsets of the performer allowlist). Adding a vocals or keys
  filter needs real coverage measurement first — deliberately not guessed
  here.
- **The contributor-index / pathfinding-graph scope difference** (~73% edge
  overlap) is pre-existing and documented, not introduced by this migration.
  Worth closing eventually so "in the index" and "in the graph" mean the
  same thing.
- **The performer allowlist is 109 tokens**, expanded from 69 by real corpus
  measurement across PRs 1 and 2 (most recently "horns", found by the shadow
  diagnostic at 124,760 rows). It will need periodic re-measurement as the
  corpus grows; the convention — real corpus count in a comment plus a
  pinned test per token — is established and should be kept.
- **`album-credit-membership.v1.json` is deliberately unchanged** and stays
  fully inclusive. Mastering, mixing, production, writing, and design
  credits remain published evidence in full. Only their ability to form a
  traversable public edge is gone.
- **Provenance strings are not content-hashed.** Both defects live
  verification caught were of this shape: an artifact internally valid and
  wrong about the world. A cheap guard worth considering — assert in
  `validate-public-artifacts` that every artifact's `source` names only
  files that actually exist in `apps/web/public/data/`. That would have
  caught the stale `challenge.v2.json` claim mechanically, at the point the
  file was deleted.

## Status

**Complete.** All eight PRs (#203–#209) are merged, CI-green, and
live-verified. The public graph means documented musical performance; ADR
0068 is the governing contract; no non-performance-only credit can form a
public edge; every route hop can explain its qualifying performance
evidence; Connect cannot produce a zero-performer alternate (structurally,
not by ranking); Explore traverses the performer graph rather than dimming;
Behind the Glass is retired with its old URLs degrading safely; full
evidence and provenance remain intact; and PR #202's mitigation machinery is
gone rather than dormant.
