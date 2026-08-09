# ADR 0053: Role-aware game mode selection — Behind the Glass

- **Status:** Accepted
- **Date:** 2026-08-03
- **Depends on:** [ADR 0047](0047-role-taxonomy-as-a-third-orthogonal-classification-layer.md), [ADR 0051](0051-connect-two-records.md)

## Context

Slice H's mandate: measure real candidate counts for role-aware game modes
against the current 140-album catalog **before** building any of them, per
ADR 0039/0043's "measured, not designed-then-hoped" discipline and ADR
0043's launch-floor precedent (≥50 one-hop / ≥20 two-hop candidate pairs;
below that, the documented outcome is "defer," not "ship it anyway, thin").

`packages/graph-core/src/networked_players_graph_core/role_mode_candidates.py`
measured three candidates against the real committed 140-album catalog and
the real private one-hop dataset (`CreditGraph.open(..., build_edges=False)`,
24s real run time):

| Mode | Description | Albums w/ ≥1 eligible credit | One-hop pairs | Two-hop pairs |
|---|---|---|---|---|
| **Behind the Glass** | Shared producer/engineering credit | 137/140 | **202** | **429** |
| Rhythm Section | Shared drums or bass credit | 124/140 | 170 | 455 |
| Guitar Paths | Shared guitar credit | 119/140 | 109 | 196 |

All three clear the launch floor by a wide margin — this was not a close
call requiring a "defer" outcome. Behind the Glass has the best one-hop
coverage (roughly double Guitar Paths) and the broadest album coverage
(137/140 = 98%), and maps directly onto ADR 0047's `RoleCategory.PRODUCTION`/
`RoleCategory.ENGINEERING` taxonomy exactly as designed — Rhythm Section and
Guitar Paths both needed to fall back to `eligibility.py`'s fine-grained
tokens (`drums`/`bass`, `guitar` specifically) since the taxonomy's coarser
`PERCUSSION_KEYS`/`STRINGS` buckets are broader than either mode wants.

## Decision

Ship **Behind the Glass**: find a documented producer/engineer/mixer chain
connecting two records, where *every* hop — not just one along the way — is
itself a producer/engineering credit.

**Scope decision — extend Connect Two Records, not a new mode/page.** The
plan's own description of Behind the Glass ("find the producer / engineer /
mixer connecting two records") is exactly Connect Two Records' pathfinding
mechanic (ADR 0051), restricted to a role-filtered traversal. Rather than
building a second round-based game mode duplicating
`connection_rounds.py`'s machinery (a much larger, riskier surface — that
module is the flagship Connection Guesser's most-trafficked, most-tested
code, and forking or parameterizing it for a second mode was judged
higher-risk than the value justified for this slice), Behind the Glass ships
as a checkbox toggle on the existing `/play/connect/` page:

- Reuses the **same published artifact**
  (`apps/web/public/data/pathfinding/graph.v1.json`) — no new artifact,
  contract, or versioning concept needed, since the pathfinding graph
  already carries `edge_role_a`/`edge_role_b` per edge.
- `apps/web/src/game/roleTaxonomy.ts` (new) — a narrow TypeScript port of
  `role_taxonomy.py`'s `_PRODUCTION_TOKENS`/`_ENGINEERING_TOKENS` (not the
  full `RoleCategory` taxonomy — only the one predicate this feature needs):
  `isEngineeringOrProductionRole`, `behindTheGlassEdgeFilter` (requires
  *both* endpoints of an edge to qualify).
- `apps/web/src/game/pathfindingGraph.ts`'s `findPath` gained an optional
  `edgeFilter` parameter (`(roleA, roleB) => boolean`), applied per
  candidate edge during BFS traversal — a minimal, additive change; the
  unfiltered call sites (existing Connect Two Records searches) are
  unaffected since the parameter defaults to `undefined`.
- `packages/graph-core/src/networked_players_graph_core/
  eligibility_engineering.py` (new) — the Python-side mirror,
  `is_engineering_or_production_role`, a thin wrapper over
  `role_taxonomy.classify_role` (not a hand-duplicated token list, per ADR
  0039's pattern) rather than a hand-maintained token set of its own. Not
  currently called by any artifact builder (the shipped feature is a
  client-side filter over the already-published graph) — kept for
  consistency with the measurement tool and as the natural extension point
  if a future backend-generated Behind the Glass artifact is ever needed.
- When the toggle is checked, the "more musical route" re-ranking section is
  hidden — every hop is already producer/engineer-only by construction, so
  `routeQuality.ts`'s role-signal re-ranking has nothing to add.
- Failure copy is mode-aware: "no producer/engineer-only connection was
  found" vs. the unfiltered "no documented connection was found," so a
  visitor doesn't read the filtered miss as a broken search.

## Consequences

- No new public artifact, contract, or `PUBLIC_ARTIFACT_GROUPS` entry — the
  entire feature is a client-side filter over data already published and
  validated for Connect Two Records.
- The role-filtered search may find **no path** far more often than the
  unfiltered search, even between catalog albums, since most credits aren't
  producer/engineering credits — this is an expected, honest outcome of a
  narrower filter, not a bug.
- If a future slice wants Rhythm Section or Guitar Paths, the measured
  counts above (170/455 and 109/196 respectively) already clear the launch
  floor too — the same toggle-based extension pattern applies directly
  (add the matching token predicate to `roleTaxonomy.ts`, no new backend
  work required).

## Validation

`packages/graph-core/tests/test_role_mode_candidates.py` (6 tests, all three
modes, one-hop and two-hop cases). `packages/graph-core/tests/
test_eligibility_engineering.py` (fail-closed default, real token
recognition). `apps/web/tests/game-roletaxonomy.spec.ts` (pure-node: token
recognition, `behindTheGlassEdgeFilter`, `findPath`'s `edgeFilter`
restricting traversal on a fixture graph). `apps/web/tests/
game-connect.spec.ts` gains two real, artifact-verified cases: Ziggy
Stardust (David Bowie) ↔ A Night at the Opera (Queen) — a real direct
shared-Producer edge in the committed pathfinding graph — finds a path
under the toggle; Discovery (Daft Punk) ↔ The Joshua Tree (U2) — whose real
direct edge is a plain "Credited artist" credit, with no producer/
engineering-only bridge within 4 hops either, confirmed by walking the
committed artifact directly — reports no connection under the toggle,
distinct from the unfiltered no-path/fetch-failure copy.

## Revisit trigger

~~If a future slice adds a second role-filtered mode (e.g. Rhythm Section),
and the toggle-per-mode pattern starts feeling cramped on a single page,
that's the signal to extract a shared "filtered connect" component rather
than adding a third checkbox to this one.~~

**Addendum (Phase 2 follow-up slice): this trigger fired.** Rhythm Section
and Guitar Paths shipped, using their already-measured counts from the
table above (170/455 and 109/196), which clear ADR 0043's launch floor by
the same wide margin Behind the Glass did. The call: **stay on one page,
switch checkboxes for a radio group** rather than extracting a shared
component or splitting into separate pages. Reasoning — all three modes
are the exact same mechanic (a role-filtered BFS over the identical
published graph) with only the edge predicate and copy differing; a
four-line `Record<string, RoleFilterMode>` table in `connect.ts` (label →
`edgeFilter` → no-path message) captures that difference without
duplicating the search/render/failure-handling logic three times. A radio
group (not independent checkboxes) makes "exactly one filter active, or
none" the HTML's own invariant rather than something `connect.ts` has to
enforce by hand. If a future mode needs meaningfully different UI (e.g. a
mode that isn't just "restrict this edge predicate," but changes what a
hop even renders), that's the next, different trigger to revisit this
decision — not simply "a fourth mode exists."

- `apps/web/src/game/roleTaxonomy.ts` gained `isRhythmSectionRole`/
  `isGuitarRole` (wrapping `eligibility.py`'s fine-grained
  `_ROLE_CATEGORY_BY_TOKEN` display-category tokens for drums/bass/guitar
  specifically — the same reason Rhythm Section/Guitar Paths needed
  `_fine_grained_role_predicate` rather than `role_taxonomy.classify_role`
  in the measurement tool, per the Context section above) and matching
  `rhythmSectionEdgeFilter`/`guitarPathsEdgeFilter`.
- `packages/graph-core/.../eligibility_rhythm_section.py` and
  `eligibility_guitar_paths.py` (new) — Python-side mirrors, same
  "not currently called by any builder" caveat as `eligibility_engineering.py`.
- Real test pairs (found by walking the committed pathfinding graph
  directly, same method used for the original Bowie/Queen pair): Rhythm
  Section has no direct one-hop pair among the 140 catalog albums' main
  artists — "Face Value" (Phil Collins) ↔ "Talking Book" (Stevie Wonder) is
  a real two-hop path bridged by Nathan East (bass/drums on both hops).
  Guitar Paths has a real one-hop pair: "Blood On The Tracks" (Bob Dylan)
  ↔ "Harvest" (Neil Young), a shared "Guitar, Vocals" credit. Discovery ↔
  The Joshua Tree (the original Behind the Glass negative case) has no
  rhythm-section- or guitar-only bridge within 4 hops either, confirmed
  directly against the artifact — reused as the negative case for both new
  modes too.

**Addendum (2026-08-09, ADR 0058): backend moved to v2; the Discovery ↔
Joshua Tree negative case above no longer holds.** This ADR's "same
published artifact" decision reused `graph.v1.json`'s raw edges, searched
from each album's single primary artist. Slice 7 moved Connect Two
Records (Behind the Glass/Rhythm Section/Guitar Paths included) onto
`graph.v2.json`'s virtual album-anchor nodes, which search from *every*
credited contributor on an album, not just its primary artist — a real,
strictly more capable search. Discovery ↔ The Joshua Tree, verified above
as having no role-filtered bridge under the old artist-only search, was
directly re-verified against the real committed v2 artifact to now have
real bridges under all three role filters via other credited
contributors — it stopped being a valid negative case, not a bug.
Replaced with Time Out (Dave Brubeck) ↔ Rumours (Fleetwood Mac), verified
to have a real unfiltered connection but no bridge under any of the three
role filters within budget. See `apps/web/tests/game-connect.spec.ts` and
ADR 0058's own Slice 7 record.
