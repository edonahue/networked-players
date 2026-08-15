# ADR 0059: Recommended documented route selection

- **Status:** Accepted
- **Date:** 2026-08-14
- **Depends on:** [ADR 0035](0035-track-scoped-credit-edges.md), [ADR 0050](0050-browser-pathfinding-architecture-selection.md), [ADR 0051](0051-connect-two-records.md), [ADR 0053](0053-role-aware-game-mode-selection.md), [ADR 0054](0054-research-lane-and-promotion-boundary.md), [ADR 0058](0058-album-credit-membership-and-evidence-registry.md)

## Context

Connect Two Records shows whichever route BFS touches first. That is not a
choice about quality; it is an accident of data layout. Searching the real
production pair *Discovery* (Daft Punk) → *The Joshua Tree* (U2) returns a
route through a contributor displayed as **`u2`**, evidenced by a **1998
Italian mashup 12″** (*With Or Without You Vs. Da Funk / Your Love Vs. Mr
Gorgeous*, release #200783). Mathematically valid; indefensible as the
default story the product tells.

Four independent causes were traced to source, not assumed:

1. **The evidence release for every artist pair is `min(release_id)`** —
   the lowest Discogs *database id*, decided in `graph.py`'s
   `credit_edges_sql` (`SELECT artist_a_id, artist_b_id, min(release_id)
   ... GROUP BY artist_a_id, artist_b_id`) long before the pathfinding
   graph is built. Lowest id correlates with "catalogued earliest", which
   skews toward early-listed 12″ singles, mashups and bootlegs. **Measured:
   0 of 65,133 pairs in the published graph retain any alternative** — the
   multiplicity is destroyed upstream, so no client-side fix is possible.
2. **The display name per node is arbitrary.** `pathfinding_graph.py` runs
   `SELECT DISTINCT artist_id, name FROM linked_credits` and keeps whichever
   row DuckDB emits first via `setdefault`. `linked_credits` holds one row
   per credit, so an artist has as many spellings as contributors typed.
   **Measured: ~550 visibly broken names of 36,819** — 149 lowercase
   (`u2`, `george duke`, `michael jackson`), 198 ALL-CAPS
   (`THE ROLLING STONES`), 203 half-cased (`Carl perkins`, `Stevie wonder`).
3. **The route tie-break is "lowest Discogs artist id wins."** CSR
   neighbour lists are sorted by node index, node index is ascending
   `artist_id`, `findPath` marks `visited` at *discovery* (so the first
   parent to claim a node keeps it irreversibly), and it returns the moment
   any frontier node touches the goal — no candidate is ever compared.
4. **That tie-break is actively biased toward hubs.** The degree
   distribution is brutally heavy-tailed (71% of real nodes are leaves; 42
   nodes carry 500+ edges), and famous acts hold low Discogs ids — Elvis
   27518, Miles 23755, Bowie 10263, Clapton 17827. Ascending-id order
   therefore routes *through* exactly the hubs a quality policy would want
   to avoid.

An earlier scorer (`scorePath`) was removed in PR #104 as dead code. It must
not be revived as written: it keyed off `contributors/index.v1.json`, which
holds **549 entries covering 1.46%** of the graph's nodes. Bono is absent
from it entirely; Quincy Jones (real graph degree **983**) scores as "no
hub" there. The concept was fine; the signal had no coverage.

## Decision

**Rank a bounded candidate set instead of returning the first route found**,
using only source-derived signals, and fix the two builder-side causes at
their source rather than compensating for them in the client.

### The hub signal comes from the graph itself

Node degree is `offsets[i+1] - offsets[i]` — available in the browser, for
**100% of nodes**, at zero additional cost. This is the direct fix for what
made `scorePath` unusable, and it is why hub-awareness is viable now.

### Candidate enumeration is bounded and shortest-first

Enumeration uses distance-guided **iterative deepening**, not plain DFS: a
reverse BFS from the goal prunes any branch that cannot reach it within the
remaining budget, and routes are collected one exact depth at a time.

Deepening is not a refinement — it is required for correctness under a cap.
A deep-first walk filled a 200-route cap with long branches and then
reported a *shortest* of 2 hops for a pair that has a 1-hop route (caught
against the live artifact while building the measurement harness, now a
regression test). Truncation must only ever discard routes **longer** than
ones already held.

**A virtual album anchor is an endpoint, never an interior step.** Walking
through one would mean "album A to some other album's anchor to album B" —
not a contributor-to-contributor route — and since `stripAlbumAnchors` only
removes the first and last hop, an interior anchor would survive into the
rendered route as a synthetic "contributor" carrying the sentinel role.
Measured before this guard: 4 of 40 sampled pairs had their best equal-hop
route running through anchors, and all 4 inflated the hub-improvement
headline, because a synthetic anchor's degree is low next to a real hub.
Production's own `findPath` has no such guard, but was measured at **0 of
40** — an anchor detour is never the shortest route — so this is a latent
risk in the traversal contract rather than a live defect, and PR 3's engine
carries the guard explicitly.

The **shortest layer is additionally exempt from the route cap**, and its
completeness is reported rather than assumed. Every equal-hop statistic
below is computed over that layer, and a partially-enumerated layer is an
arbitrary CSR-ordered prefix, not a sample — capping it mid-depth would
silently undercount candidates and could miss the best route outright. When
the expansion cap does fire inside the shortest layer, the layer is flagged
incomplete and the derived hub claim is withheld instead of asserted.

### Measured bounds (real artifact, 40 stratified pairs, `local/research/`)

Pairs are sampled across degree terciles covering **every** stratum
combination (sparse/sparse through dense/dense). An earlier
complementary-rank pairing produced only sparse/dense pairs and biased
these figures; the numbers below are from the corrected sample, with all 40
shortest layers verified complete.

| Measurement | Result |
| --- | --- |
| Pairs where an **equal-hop** alternative strictly lowers the worst hub | **23 of 40 (57.5%)** |
| Shortest-hop distribution | 0 hops: 2 · 1 hop: 23 · 2 hops: 15 |
| Equal-hop candidates per pair | min 1 · **median 4.5** · max 157 |
| Shortest-layer forward walk (slots inspected) | **median 2,256.5** · max 84,240 |
| Reverse-distance precompute (slots scanned) | **max 125,975** — one pass per search |
| Precompute share of the whole bounded search | median **60.1%** · range 35.1–86.0% |
| Candidates within +1 hop (raised cap, see below) | **8,654** for the worst pair — an exact count |

Expansion counts here are **slots inspected**, charged before the pruning
checks rather than after. An earlier revision counted only the neighbours
that survived pruning, which on a heavy-tailed graph undercounted the
forward walk by roughly two orders of magnitude (it reported a median of
11.5 against a true 2,256.5) and made the precompute look like 98.8% of
the search when it is nearer 60%. The cap now bounds the work it claims to
bound.

Every figure above is printed verbatim by the `research-route-quality`
command, so the decision and its reproducible report cannot drift apart.
The first four rows come from the default invocation; the +1-hop row needs
`--max-routes` raised, because at the default 200 that layer saturates for
**26 of the 40 pairs** and reports a censored 200 for each:

```
networked-players-research research-route-quality --pairs 40 \
  --max-routes 20000 --max-expansions 5000000
```

Because enumeration is shortest-first, a cap firing at a deeper layer
leaves every shallower layer already complete. Whole-search truncation and
+1-layer saturation are therefore different facts and the report keeps them
apart: the default run truncates *somewhere* on all 40 pairs
(`truncated_pairs: 40`) while only 26 of those caps fire at or before the
+1 layer (`saturated_within_plus_one_pairs: 26`) — the other 14 finish that
layer and report exact counts below 200. At the raised cap above,
`saturated_within_plus_one_pairs: 0`, so **8,654 is an exact count** rather
than a lower bound.

Expansion and candidate counts are deterministic properties of the graph
and the algorithm — identical on any machine, so they belong here. Elapsed
time is a benchmark *result* and stays in `local/research/` per
[ADR 0018](0018-benchmark-results-local-only.md) and
`docs/PUBLIC_PRIVATE_BOUNDARY.md`; the reproducible method is the
`research-route-quality` command above, not a transcribed number.

Two conclusions follow directly, and neither was chosen by taste:

- **Enumerate the complete shortest layer.** Its worst case is 157 routes
  over 84,240 inspected slots — not free, but the same order as the
  ~126,000-slot `buildArtistIndex` pass the browser already performs on
  every load, and it is plain typed-array reads. Nearly three in five pairs
  improve with **no hop increase at all**, which is what that cost buys.
- **Both halves of the search must be bounded and cached, not just one.**
  The reverse precompute is the larger single component (median 60.1% of
  the whole search, up to 86%) and is per-GOAL, so PR 3 computes it once
  per search and reuses it across the recommended/shortest/alternate
  results rather than once per candidate. But the forward walk is not
  negligible either — up to 84,240 slots — so it keeps its own explicit
  cap rather than relying on the precompute to dominate. Production's
  `findPath` pays neither cost today because plain BFS needs no guide;
  completeness is what buys both, and the trade is defensible because each
  pass is linear and the expensive one is cached.
- **Treat any hop increase as exceptional and hard-capped.** The +1 layer
  reaches 8,654 routes for the worst measured pair — roughly 55x the
  shortest layer's worst case of 157 — so it may only be consulted when the
  shortest layer offers nothing, and never without a cap.

### Honest labels

- **"Recommended documented route"** — only because candidates are genuinely
  ranked. The shown explanation is generated from the same facts used to
  select it, never a parallel narrative.
- **"Shortest documented route"** — literal BFS distance, always available.
- **"Distinct alternate route"** — only for a genuinely edge-disjoint route.
- Never "more musical" or "best": nothing here could substantiate that.

### Out of scope, permanently

No LLM, embedding, vector, popularity, streaming or external-API signal. No
hidden blacklist — a release is only ever de-preferred by a published,
source-derived field the UI is willing to show the player. Nothing here
implies friendship, influence, collaboration intent or musical lineage; a
shared credit remains documented co-participation and nothing more.

## Consequences

- The evidence-release fix requires **regenerating `graph.v2.json`**, since
  the published artifact stores exactly one release per pair. Names are
  fixed in the same regeneration, using the `QUALIFY row_number() OVER
  (PARTITION BY artist_id ORDER BY count(*) DESC, name)` pattern
  `snapshot.py` already uses — most-credited spelling wins, deterministic,
  and it never transforms the source string, so `will.i.am`, `deadmau5`,
  `k.d. lang`, `P!nk` and `blink-182` survive intact. Generic title-casing
  is explicitly rejected for exactly that reason.
- Regeneration was expected to invalidate the pinned BFS parity goldens.
  **It did not, and the expectation was wrong**: `pathfinding-bfs-parity*.
  spec.ts` pin a synthetic five-edge fixture, not the published artifact,
  so no golden encodes the old tie-break. The web specs that do name
  `graph.v2.json` either serve a synthetic payload through `page.route` or
  assert structural properties. Nothing was re-pinned, because nothing
  needed to be — recorded here so the next regeneration does not go
  looking for a step that does not exist.
- The diagnostic pair is **not** fixed by hub-awareness: both of its
  equal-hop routes pass through the same node (`u2`, degree 928), so only
  the evidence-release axis discriminates there. This is why the phase does
  both, and why neither alone would have been enough.

### Measured outcome of the regeneration

Run against the 20260601 corpus. The pair-set invariant held on real data:
`node_ids`, `offsets`, `neighbors` and `album_virtual_nodes` are
**byte-identical**, 36,959 nodes and 65,133 edges before and after. Only
the representative release, the roles derived from it, and the display
names moved.

| Measurement | Result |
| --- | --- |
| Display names corrected | **790** of 36,959 (`u2` → `U2`, `Mfsb` → `MFSB`, `Patti labelle` → `Patti LaBelle`, `Paul Van Dyk` → `Paul van Dyk`) |
| Real (non-anchor) edges whose evidence carries a caveat | **42.3% → 27.5%** (−17,930 of 121,392) |
| — of which `reissue` | 27,642 → 14,260 |
| — of which `compilation` | 17,668 → 12,902 |
| — of which `unofficial` | 9,020 → 7,672 |
| Anchor-edge sentinel slots | 8,874, identical set, each still carrying its album's own `main_release_id` |
| Graph gzip | 2,233.85 KB → 2,243.06 KB (+0.41%) |
| Registry gzip | 338.60 KB → 359.37 KB (+6.1%), against that contract's own 1.8 MB revisit trigger |

Two honest caveats on those figures. First, an earlier comparison looked
up caveat flags in the *new* registry, which no longer lists the 3,728
release ids the old graph referenced and only the new one dropped; those
silently defaulted to "no caveat" and understated the improvement. The
table above resolves flags for the union of both graphs' ids straight from
the dataset. Second, the caveat tiers are ranked by severity (bootleg,
then container, then pressing) rather than as one flat "has any caveat"
test — not to repair a regression, but because a flat term lets a bootleg
and a reissue tie and fall through to the release-id tiebreak, which is
precisely the arbitrary choice this ADR exists to remove.

Build cost was measured rather than assumed, since the collapse changed
shape (a streaming `GROUP BY … min(release_id)` became a `DISTINCT` plus a
`row_number()` window whose ordering carries correlated subqueries). Both
paths were run against the real corpus at the CLI's default memory limit:
the `credit_edges` count is **identical at 2,584,126**, which is the
pair-set invariant confirmed a second way, and the ranked collapse costs
roughly a third more spill and wall time on an operation that **already
spilled several GB before this change**. Elapsed and peak-memory figures
stay in `local/research/` per [ADR 0018](0018-benchmark-results-local-only.md);
the operator-facing consequence — check free space on the dataset volume
before regenerating — is recorded in `docs/OPERATOR_SETUP.md`.

The diagnostic release #200783 still evidences its two edges: it is the
**only** release evidencing those pairs, so no re-selection could move
them. What changed is that it is now published as `unofficial`, which is
what lets PR 3 rank the route down and PR 5 caveat it honestly — the
evidence is never concealed or rewritten.
- Route quality can only improve as far as the published evidence signals
  allow. Format descriptors are reliable for *exclusion*, not confirmation
  (`docs/RELEASE_FORMAT_RESEARCH.md` measured 94.7% of a known
  false-positive population carrying only a bare `Album` descriptor), so
  they are used as caveats, never as a positive "this is a studio album"
  claim.

## PR 3: the recommended-route engine ships

`apps/web/src/game/recommendedRoute.ts` — client-side, no artifact change.
Enumerates the complete shortest virtual-node layer between two albums
(bounded, shortest-first, sharing one expansion budget between the
reverse-distance guide and the forward walk, exactly as measured above),
ranks it on evidence caveat severity, then CSR node degree, then role
substance (`roleTaxonomy.ts`'s new `isPerformerRole`, ported verbatim from
`eligibility.py`'s `_PERFORMER_ROLE_TOKENS`), with a canonical sorted-edge-
key tiebreak so two runs over the same graph always agree. The retired
`scorePath`'s failure was coverage (1.46% of nodes via
`contributors/index.v1.json`), not concept — degree is the same signal at
100% coverage, for free, from the CSR already in memory.

**Caveat tiers, ported from `graph.py`'s `EVIDENCE_CAVEAT_TIERS`** so the
release the builder already de-prefers when picking evidence is the same
one the ranker de-prefers when picking a route: unofficial (worst), then
compilation/mixed/sampler, then promo/reissue (mildest). A flat "has any
caveat" test cannot tell a bootleg from a reissue — the PR 2 severity-tier
fix exists for exactly this reason, and the ranker inherits it rather than
re-deriving a weaker version.

**The +1-hop escape hatch is real and narrowly scoped**: triggered only
when *every* shortest-layer candidate carries the worst caveat tier and a
strictly better-evidenced route exists exactly one hop further, sharing
the already-computed reverse-distance guide so it costs no second
precompute. When no better alternative exists at any depth, the honestly-
caveated shortest route is still returned — evidence is never concealed to
make a route look cleaner than it is.

**Safe fallback, satisfied structurally, not by caller discipline**: if
bounded enumeration cannot produce a real candidate (expansion budget
exhausted before the reverse precompute completes), `selectRecommendedRoute`
falls back to `findAlbumRoute`'s plain first-found result internally and
reports `rankingDegraded: true` — the caller never needs a separate
fallback path, and the label downgrades from "Recommended" to "Shortest"
accordingly (honest labels: the method that ran, not the outcome, decides
the claim).

**A real bug the diagnostic pair itself caught**: the first working version
of the engine conflated `albumIndex`'s virtual ARTIST id with a CSR NODE
INDEX, silently walking the wrong slot on every real query and returning
`no-path` for the diagnostic pair. A second, more subtle bug followed:
unlike `findAlbumRoute`, the engine did not exempt anchor edges from a
caller-supplied `edgeFilter`, which would have made any future
role-filtered use of this engine fail to leave the start album's anchor at
all — unreachable from today's one caller (role-filtered searches keep
using `findAlbumRoute` directly, unchanged) but a landmine in the exported
function regardless. Both are fixed and regression-tested.

**Scope decision, stated plainly**: role-filtered searches (Behind the
Glass, Rhythm Section, Guitar Paths) keep today's plain first-found BFS
unchanged in this PR. The edge filter already narrows every hop to one
credit type, a materially stronger constraint than ranking adds value
against, and the existing role-mode tests assert specific real-artifact
hop content this PR did not want to put at risk without its own dedicated
measurement. Extending ranking to role-filtered search is a scoped future
change, not an oversight.

**Measured against the real committed artifacts** (`graph.v2.json`,
`release-registry.v1.json`, this machine, Node 22, warm/post-JIT): the
diagnostic pair and the PR 1 research sample's worst pair
(master-24047/master-3878) both complete in ~34ms, neither exhausting the
400,000-slot shared budget (`shortestLayerComplete: true` for both) — see
`apps/web/tests/game-connect.spec.ts`'s "the diagnostic pair" test for the
live, real-artifact assertion that the recommended route no longer routes
through the bootleg mashup's evidence, and
`apps/web/tests/recommended-route.spec.ts` for the engine's own synthetic
unit suite (ranking axes, determinism, the anchor-exclusion invariant
verified to fail without its guard, hard caps, the +1-hop escape hatch in
both directions, and `computeRouteFacts`/`explainRoute`).

**Also retired in this PR**: `routeQuality.ts`'s `explainScore`, the
purely-descriptive (never selecting) narrator this repo already used for
the distinct-alternate route's explanation text. It read
`contributors/index.v1.json`'s `connection_count` for its own hub signal —
the same 1.46%-coverage problem `scorePath` had — so it is replaced by
`computeRouteFacts`/`explainRoute`, which both the recommended pick and
the distinct alternate now share, reading CSR degree instead.

### The first review pass: three findings, fixed before merge

1. **A truncated candidate set was silently ranked and still labeled
   "Recommended."** A route or expansion cap firing mid-enumeration left
   `candidates` non-empty but ARBITRARY — an accident of CSR walk order,
   exactly the bias this whole engine exists to remove — yet the code only
   checked `candidates.length === 0` before trusting `best`, never the
   layer's own `complete` flag it already computed. `rankingDegraded` is
   now `!shortestLayer.complete` (and `!plusOneLayer.complete` when the
   +1-hop pick is used) rather than hardcoded `false` on every success
   path. A test that exercised exactly this cap-truncation path had been
   asserting the bug (`rankingDegraded: false` with only 1 of 2 real
   candidates surviving a `maxRoutes: 1` cap) rather than catching it —
   rewritten to assert the honest, fixed behavior, plus a companion test
   confirming a cap that does NOT truncate stays genuinely ranked.
2. **The reverse-distance precompute over-scanned by a full extra layer**
   beyond even its own stated intent (`maxDepth + 1` passed where the
   forward walk only ever consults distances up to `maxDepth - 1`, and the
   code's own comment claimed only `maxDepth` was needed for later +1-hop
   reuse). Harmless for correctness, real for the shared expansion budget:
   on the worst measured pair already consuming 358,505 of 400,000 slots,
   an unneeded layer could be the difference between completing and
   spuriously exhausting the budget on a denser pair. Fixed to `maxDepth`.
3. **The evidence registry was fetched unconditionally on every search
   click**, including role-filtered searches (which never rank on it, only
   render with it) and any search that finds no route at all — a real
   network request the pre-ranking code never made in those cases. Fixed:
   the fetch now starts alongside the graph only for an unfiltered search;
   a role-filtered search defers it to after a route is confirmed, exactly
   matching pre-PR behavior. Two new real-artifact tests pin both sides:
   zero evidence fetches for a role-filtered search with no connection,
   exactly one once a route is found.

### A second review pass: three more findings

1. **The +1-hop escape hatch could still fire on a truncated shortest
   layer**, even after the `rankingDegraded` fix above: gating the LABEL
   on completeness didn't stop the CONTROL FLOW from evaluating "every
   collected candidate is worst-tier" over a partial set and searching +1
   hop on that possibly-false premise. A hostile fixture makes this
   concrete: three real 1-hop bridges exist, two unofficial and one CLEAN,
   ordered so a route cap of 2 truncates the layer to just the two
   unofficial ones before the clean one is ever found; a real clean 2-hop
   detour also exists. Unfixed, the engine finds "every candidate is
   worst-tier" (true only of the truncated pair), searches +1 hop, and
   promotes the 2-hop detour — overlooking the shorter, cleaner 1-hop
   bridge that the cap had excluded. Fixed by adding
   `shortestLayer.complete` to the escape hatch's own trigger condition,
   not just the final label.
2. **A release absent from an otherwise-populated registry was read as
   "no caveat" rather than "unknown."** The published GRAPH is cached in
   `sessionStorage` across page loads while the REGISTRY is always fetched
   fresh, so a session that spans a deploy can hold a graph referencing
   release ids a freshly-fetched registry doesn't cover — precisely the
   staleness pattern this ADR's own PR 2 section measured (3,728 ids the
   old graph referenced that a new registry didn't). Reading `?? 0` for a
   missing release repeated that mistake at query time. Fixed with a rule
   that only ever WIDENS what's reported, never narrows it: a route's
   `worstCaveatSeverity` downgrades from a would-be "0 (verified clean)"
   to `null` (unknown) when any hop's evidence couldn't be checked at all,
   but a REAL known caveat from another hop is never hidden behind that
   uncertainty — concealing a known bad signal because an unrelated one is
   unverifiable would itself violate "never conceal evidence."
3. **The reverse-distance guide was unfiltered**, so `shortestPossible`
   was always the UNFILTERED shortest depth even when a role filter was
   supplied. If the true unfiltered-shortest path's edges didn't satisfy
   the filter but a real, longer filter-compliant path existed within the
   hop budget, an exact-depth search at the (wrong) unfiltered depth found
   nothing and reported a false `no-path`. Unreachable from connect.ts
   today (role-filtered searches call `findAlbumRoute` directly, never
   this engine) but a real defect in the exported function's contract, in
   the same category as the anchor-edge exemption bug found earlier.
   Fixed by threading the same `anchorAwareFilter` into the reverse pass
   that the forward pass already uses — symmetric and correct because the
   CSR is undirected and a slot's own `edge_role_a`/`edge_role_b` mean the
   same "this node to that neighbor" thing regardless of which direction
   is doing the scanning.

All three are regression-pinned in `recommended-route.spec.ts`'s "review
fixes" group, each verified to fail against the reverted code before being
confirmed against the fix — including the escape-hatch fixture, which
required a real design pass to make it discriminate the actual bug (an
earlier, weaker version of the test passed even with the fix reverted,
because a different part of the same commit already covered its original
scenario).

## PR 4: shareable URL state, Swap Records, accessible combobox, request lifecycle

Four things, all in `apps/web/src/game/connect.ts`/`connectUrlState.ts`/
`ConnectStage.astro` -- none touch the ranking engine itself.

**URL state.** Connect is the first surface in this codebase to WRITE URL
state at all: verified before starting (`grep`, not assumed) that nothing
in `apps/web/src` calls `pushState`/`replaceState`, only the read-once-at-
init `new URLSearchParams(window.location.search)` pattern `flagship.ts`/
`routes.ts` already use for `?round=`/`?seed=`/`?motion=off`. Album **ids**
only, never titles (`a`/`b`), plus `mode` (omitted entirely at its
unfiltered default, so there is exactly one way to write the common case,
never a redundant `mode=none` some links carry and others don't).
Malformed input is rejected safely and silently: missing/empty ids, and
`a === b` (a record cannot search against itself, and silently keeping one
side of a self-referential link while dropping the other would be an
arbitrary, unrequested repair, not a safe rejection). An unresolvable id
(stale/deleted) cleans the URL without an alarming error -- a dead link is
not something the visitor did wrong. An unrecognized `mode` value falls
back to the unfiltered default rather than failing. No automatic search
runs until both ids validate against the real, loaded catalog.

`pushState` for a genuinely new pair, `replaceState` for the same pair
re-run under a different filter -- **a real design bug found by the test
that should have proven it**: the first implementation compared `a`/`b`/
`mode` all three for the push-vs-replace decision, so a MODE-ONLY change
(same two records) pushed a new history entry instead of replacing, which
directly contradicted "replaceState for same-search refinements." Fixed
by splitting `isSameConnectPair` (all three fields -- "is this write a
total no-op") from a new `isSameConnectAlbumPair` (ids only -- the real
push/replace test), each with its own pinned unit tests.

**Copy Link** copies `location.href` (already reflecting the last
completed search) via `navigator.clipboard.writeText`, following the exact
success/failure pattern `flagship.ts`'s existing share-copy button already
established (button-text swap on success, a polite announcement on
failure) rather than inventing a second convention.

**Swap Records** exchanges both picks, updates the URL, and -- when a
route is already on screen -- reverses the DISPLAYED route
(`pathfindingGraph.ts`'s new `reverseRoute`) instead of searching again.
This is more than an optimization: re-searching A→B as B→A over an
undirected graph is not guaranteed to return the identical route, since
tie-breaking depends on which side the walk starts from, so reversing the
already-verified route is the only way to guarantee "swap" means
literally the same evidence, read the other direction. A genuinely new
pick after a swap correctly invalidates the reusable route
(`onSelect`); Swap's own `setSelection` calls are marked
`{programmatic: true}` specifically so they do NOT re-trigger that same
invalidation on the route they are in the middle of reusing.

**Accessible combobox**, following the WAI-ARIA APG pattern precisely:
`role="combobox"` + `aria-autocomplete="list"` + `aria-expanded` on the
input; `role="listbox"` on the results; `role="option"` with a stable,
picker-namespaced id on each result; `aria-activedescendant` tracks
keyboard navigation WITHOUT moving real DOM focus off the input.
`mousedown` on the listbox calls `preventDefault()` so a click never blurs
the input first. **A real bug found by Playwright, not by review**: the
scrollable results `<ul>` (`overflow-y: auto`, per the existing CSS)
became a genuine, unintended Tab stop in Chromium -- an implicit-
focusability quirk for any scrollable region regardless of `role` or the
absence of `tabindex`, not something either the ARIA spec or this file's
own markup review would surface. Fixed with an explicit `tabindex="-1"`
on both listboxes, a real accessibility improvement independent of the
test that found it.

**Request lifecycle**: the same generation-counter pattern
`explorerStage.ts` already proved for its evidence drawer, applied to
`runSearch`. **The naive regression test for this ("click search twice
quickly, assert the second wins") does not actually exercise the guard**
in this codebase: `loadPreparedGraph`/the evidence-registry loader are
each one memoized, URL-keyed promise, so two overlapping searches share
the identical in-flight promise and their continuations resume in
FIFO (invocation) order regardless of the guard -- the newer search
naturally finishes second-and-therefore-last anyway. A REAL, guard-
dependent race exists because an unfiltered search always awaits two
promises (graph, then evidence) while a role-filtered search that finds
NO connection returns after just the first (it never reaches the
evidence await at all) -- so an OLDER unfiltered search can still be
mid-flight, stalled on evidence, when a NEWER role-filtered search that
fails has already finished and posted its own status. Gating the
evidence-registry response specifically (not the graph) lets the older
search's completion arrive strictly after the newer one's, a real
ordering inversion the guard is what prevents. Verified by disabling the
guard and confirming the test fails for the right reason before trusting
it; the FIRST version of this test (gating the graph, "click twice
quickly") passed with the guard removed and would have been a false
regression pin. A second finding while building the test itself: a
network response having arrived (`page.waitForResponse`) is NOT proof the
page's own `await fetch(...)` continuation has finished running --
`route.continue()`'s extra real I/O (proxying to the actual preview
server) exceeded what a deterministic double-`requestAnimationFrame`
flush covers, while `route.fulfill()` with the real artifact's own bytes
(no proxy hop) does not; traced with the DOM's actual `hidden`
attribute/status text before trusting either.

**Second review pass, one root cause behind three symptoms.** An
automated review of the initial PR found seven real defects, five of
which traced to the same root cause: `runSearch` tracked its completed
route as **five independently-mutated `let` variables**
(`lastPrimaryRoute`, `lastAlternateRoute`, `lastNameById`,
`lastEvidenceReleases`, `lastWasRoleFiltered`), and different call sites
cleared different subsets of them. Consolidated into one
`LastSearch | null` plus a single `clearLastSearch()`, which by
construction makes a partial-clear bug impossible to reintroduce. The
symptoms this caused:

- Swap never called `syncUrl` at all when the last completed search was
  role-filtered (Swap's own code path never touched the URL-sync
  variables the unfiltered path did), and separately read the *live*
  checked radio for `mode` rather than the mode the cached route was
  actually computed under -- so swapping after changing the filter
  selection without re-searching could sync a URL naming a mode the
  displayed route was never ranked against. Fixed: Swap now always
  calls `syncUrl({..., mode: lastSearch.mode})` from the stored,
  route-accurate mode.
- A **failed** search never cleared the `last*` state, so Swap could
  reverse and redisplay a route that a subsequent failed search had
  already disproven as connected. Fixed: `clearLastSearch()` now runs
  at the top of `runSearch`, before the outcome is known, so any new
  search attempt -- successful or not -- invalidates the prior one
  immediately rather than leaving stale evidence reachable.
- Copy Link's reveal was bundled inside `syncUrl`, but `restoreFromUrl`
  always called `runSearch` with `skipUrlSync: true` (correctly, to
  avoid re-writing the URL it was just restoring from) -- which meant a
  URL-restored search could never reveal Copy Link at all. Split
  `syncUrl` (history only) from a new `showCopyLink()`, called
  unconditionally at the end of every successful `runSearch` regardless
  of `skipUrlSync`.

Two independent findings: `restoreFromUrl`'s popstate cleanup called
`setSelection(null)` on both pickers but never closed an open listbox,
leaving a stale result list visible over an now-empty input. Fixed by
moving `closeListbox()` to run unconditionally at the top of
`applySelection`, rather than only on the album-selected branch.
`restoreFromUrl` was invoked exactly once, from the bottom of
`initConnect`, immediately after `ensureCatalog()` -- so a *failed*
initial catalog load permanently skipped URL restoration even though
`ensureCatalog` is retried on the next keystroke. Fixed with an
`urlRestoreAttempted` flag and moving the `restoreFromUrl` call inside
`ensureCatalog`'s own success branch, so it fires exactly once, on
whichever attempt first actually succeeds.

Last, `isSameConnectPair` (the original all-three-field comparator,
superseded by `isSameConnectAlbumPair` above) had zero remaining
production callers and was deleted along with its dedicated test block,
rather than left as unreachable dead code.

**Third review pass: editable state during a pending request, and a
stale result surviving a cache-discarding pick.** An automated review of
the pushed fixes above found three more real defects, all still on PR
#115.

Only Search and Swap were disabled while a request was pending -- the
picker inputs and the mode radios stayed fully interactive. Editing a
selection or the role filter mid-request, WITHOUT clicking Search again,
never advanced `searchGeneration`, so the original, now-abandoned request
could still land once its network call resolved and render a route/URL
for albums or a mode the visitor had since changed away from. The fix is
NOT disabling those controls during a request: the generation counter's
whole design intentionally allows a genuinely NEW search to overlap and
supersede an older one (the two `an older... late completion` tests
above rely on exactly that, clicking a real second search mid-flight),
so blocking input during a request would have broken supported,
tested behavior. Instead, `searchGeneration` is now also bumped directly
from the picker's real-pick handler and from each mode radio's `change`
listener -- invalidating an EDIT-WITHOUT-a-new-search, while a real new
search still bumps it again itself and behaves exactly as before.

Verifying this against the reverted code surfaced a second, genuinely
new lesson about this codebase's own established staleness-test pattern:
the existing `flushPendingWork` double-`requestAnimationFrame` flush,
proven reliable for the earlier two generation-counter tests, was NOT
reliable here -- measured directly and repeatedly (consistent, not
flaky), the gated `route.fulfill()` response in THIS specific
construction took noticeably longer than two animation frames to reach
the page's own `fetch()` continuation, because (unlike the earlier two
tests) no second search's own real network round trip intervenes
beforehand to incidentally absorb that latency. A double-rAF flush
insufficiently proves an absence when nothing else pads the timing. The
regression tests for this now actively poll for the BAD outcome (a
populated URL) over a bounded, generous window via `page.waitForFunction`
instead, so a broken guard is still caught fast and reliably, while a
correctly-invalidated request (which never produces that outcome at all)
costs exactly one full timeout -- the unavoidable price of proving an
absence. Writing this poll surfaced a THIRD, unrelated lesson the hard
way: `page.waitForFunction(fn, options)` silently puts `options` in the
function's `arg` slot, not `options` -- the real signature is
`(fn, arg, options)` -- so the intended `{ timeout: 2000 }` was silently
discarded and Playwright's real default (30s) governed instead, which
exceeded the test's own 30s timeout and tore the whole test down before
the polling promise ever settled. Caught by directly observing the
symptom (`Test timeout of 30000ms exceeded`, `Target page ... has been
closed`) rather than trusting the first failure message at face value.

Separately: after a completed search, a real pick that discards the
cached route (`clearLastSearch`) used to leave the PREVIOUS pair's route
and Copy Link visibly on screen -- only the cache was invalidated, not
the DOM. Pressing Swap at that point found no cached route to reverse (a
correct no-op for the route itself, matching "swap before a search just
exchanges the two picker selections") but left that stale route and
Copy Link untouched while the picker selections had already changed
underneath them -- two mismatched states shown together. Fixed by hiding
the results panel and Copy Link from the same real-pick handler that
clears the cache. Writing the regression test for this surfaced a
genuine, previously-undetected, unrelated CSS bug: `.button` (in
`global.css`, predating this PR) sets `display: inline-flex`
unconditionally, which as a class selector outranks the UA stylesheet's
`[hidden] { display: none }` -- an attribute selector has lower
specificity than any class selector. Copy Link (`class="button"`,
toggled via the `hidden` attribute) had therefore never been visually
hidden by that attribute at all, on initial page load or otherwise; no
existing test had ever asserted Copy Link's HIDDEN state, only ever its
visible one, so this had shipped undetected. Fixed with a
`.button[hidden] { display: none; }` override restoring the native
behavior, verified to be the only `.button`-classed element in the
codebase that combines with `hidden` today.

## Validation

- Synthetic-fixture tests for enumeration bounds, shortest-first
  truncation, the reproduced production tie-break, role/degree metrics, and
  disconnected/unknown-album handling
  (`packages/research/tests/test_route_quality.py`).
- Real measurement is reproducible from committed public artifacts alone:
  `networked-players-research research-route-quality`. No private one-hop
  corpus required; outputs go to the git-ignored `local/research/` lane
  (ADR 0054).
- Ranking determinism, stable tie-breaking, the virtual-anchor exclusion
  invariant, hard caps, the +1-hop escape hatch (both the trigger and its
  refusal to fire when nothing better exists), and safe fallback are all
  tested in the engine itself
  (`apps/web/tests/recommended-route.spec.ts`), plus one real-artifact,
  real-browser assertion against the diagnostic pair
  (`apps/web/tests/game-connect.spec.ts`).

## PR 5a: route timeline presentation

The first slice of Phase 5 PR 5 (route timeline, progressive rendering,
performance, closeout) -- presentation only, in `apps/web/src/game/connect.ts`,
`connectEvidence.ts`, `ConnectStage.astro`, and `game.css`. No ranking or
search-behavior change.

**Endpoint cover art.** Endpoint cards (the route's literal start/end
albums) now carry real cover art via the existing `albumArt.ts`
(`fetchAlbumArt`, ADR 0044/0045) client-side module -- fetched once per page
session alongside the graph/evidence, never blocking a search, and falling
back to `AlbumCard.astro`'s own established polished placeholder (reused
verbatim -- `.album-card__placeholder`/`.album-card__placeholder-disc` from
`motif.css`, not a new placeholder design) for any album missing an entry.
`data-art-fallback="disc"` wires the load-failure case into the SAME
site-wide `BaseLayout.astro` error handler every other cover image already
uses, rather than adding a second one.

**Contributor vs. evidence-release separation.** Each hop card used to run
the two contributors' names and the bridging release's title/year/country
together into one sentence, with the cover image sitting in an unstyled,
accidentally-malformed wrapper div (`<div class="connect-hop__head">${cover}<div>`
-- an unclosed tag, not previously caught because no test asserted on
`.connect-hop__head`'s own layout, only on text content via
`toContainText`). Split into two real, separately styled blocks: a plain
contributor-prose paragraph, and a `.connect-hop__release` sub-card (cover +
title/year/country + source link) with its own subtle background --
"contributor nodes visually distinct from evidence releases" from the PR 5
plan, and a real bug fix along the way.

**Route length.** `hops.length` is now always rendered ("2 hops
documented"), for every outcome that reaches a route -- ranked, degraded,
role-filtered, and the distinct alternate -- not just folded into the
ranked-and-not-degraded case's "why" explanation text as it was before
(where a role-filtered or degraded result showed no length at all).

**"Why this route?" as a real disclosure.** The primary explanation used to
be a permanently-visible paragraph; it's now a `<details data-connect-why-primary>`
around the same explanation `<p>`, closed by default -- a genuine
progressive disclosure rather than a permanently-shown block, matching the
plan's own "disclosure" framing. Only rendered/openable when a real ranking
ran (`!rankingDegraded`), same as before; a role-filtered or degraded result
still shows no "why" section at all, since there is no real ranking to
explain.

**Timeline connector.** `.connect-timeline` (wrapping both the primary and
alternate hop lists) adds a continuous left-edge connecting line with a
marker per stop -- a filled accent dot for each endpoint, a hollow dot for
each hop -- built entirely from this page's own `--line`/`--accent-strong`
tokens, not a new visual system.

**Pre-selection empty state.** A `<p data-connect-empty-state>` sits below
the status/announce region, visible whenever neither the results panel nor
the status message is -- covering initial page load, a popstate-driven
clear, and (new in this slice) a real pick that discards a previously-
completed search's cached route. Deliberately NOT threaded through every
call site that already toggles `resultsEl.hidden`/`statusEl.hidden` (there
are several, and PR 4's whole `LastSearch` consolidation exists specifically
because that kind of duplication drifts); instead a `MutationObserver`
derives it reactively from those two elements' real `hidden` attribute,
so it can never fall out of sync with them by construction.

**Verification.** All 7 new presentation-specific assertions (empty state
before/after search, empty state reappearing after a cache-invalidating
pick, real cover art rendering, the placeholder for a missing art entry,
route length across ranked/role-filtered/alternate outcomes, and the
disclosure's closed-by-default/openable behavior) were confirmed to
actually fail against the pre-slice code before being trusted -- 7 of 8
failed for the right reason; the 8th (role-filtered search shows no "why"
section) was already true before this slice and stays a non-regression
check, not a new-behavior one. Full existing Connect suite (50 tests
including combobox, URL state, swap, and staleness) re-verified green
against the restored code, plus a fresh `npx tsc --noEmit` and `make check`.

**Review findings on this slice, both real.** An automated review of the
pushed PR found two defects:

1. `runSearch` awaited the album-art registry (`artPromise`) before
   revealing results at all. `fetchAlbumArt()` has no fetch timeout, so a
   slow or hung art registry would leave an already-found route stuck
   behind "Searching…" indefinitely, with search/swap disabled, for a
   fetch that only affects presentation. Fixed by never awaiting it:
   `runSearch` now renders immediately with an empty (all-placeholder) art
   map, then a `.then()` callback -- guarded by the same `stale()` check
   every other late-arriving continuation uses -- upgrades each rendered
   endpoint's placeholder to a real cover IN PLACE
   (`connectEvidence.ts`'s new `enhanceEndpointCover`) once the registry
   actually resolves, never a full re-render of the route. The map is the
   same mutable object stored on `lastSearch`, so Swap's own re-render
   (which reads `lastSearch.artByAlbumId`) sees the enhancement too with
   no extra bookkeeping.
2. `BaseLayout.astro`'s site-wide image-error fallback (the handler every
   `data-art-fallback="disc"` image already shares) replaced a failing
   `<img>` with a bare `<span class="album-card__placeholder">`, discarding
   whatever OTHER classes that image carried. For Connect's 72px, flex-
   sized `connect-endpoint__cover`, a real upstream image failure (an
   expired or 404 hotlink) would silently fall back to
   `.album-card__placeholder`'s own `width: 100%` sizing instead --
   correct for the album grid this handler was originally written for,
   wrong for an endpoint card. Fixed by carrying the failing image's own
   `className` over onto the replacement span (`${img.className}
   album-card__placeholder`) rather than discarding it -- a generic fix at
   the shared handler, not a Connect-specific branch, so any future
   `data-art-fallback="disc"` caller with its own sizing class is covered
   the same way.

A new regression test (`a slow album-art registry never delays the route
from rendering, and covers upgrade in place once it resolves`) gates the
art registry response and confirms the route renders fully -- status
clears, results show, placeholders stand in -- before releasing it and
confirming the placeholders upgrade to real `<img>`s in place.

## PR 5b: progressive rendering

The second slice of PR 5, in `apps/web/src/game/connect.ts` -- begins
graph preparation on a real intent signal, and stages status text
honestly, per the plan's own wording. No ranking or route-selection
change.

**Begin graph preparation on the second valid pick, not the search
click.** `updateButton()` already runs on every pick and already computes
`bothPicked`; it now also calls `loadPreparedGraph()` (and `loadAlbumArt()`)
the moment that's true. Both are already memoized, module-level promises
(post-Phase-4 cleanup audit F11/F12 for the graph; this PR's own PR 5a
slice for art), so warming them here costs nothing extra -- `runSearch`'s
own later calls to the same functions just resolve immediately, or much
sooner, once the visitor actually clicks Search, overlapping fetch/parse/
validate time with their own think-time between picking and searching.
This directly targets the measured baseline's single biggest waterfall
item: `graph.v2.json` wasn't even requested until the search click.

**Evidence is deliberately NOT warmed the same way.** Unlike the graph,
whether evidence is needed at all depends on the role-filter mode, which
isn't decided yet at pick time (it defaults to unfiltered, but picking
both albums and only afterward choosing a role filter -- exactly what
`tests/game-connect.spec.ts`'s "a role-filtered search that finds no
connection never fetches the evidence registry" already covers -- is a
real, common order). Warming it unconditionally on pick-completion would
silently reintroduce the exact wasted-fetch cost `runSearch`'s own
mode-conditional evidence fetch (PR 3) was written to avoid. Evidence
keeps loading exactly when it does today: alongside the graph for an
unfiltered search, or only after a role-filtered route is confirmed.

**Honest staged status text**, never a fabricated percentage: "Loading
the connection graph…" (the real first operation, true whether the graph
is a fresh fetch or already warmed -- the await still runs either way, it
just settles fast when warmed) transitions to "Ranking documented
routes…" (unfiltered -- about to await evidence and rank) or "Searching
for a documented connection…" (role-filtered -- about to run the edge-
filtered BFS) once the graph resolves. The four existing staleness/
race-condition tests that previously asserted a flat `/searching/i`
were updated to the new second-stage text, since all four are unfiltered
Discovery/Joshua Tree searches whose evidence-gated construction means
that's genuinely what's showing by the time each assertion runs.

**Verification.** Five new tests confirm the graph and album-art registry
are requested on the second pick (before any search click), that evidence
is NOT eagerly fetched merely from picking both albums, and that both
staged-status transitions are real and observable (gating the graph, then
also gating evidence long enough to hold each search at its second stage
before releasing) -- 4 of 5 confirmed to fail against the pre-slice code;
the 5th (no eager evidence fetch) was already true and stays a non-
regression check. Full Connect suite (76 tests across every existing
spec file plus the two new ones) re-verified green, plus `npx tsc
--noEmit` and `make check`.

## PR 5c: off-main-thread graph parse/canonicalize/hash

The third slice of PR 5 -- the first Web Worker in this codebase. In
`apps/web/src/game/graphWorker.ts` (new) and `pathfindingGraph.ts`. Bounded
scope, per the plan's own risk note: this worker ONLY fetches, parses, and
validates/hashes the pathfinding graph artifact; no BFS or ranking logic
moves off-thread, and the integrity hash is never skipped or deferred past
validation.

**Why.** ADR 0059's own measured baseline (cold cache, this machine, the
13.5 MB v2 graph): fetch+body 456ms, `JSON.parse` 106ms, canonical
stringify 106ms, SHA-256 299ms, build index 24ms -- the integrity check
(`validatePathfindingGraph` recomputing `pathfinding_graph_version` from
content, which canonical-stringifies and hashes the graph's identity
fields) is 405ms of 535ms of real main-thread work, 76% of it. Real Pi-
fleet browsers aside, even on a capable machine that's most of a second
where the page can't respond to input, scroll, or repaint anything else.

**Design.** `graphWorker.ts` fetches, `JSON.parse`s, and calls the
EXISTING `validatePathfindingGraph` (already pure, DOM-free -- no
duplication needed, just imported directly into the worker's module
graph) -- then posts the validated graph back via structured clone (a
plain-array CSR structure; a full clone, not a zero-copy transfer, but
still far cheaper than redoing parse+canonicalize+hash on the receiving
thread). `pathfindingGraph.ts`'s `loadPathfindingGraph` keeps its exact
public signature and behavior: same cache-read-first order, same
validation, same cache write, only WHERE the work happens changes. A
single worker is created lazily and reused for the page's lifetime (the
same load-once-reuse shape every other module-level cache in this file
already has); `sessionStorage` access stays main-thread-only (a worker
has no access to it) -- the main thread reads the cache entry first and
passes it to the worker as `cachedText` for validation-in-place, and
writes back whatever raw text the worker's own request actually used.

**Fallback, two distinct cases.** A Worker that can't be constructed at
all (`typeof Worker === "undefined"`, or the constructor throws -- the
realistic case, e.g. a strict CSP) falls back to running the identical
logic directly on the main thread (`loadPathfindingGraphMainThread`,
literally the pre-PR-5c function body, unchanged). A Worker that crashes
AFTER construction (its own `error` event) fails every request currently
waiting on it with a synthetic `"worker-crashed"` signal, which the
caller treats exactly the same way -- falls back to the main thread for
that call, never leaving a promise hanging forever on a worker that can
no longer respond. Neither case is confused with a THIRD case: a worker
that completes a request normally and reports a real `fetch-failed`/
`parse-failed`/`invalid-graph` failure. That's trusted as final and never
retried on the main thread -- retrying would just reproduce the identical
real failure with extra latency, not recover from anything.

**Both real browser consumers benefit, not just Connect.**
`loadPathfindingGraph` is `explorerStage.ts`'s own direct dependency too
(Network Explorer), so this slice's win applies there automatically, with
no Explorer-specific change.

**Worker typing without a second tsconfig.** This project has one shared
`tsconfig.json` across `apps/web/src`, which needs the `"dom"` lib for
every other file; TypeScript doesn't support mixing `"dom"` and
`"webworker"` lib globals in one compilation (both declare conflicting
types for `self`/`postMessage`). Rather than add a second tsconfig for
one file, `graphWorker.ts` casts `self` once to a small, locally-defined
interface covering exactly the two worker APIs it uses
(`postMessage`/`onmessage`), fully type-safe for this file's own
request/response shapes without touching the ambient global lib set.

**Verification.** Four new tests confirm: the worker script is actually
requested (not just present in the bundle -- Vite's `new Worker(new
URL(...))` convention was verified to produce a real, separate output
chunk via a real `npm run build`, not assumed); a real search still finds
the correct route when Worker construction is made to throw; a real
search still finds the correct route when the worker script itself is
replaced with one that crashes on load (a genuine Worker `error` event,
not a simulated one); and a fetch failure still degrades gracefully
through the worker path. The two fallback tests were each spot-verified
against a deliberately broken version of their own code path (the
try/catch removed, then the `error` listener removed) and confirmed to
fail -- specifically to hang/time out, since without either fallback the
promise the UI awaits never settles -- before being trusted. Full Connect
suite, Network Explorer suite (both evidence-drawer and state-graph
specs), and `pathfinding-bfs-v2.spec.ts` (98 tests total) re-verified
green against the worker-backed loader, plus the full site-wide Playwright
suite, `npx tsc --noEmit`, and `make check`.

**Review finding on this slice.** An automated review of the pushed PR
found one real defect: the crash handler resolved every request currently
waiting on the dead worker, but left the dead `Worker` object itself
cached (`graphWorker` still pointed at it, `graphWorkerWired` still
`true`). `loadPreparedGraph` separately evicts a failed result from its
own cache so a later search can retry -- but that retry would `postMessage`
to the SAME crashed worker, which (having thrown during its own top-level
script evaluation) never processes another message or fires another
event, so the retry would hang forever waiting on a response that could
never arrive. Fixed: the crash handler now also terminates the dead
worker and resets both module-level flags (only when the crashed instance
is still the currently-cached one, guarding against a stale listener on
an already-replaced worker), so the next `getGraphWorker()` call
constructs a genuinely fresh instance. A new regression test crashes the
worker AND fails the graph fetch on its first attempt, then confirms a
second attempt (progressive rendering's own pick-time warm-up already
supplies the first attempt, so the search click itself becomes the real
retry) resolves rather than hanging, with an explicit assertion that at
least two real fetch attempts occurred -- confirmed to fail (time out)
against the pre-fix code before being trusted.

## PR 5d: closeout

Phase 5 is complete: PR 1 (measurement + preflight), PR 2 (canonical
names, defensible evidence release, evidence registry v2), PR 3 (the
recommended-route engine), PR 4 (shareable URL state, Swap Records,
accessible combobox, request lifecycle), and PR 5 in its three slices
(5a presentation, 5b progressive rendering, 5c the graph Worker) are all
merged to `main` and live in production.

**`docs/PRODUCT.md`** updated -- its Connect Two Records bullet described
only the ADR 0058/0053 baseline (route search, evidence cards, role
filters); it now also names the ranked recommendation, the shortest/
alternate distinction, the "Why this route?" disclosure, the shareable
link, Swap, and endpoint cover art, all real and live.

**`docs/ROADMAP.md` and `docs/NEXT_PATH_BRIEF.md`** checked and left
unchanged -- neither references Connect, pathfinding, or route quality;
both track a different, unrelated set of milestones and next-direction
candidates that this phase doesn't touch or invalidate.

**Real, dated performance observation** (not a claim about every visitor's
experience -- one measurement, one machine, three runs, against the live
production site, 2026-08-15, `chromium` via Playwright, cold context per
run, the Discovery/Joshua Tree diagnostic pair, unfiltered mode):

| Stage (from navigation start) | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| page load | 692ms | 588ms | 535ms |
| picker ready | 815ms | 676ms | 621ms |
| Worker script requested | 1112ms | 928ms | 854ms |
| `graph.v2.json` requested | 1270ms | 1020ms | 918ms |
| evidence registry requested | 1201ms | 1002ms | 954ms |
| search click → results visible | 2232ms | 1643ms | 1649ms |

The structural claim PR 5b's own section above makes -- that the graph
(and, new in 5c, the Worker script) now load during picking rather than
after the search click -- is directly confirmed here: both are requested
within roughly a second of navigation start, well before this script's
own search click (which follows immediately after the second pick, with
none of a real visitor's think-time in between). That immediacy means
this measurement is a conservative floor, not a ceiling, on the real-world
benefit: a visitor who pauses between picking and searching gets more of
that fetch/parse/validate time absorbed into their own think-time than an
automated script clicking as fast as possible ever can. The search-click-
to-results span (1643-2232ms) is comparable to or faster than this same
page's pre-Phase-5-PR-5 behavior, where the graph fetch hadn't even
started by the time of the click at all -- but no exact prior number is
cited here, because none was ever committed to this repository to cite;
the only claim made is what this table itself shows, run against the real
site on the date given.

## Revisit trigger

If the catalog grows enough that the shortest layer stops being cheap —
concretely, if the shortest-layer forward walk's **median** exceeds ~25,000
inspected slots (it is 2,256.5 today) or its worst case exceeds ~500,000
(84,240 today), or the equal-hop candidate count routinely exceeds ~1,000
(max 157 today), or the reverse precompute stops being reusable across a
single search — revisit the bound before widening the hop allowance. If a future artifact ever publishes
per-pair *candidate* releases rather than one collapsed choice, revisit
whether hop-level evidence selection belongs in the client instead of the
builder.
