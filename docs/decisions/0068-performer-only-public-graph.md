# ADR 0068: Public connections mean documented musical performance

- **Status:** Accepted (policy and audit only in this addendum; graph-construction
  cutover ships in follow-on PRs, tracked below)
- **Date:** 2026-09-01
- **Supersedes:** [ADR 0039](0039-performer-allowlist-layered-for-game-rounds.md)'s
  "must never be imported by `graph.py`, `challenge.py`, or the cohort pipeline"
  restriction, for `eligibility.py` specifically
- **Extends:** [ADR 0035](0035-track-scoped-credit-edges.md),
  [ADR 0047](0047-role-taxonomy-as-a-third-orthogonal-classification-layer.md),
  [ADR 0058](0058-album-credit-membership-and-evidence-registry.md),
  [ADR 0059](0059-recommended-route-selection.md),
  [ADR 0060](0060-interesting-next-step-signal.md) without modifying any of them

## Context

The owner made a product decision: the public graph's connections must mean
"these artists or groups are documented as performing on the same recording or
release," not "these names appear somewhere in the same release's credits."
PR #202 (merged, `main` at `000a506`) added real mitigation for the narrowest
slice of this problem -- rank-lowering, Explore dimming, and a
`background-only-profiles.v1.json` companion artifact for Mastered By/Recorded
By/Mixed By-only connections -- but left `graph.py`'s `credit_edges_sql`
untouched. Verified live before this work started: Stuart Hawkes
(`/contributors/300468/`) bridges *The Dark Side Of The Moon*, *Synkronized*,
*Post*, and *1989* purely through mastering credits; `/play/connect/` offers a
*Dark Side Of The Moon → Synkronized* alternate through Chris Thomas/Rod
Stewart/Simon Hale reporting zero performer-bridged hops; the homepage
promotes a Behind the Glass producer/engineer-only route as a representative
public connection. Every non-performing role -- Producer, Engineer, Conductor,
Arranged By, Written-By, and (the largest bucket by far) a bare release-artist
billing with no role text at all -- remains fully edge-forming today.

**The three-layer role model this decision changes.** ADR 0035 built
`credit_edges_sql` as a *denylist* (`_NON_COLLABORATIVE_ROLE_TOKENS`): an edge
forms unless a role is composition/packaging-business/rework/
audiovisual-production, on the theory that "did these two people plausibly
share a recording session" is the right question for the album challenge and
cohort surfaces, where a bare Producer or Mixed By credit should keep counting.
ADR 0039 then built `eligibility.py`'s `is_performer_role` as a narrower
*allowlist* -- "did this specific person sing or play an instrument" -- fail-
closed in the opposite direction, and explicitly walled it off: "This module
must never be imported by `graph.py`, `challenge.py`, or the cohort pipeline --
only by game-round candidate generation. Narrowing what counts as a 'playable
identity' for the game must not silently narrow the cohort's or album
challenge's broader graph exploration." ADR 0039's own Revisit trigger even
anticipated a version of this moment: "a third fail-closed rule layered the
same way is a signal to extract a shared helper, not to relax
`credit_edges_sql`'s denylist." The owner's decision goes further than that
anticipated revisit -- not a third layered rule, but retargeting the *public*
graph's own core rule at the same narrower definition ADR 0039 built for the
game. That is a real, deliberate reversal of ADR 0039's protective boundary,
made explicitly here rather than left to accumulate as silent drift.

## Decision

**One canonical performer-participation policy, applied at the graph-
construction layer, `credit_scope`-aware:**

- `track_artist` or `release_artist` billing (a credit's *billing* scope,
  regardless of role text, including a bare `NULL`-role main-artist billing)
  is always implicit performer-qualifying. This is the correct treatment of
  "main-release album anchors," "groups and bands billed as artists," and "a
  release's primary billed artist's own record" that the task requires --
  literal reuse of `eligibility.py`'s existing `NULL` → `False` default would
  wrongly disconnect the primary billed artist from their own record, so
  billing scope never goes through that check at all.
- `track_credit` or `release_credit` scope (an "extra credit" row -- producer,
  engineer, mixer, mastering, designer, etc., entered against a track or
  release but never a billing) must pass `eligibility.py`'s existing
  `is_performer_role`/`is_performer_role_sql` to be edge-forming.

This is a `credit_scope`-aware *application* of an existing, already-tested
predicate, not a second definition. `eligibility.py`'s file location, token
set (expanded below), and `NULL`-excluded behavior are otherwise unchanged.

**Mechanically, the follow-on implementation PR will change exactly two of
`credit_edges_sql`'s three CTEs** (`packages/graph-core/.../graph.py`) --
**not this PR, which touches neither `graph.py` nor `pathfinding_graph.py`
at all** (see Consequences: no production cutover ships here):
- `co_performers` will need **no change**. Both its endpoints are
  `track_artist` scope -- inherently strong implicit-performance evidence
  already.
- `same_recording` and `release_scope` will each gain one new condition on
  their non-anchor side: that side's row must pass `is_performer_role`
  whenever its `credit_scope` is `track_credit` or `release_credit` (the only
  two scopes that ever reach that position in either CTE, confirmed by
  inspection of the join conditions). The anchor side
  (`track_artist`/`release_artist`) will be untouched.

`pathfinding_graph.py`'s `edge_eligible_membership_artist_ids` (which decides
who an album's virtual anchor node can reach -- exactly as load-bearing as
`credit_edges_sql` for what Connect/Explore can search "from this album")
will get the identical `credit_scope`-aware upgrade; `album_credit_membership.v1.json`
already carries `credit_scope` per credit today, so no artifact shape change
is needed to support it when that PR lands.

**ADR 0039's "must never be imported by" restriction is superseded, for
`eligibility.py` specifically, by this ADR.** The concern it protected against
-- the game's narrower rule silently narrowing the album/cohort surfaces'
broader graph -- is now moot by the owner's own product decision: the public
graph is meant to ask the same narrower question `eligibility.py` already
answered for game rounds. The follow-on implementation PR will have
`graph.py`, `challenge.py` (via `CreditGraph.find_path` traversing the then-
gated `credit_edges`), and the cohort pipeline (`cohort_connectivity.py`,
which will retire its own local, duplicate `_is_non_performer_role` in favor
of this shared predicate) all import `eligibility.py` directly. **This
addendum only lifts the restriction and revises `eligibility.py`'s own
module docstring to state that plainly rather than leaving the old
restriction looking authoritative -- `graph.py`, `challenge.py`, and
`cohort_connectivity.py` do not yet import `eligibility.py` as of this PR**
(see Consequences below: no production cutover ships here). `role_taxonomy.py`
remains presentation-only exactly as ADR 0047 requires -- it is not on this
import path and does not gate anything; the new performer gate will live in
`graph.py`/`pathfinding_graph.py` importing `eligibility.py` directly, never
through `role_taxonomy.py`'s `RoleCategory`/`classify_role`.

**Allowlist expansion is measured, not guessed.** Ran `is_performer_role_sql`
against the full public one-hop corpus (`local/processed/discogs-v3-full`,
220M credit rows) as a real baseline before touching the token set. Real,
currently-unrecognized-by-either-list tokens with real scale, added with a
per-token real-corpus-count comment in `eligibility.py` (same convention the
existing 2026-08-04 additions use):

| Group | Tokens added | Representative real counts |
|---|---|---|
| Voice, range-qualified | soprano/tenor/alto/baritone/bass vocals | 229,273 / 194,549 / 53,625 / 88,876 / 107,351 |
| Voice, other | human beatbox, whistling, **featuring** | 3,718 / 4,672 / **3,221,801** |
| Generic/ensemble | performer, musician, instruments, orchestra, strings, soloist | 999,112 / 220,705 / 47,705 / 1,116,885 / 309,116 / 118,061 |
| Turntablism | turntables, scratches | 12,800 / 97,466 |
| Strings, additional | concertmaster, zither, dulcimer, bouzouki, kora, autoharp, dobro | 32,339 / 5,255 / 4,996 / 17,043 / 2,911 / 4,872 / 24,596 |
| Percussion/keys, additional | tambourine, cowbell, steel drums, theremin, moog, mellotron, clavinet, rhodes, wurlitzer, vocoder, talk box | 41,907 / 5,395 / 6,424 / 4,628 / 11 / 12,573 / 17,483 / 43 / 30 / 4,220 / 3 |
| Woodwind/breath, additional | recorder, didgeridoo, whistle, melodica, kazoo | 22,951 / 5,588 / 8,208 / 5,965 / 2,330 |

**"Featuring" (3,221,801 rows) is the single largest addition and deserves its
own justification.** Real compound-credit co-occurrence data --
`"Vocals, Featuring"` (7,318 rows), `"Rap [Featuring]"` (51,438 rows),
`"Featuring [Vocals]"` (9,812 rows) -- confirms "Featuring" is Discogs' real-
world convention for a guest performer's own billing, used interchangeably
with explicit vocal/rap credits, not a mere name-check. Excluding it would
disconnect a very large fraction of real hip-hop/pop guest-verse
collaboration, directly contrary to the task's own requirement to cover
"rock, pop, electronic, jazz, soul/R&B, and hip-hop" credibly.

**Explicitly considered and excluded** (kept fail-closed), with reasoning:

- **Conductor** (1,119,397) / **Orchestrated By** (114,331) -- directing or
  arranging a performance is not itself performing. `role_taxonomy.py`
  currently buckets `Conductor` under `ARRANGEMENT`; `Orchestrated By` is not
  yet in `_ARRANGEMENT_TOKENS` and classifies as `UNKNOWN` today. Either way,
  neither is a performer-eligibility token, which is the only claim this
  decision makes -- `role_taxonomy.py`'s own bucketing of `Orchestrated By` is
  a separate, unaudited presentation-layer question this PR does not disturb.
- **Programming** (123) / the much larger **Programmed By** (already excluded,
  unaffected) -- a production/engineering process, not a real-time performance
  act.
- **Sampler** (11,871) -- genuinely ambiguous between "played the sampler as
  an instrument" and "sampled other people's recordings" (a rework/production
  technique); the text alone cannot disambiguate, so it stays excluded rather
  than guessed, per this project's standing rule against inferring from
  context.
- **Cover** (253,766, 98% release-scope) -- overwhelmingly a truncated
  packaging credit (cover art/design), not a performance.
- **Leader** (76,602) -- too generic across real contexts (band-leader vs.
  directorial) to safely assume performance either way.

**A new, honest `RoleCategory.PERFORMANCE`** is added to `role_taxonomy.py`
for the generic/ensemble tokens above (performer, musician, instruments,
orchestra, strings, featuring, soloist, turntables, scratches, whistle,
vocoder, talk box) -- these are real, confirmed performance credits that do
not name a specific instrument or vocal range, so classifying them as
`UNKNOWN` would be dishonest (we know they ARE a documented performance, just
not which kind), and forcing them into `VOCALS`/`STRINGS`/`PERCUSSION_KEYS`/
`BRASS_WOODWIND` would fabricate an instrument the credit itself doesn't name.
`CATEGORY_TRAVERSABLE[PERFORMANCE] = True` (unchanged from today's real
behavior for these tokens, none of which was ever denylisted).
`packages/contracts/.../contributor_index.py`'s `_VALID_ROLE_CATEGORIES` and
`apps/web/src/data/contributors.ts`'s `ROLE_CATEGORY_LABEL` are updated
alongside, purely additively, matching the precedent
`RoleCategory.AUDIOVISUAL_PRODUCTION` (2026-08-27) already set.

**`is_performer_role`'s plain (non-bracket-aware) comma split is deliberately
NOT changed to bracket-aware splitting**, despite that pattern existing
elsewhere in this codebase (`role_taxonomy.py`'s `_ROLE_COMPONENT_SPLIT`,
`is_background_engineering_role`). Real corpus review of bracket-qualified
compound credits (`"Arranged By [Rhythm, Vocals]"`, 893 rows; `"Producer
[Vocals, Additional]"`, 892 rows) found these bracket qualifiers predominantly
describe the SCOPE of the non-performer base role (what was arranged, what was
produced), not independent performer evidence -- bracket-aware splitting here
would introduce false positives (crediting an arranger as a vocalist), not fix
a false negative. This is a considered non-change, not an oversight.

**TypeScript parity.** `apps/web/src/game/roleTaxonomy.ts`'s `PERFORMER_TOKENS`
receives the identical 39-token expansion (69 → 108), verified byte-for-byte
equal to `eligibility.py`'s `_PERFORMER_ROLE_TOKENS` (108 tokens on both
sides). A
pinned parity test (`apps/web/tests/game-roletaxonomy.spec.ts`, "ADR 0068
audit") exercises every included and excluded token so a future one-sided edit
fails loudly, the same convention this file's header already documents for
the three role-filter-mode token sets.

## Consequences

- This addendum lands with **no production cutover**: `credit_edges_sql`,
  `pathfinding_graph.py`, and every public artifact are unchanged by this PR.
  Only `eligibility.py`'s token set/docstring, `role_taxonomy.py`'s new
  category, and their downstream display-layer mirrors change. The graph-
  construction change itself (the two-CTE edit described above) and the
  resulting artifact regeneration are the next PR's deliverable, building
  directly on the contract this ADR settles.
- `rounds.py`'s `build_round_hop` (Connection Guesser/Record Routes candidate
  generation) already calls `is_performer_role` -- the expanded token set
  takes effect for game rounds immediately once this PR merges, before the
  graph itself changes. This is measured, not incidental: three existing
  tests whose fixtures relied on the generic role text "Performer" being
  non-performer-eligible (`test_build_round_hop_rejects_bare_release_artist_billing`,
  `test_build_round_from_path_returns_none_when_any_hop_is_ineligible`,
  `test_build_rounds_from_dump_raises_when_no_eligible_rounds`) needed their
  fixtures rebuilt around a role that is still genuinely non-performer
  ("Producer") -- confirmed real ripple, not a hidden regression.
- No real committed public artifact changes shape or content in this PR.
  `validate-public-artifacts` passes unchanged.
- `cohort_connectivity.py`'s local `_is_non_performer_role` duplicate is
  retired in a follow-on PR once the shared predicate is confirmed to cover
  its existing real-data behavior -- not in this PR, to keep this PR reviewable
  independently of any cohort-pipeline behavior change.

## Validation

`packages/graph-core/tests/test_eligibility.py` (existing parity/allowlist
suite, all passing against the expanded set), `test_role_taxonomy.py` (new
`RoleCategory.PERFORMANCE` classification, including the reclassified
"Featuring" case), `test_rounds.py`/`test_cli_rounds.py` (three fixtures
rebuilt around a still-genuinely-non-performer role, fail-then-pass
confirmed). `apps/web/tests/game-roletaxonomy.spec.ts`'s new "ADR 0068 audit"
test pins every included/excluded token on the TypeScript side. Full
`make check` (1,450 Python tests), `npm run check`/`format:check`, and the
full Playwright suite (532 passed, 3 pre-existing skips) all green against
this PR with zero real committed artifact changes.

## Revisit trigger

If a future measurement shows a real, currently-excluded role string
(Conductor, Sampler, Leader, or a token not yet reviewed) is common enough on
real catalog content to be worth reconsidering, revisit it the same way this
ADR's own audit did -- real corpus counts, explicit reasoning, a pinned test --
never by relaxing the fail-closed default for something unmeasured. If the
graph-construction cutover (next PR) measures a materially different real
retained-edge count than this ADR's token additions alone would predict,
that is expected (billing-scope implicit performance is the larger structural
change) and should be reported honestly in that PR's own shadow-diagnostic,
not treated as a contradiction of this ADR.
