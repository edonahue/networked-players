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

## Validation

- Synthetic-fixture tests for enumeration bounds, shortest-first
  truncation, the reproduced production tie-break, role/degree metrics, and
  disconnected/unknown-album handling
  (`packages/research/tests/test_route_quality.py`).
- Real measurement is reproducible from committed public artifacts alone:
  `networked-players-research research-route-quality`. No private one-hop
  corpus required; outputs go to the git-ignored `local/research/` lane
  (ADR 0054).
- Ranking determinism, stable tie-breaking, role-filter hardness, and
  fallback-to-shortest are tested in the engine itself when it ships.

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
