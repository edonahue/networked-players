# ADR 0064: Traversal role policy — album anchors and film/video credits

- **Status:** Accepted
- **Date:** 2026-08-27
- **Depends on:** [ADR 0027](0027-exclude-non-performer-roles-from-one-hop-frontier.md) (the "every component must match" rule this reuses), [ADR 0035](0035-track-scoped-credit-edges.md) (`credit_edges_sql`'s edge semantics), [ADR 0047](0047-role-taxonomy-as-a-third-orthogonal-classification-layer.md) (the taxonomy this adds a category to), [ADR 0050](0050-browser-pathfinding-architecture-selection.md) and [ADR 0058](0058-album-credit-membership-and-evidence-registry.md) (album anchors and the membership artifact), [ADR 0059](0059-recommended-route-selection.md) (the ranker this deliberately does not change)

## Context

A real Connect Two Records result prompted this: **Discovery — Daft Punk →
The Joshua Tree — U2** recommended a route through **Alex And Martin**,
credited `Design Concept, Art Direction` on Discovery and `Film Director` on
a 2005 U2 single. The route is documented and truthfully described, and the
engine's caveat ranking was working correctly — it demoted the only
alternative, a 1998 Italian bootleg mashup carrying an `unofficial` flag.
But "the sleeve designer of one record also directed a video for the other"
is not the kind of documented musical connection the product is for.

Reproduced independently against the published `graph.v2.json` before
changing anything. The shortest layer held exactly two candidates, and the
ranker picked correctly *given the edges it was handed*. **The scorer was
right; the edge sets were wrong**, in two independent places.

### (A) Album-anchor edges bypassed the role-eligibility rule

`graph.py`'s `_NON_COLLABORATIVE_ROLE_TOKENS` already contains both
`design concept` and `art direction`, so a contributor-to-contributor edge
carrying that exact role text has never been eligible. But
`pathfinding_graph.py` built one album-anchor edge per
`album_credit_membership` credit with no filter at all.

That artifact is *correctly* inclusive — it is an album's credits list, and a
sleeve designer belongs on the album page. Turning it 1:1 into a **traversal**
edge set was the gap. The same credit cannot be non-collaborative in one edge
class and a first-class routing hop in another.

### (B) Film/video-production tokens were missing from the denylist

`film director` was not in the denylist, so the every-component rule kept the
bridge edge eligible. The comment above that set already conceded the list
"can only under-filter." `role_taxonomy.py` carried a matching note naming
*Film Director, Director Of Photography, Film Producer, Film Editor, Video
Editor* explicitly, saying the taxonomy's categories "have no honest home for"
them and deferring the question to "a future pass if it's ever justified."

## Decision

**1. Album-anchor edges apply the same role-eligibility rule as every other
edge — evaluated per credit, not on the joined display role.**

`pathfinding_graph.edge_eligible_membership_artist_ids()` reuses `graph.py`'s
own `edge_ineligible_role` (never a second copy) and keeps an artist when
**any** of their credits on that album is edge-eligible, dropping them only
when **every** one is non-collaborative.

Granularity is the whole decision. Filtering on the single joined display role
instead would detach nine real catalog albums from **their own billed artist**
— measured: Bob Dylan from *Blood On The Tracks*, U2 from *The Joshua Tree*,
Wu-Tang Clan from *36 Chambers*, Joni Mitchell from *Blue*, and five more —
because the joined text happens to read `Written-By` or `Composed By`. A
billed artist's `release_artist` credit carries a NULL role, and
`edge_ineligible_role(None)` is `False` (the same always-eligible main-artist
rule `credit_edges_sql` applies), so per-credit evaluation keeps them.

**2. Film/video-production tokens join the denylist, and get an honest
taxonomy category.**

Thirteen tokens added: `film director`, `film producer`, `film editor`,
`cinematographer`, `camera operator`, `director of photography`,
`film technician`, `video director`, `video editor`, `lighting director`,
`creative director`, `choreography`, `choreographer`.

Deliberately **not** added: `directed by` (a bare `Directed By` is ambiguous —
`Directed By [Musical Director]` is a real musical role and the bracket
qualifier is stripped before lookup) and `music director` (musical direction of
a band or orchestra is a genuine musical contribution).

These become `RoleCategory.AUDIOVISUAL_PRODUCTION`, non-traversable — a new
category rather than a stretch of `PACKAGING_BUSINESS`, because a
cinematographer made a film, and labelling that "Packaging & Business" on a
contributor page would be false. This is the "future pass" `role_taxonomy.py`'s
own note anticipated, and it arrives with the measurement that note asked for.

## Measurement

All figures measured against the real published artifacts before the change.

**Anchor edges (A):** 1,219 of 5,446 (album, artist) anchor pairs dropped
(22.4%). **Zero albums lose their primary artist. Zero albums are left with no
anchors.** Lowest surviving count is Elvis Presley's 1956 debut at 1 — correct,
not a defect: that record's Discogs credits genuinely are almost all
songwriters and photographers.

**Denylist (B):** 3,564 of 121,392 contributor-to-contributor edge slots become
ineligible (2.94%), across 432 distinct role strings, touching 1,599 of 36,959
nodes. The top strings caught are exactly `Film Director` (683),
`Film Producer` (442), `Film Editor` (220), `Camera Operator` (140),
`Creative Director` (136), `Director Of Photography` (121).

The every-component rule protects the case that matters: a musician who also
directed the video (`Acoustic Guitar, Producer, Vocals, Film Director`) keeps
every edge, because `acoustic guitar` is not in the set. This change can still
only under-filter, never over-filter.

**The prompting route, after both fixes.** The two-contributor layer holds one
candidate — the bootleg mashup, worst caveat tier. The recommended-route
engine's existing +1-hop escape hatch then fires exactly as ADR 0059 designed
it, and the pick becomes:

> Discovery → George Duke → Quincy Jones → Bono → The Joshua Tree

all hops clean-evidenced. **No change to the ranker was needed or made.**

## Consequences

- Album anchors get sparser and more honest. The route timeline stops
  presenting packaging credits as connective tissue.
- `audiovisual_production` is additive everywhere: the contributor-index
  validator's vocabulary accepts it alongside every existing value, so the
  already-published artifact stays valid and the next regeneration may use it.
  `apps/web`'s `ROLE_CATEGORY_LABEL` gains "Film & Video" and a drift test.
- **No artifact is regenerated by this ADR's implementing PR.** The published
  set stays internally consistent (it was built together); it is simply built
  by older code until the Phase 7 catalog expansion regenerates everything. The
  measured deltas above are what that regeneration will produce.
- Contributors who *only* ever held film/packaging credits will drop out of
  routing on regeneration. They remain on album pages and in the evidence
  registry — this changes traversal, not the record of who was credited.

## Alternatives rejected

- **Hard-code or denylist the specific pair, person, or release.** Refused
  outright: it fixes one URL and hides the class of defect.
- **Change the route scorer.** The scorer was correct at every step. Changing
  it would have masked an edge-set problem in a ranking layer.
- **Filter anchors on the joined display role.** Simpler, and wrong — it
  detaches nine albums from their own billed artist (measured above).
- **Put the film tokens in `PACKAGING_BUSINESS`.** Avoids a new category at the
  cost of telling users a cinematographer is packaging. Rejected.
- **Wire `CATEGORY_TRAVERSABLE` into `graph.py` as a gate.** Explicitly
  forbidden by ADR 0047, and not needed: the denylist is the gate, and the
  taxonomy stays a documentation layer over it.

## Validation

- `packages/graph-core/tests/test_pathfinding_graph.py`:
  `test_packaging_only_membership_credit_creates_no_anchor_edge` (the reduced
  form of the real defect),
  `test_a_billed_artist_keeps_its_anchor_edge_despite_a_non_collaborative_role`
  (the nine-album regression this decision's granularity exists to prevent),
  `test_edge_eligible_membership_artist_ids_keeps_an_artist_with_any_eligible_credit`.
- `packages/graph-core/tests/test_graph.py`: the new film/video assertions in
  `test_edge_ineligible_role_matches_the_sql`, including the two that must NOT
  become ineligible (`Acoustic Guitar, Producer, Vocals, Film Director`,
  `Music Director`). The new role strings are also added to
  `ROLE_PARITY_CASES`, so SQL/Python agreement is pinned on them too.
- `packages/graph-core/tests/test_role_taxonomy.py`:
  `test_non_collaborative_tokens_are_fully_partitioned` now checks four
  mutually-disjoint sets whose union is the denylist, so any future denylist
  addition that isn't triaged still fails loudly.
- `apps/web/tests/game-roletaxonomy.spec.ts`: `ROLE_CATEGORY_LABEL parity` —
  a category the Python taxonomy emits but the web doesn't label would
  silently lose its contributor-directory filter chip.
- Full `make check` and the complete Playwright suite at normal concurrency.
- The measurement figures in this ADR were produced read-only against the
  committed artifacts and are reproducible from them; per
  [ADR 0018](0018-benchmark-results-local-only.md) they are structural counts,
  not machine-specific timings, so they belong in this public record.

## Revisit trigger

- **A real album left with too few anchors to route.** Elvis Presley's 1956
  debut drops to a single surviving anchor. If a future catalog addition lands
  at zero, that is this decision over-reaching, not a data problem — revisit
  whether album-anchor eligibility needs its own, looser rule than
  contributor-to-contributor eligibility rather than sharing one.
- **A denylist token turning out to be musical in practice.** `creative
  director` is the least clear-cut of the thirteen; if real corpus evidence
  shows it naming a musical role with any regularity, drop it. The
  every-component rule means each token can only under-filter, so removing one
  is always safe.
- **`Presenter`/`Interviewee` or another broadcast/spoken-word class becoming
  frequent enough to matter.** They stay `unknown` deliberately; a measured
  case would justify either extending this category or adding a sibling.
- **Any proposal to consult `CATEGORY_TRAVERSABLE` as a gate.** Still forbidden
  by ADR 0047. If that ever looks necessary, it is an ADR, not a patch.
