# ADR 0070: Community detection is measured and denied; Explore scaling gets a real recenter budget

- **Status:** Accepted (superseded in part — see banner below)
- **Date:** 2026-09-03, last revised 2026-09-04
- **Extends:** [ADR 0055](0055-research-graph-library-selection.md) (igraph selection),
  [ADR 0061](0061-scope-tier-corpus-design-deferred.md), [ADR 0063](0063-bridge-contributors-promotion-rejected.md)
  (betweenness/bridge-contributor promotion, rejected) without modifying any of them
- **Relates to:** [ADR 0052](0052-network-explorer-svg-bounded-radius.md) (recenter as the
  primary Explore interaction, still holds), [ADR 0069](0069-public-universe-model-and-expansion-policy.md)

> **Read this first.** This ADR's own real §6 recenter-timing measurement was reported twice,
> with the second report reversing the first — a reader stopping after "Decision" /
> "Consequences" / "Validation" / "Revisit trigger" below (a normal place to stop) will land on
> the *original*, now-superseded finding. **The current, correct conclusion is the final
> section, "Addendum (2026-09-04): root-cause investigation and controlled remeasurement":
> the original "recenter budget missed, tiles likely needed" finding turned out to be
> substantially a benchmark artifact. Tiles are NOT indicated, and Phase 2 catalog growth is
> NOT blocked on an Explore rendering-architecture change.** Community detection's own
> denial (§1 below) is unaffected by any of this and stands as originally decided.

## Context

Graph-expansion Phase 0 slice 0-C (`docs/GRAPH_EXPANSION_DIRECTION.md`) is a measurement-only
slice: no product change, real numbers recorded to `local/benchmarks/` (ADR 0018 — this ADR
states qualitative outcomes only, never the underlying elapsed-time figures). Two of its
measurements produce real, actionable decisions rather than just raw numbers, which belong
in a decision record so a later reader doesn't re-derive them:

1. The plan's §8 asked whether Leiden community detection "earns its place" as an Explore
   prominence signal, via a stated gate: runtime < 60s, modularity > 0.3, ≥ 60% of album
   anchors in a majority community with another anchor, and a legible 10-community spot
   check.
2. The plan's §6 Explore-scaling benchmark asked for a real recenter-timing budget (p95 ≤
   100ms) to gate Phase 1's tiles-vs-single-file decision — never previously measured.

## Decision

### 1. Community detection: measured, denied

Ran real Leiden (`igraph.Graph.community_leiden`, modularity objective) and
`articulation_points()` against the real, committed `pathfinding/graph.v3.json` (20,845
nodes, 38,323 undirected edges, 179 album anchors), via a new CSR→igraph adapter
(`packages/research/src/networked_players_research/graph_analysis.py`'s
`published_graph_community_detection`/`published_graph_articulation_points`, reusing
`route_quality.load_published_graph` — dependency-free of the private one-hop corpus, so
any checkout can reproduce this from the committed artifact alone).

Two of the four gate criteria pass clearly (runtime is a small fraction of the 60-second
budget; modularity is well above 0.3) and two fail decisively:

- **Anchor majority-community sharing: 0%** (gate requires ≥ 60%). Not one of the 179 album
  anchors shares its Leiden community with another album anchor.
- **Real inter-anchor bridges: 0 of 173 real cut vertices.** Every cut vertex
  `articulation_points()` found, filtered to ones separating ≥ 2 album anchors into
  different resulting components (the exact "single-leaf case that sank ADR 0063" filter,
  reproduced here as real tested code rather than one-off arithmetic), turned out to
  separate zero anchor pairs. ADR 0063 found the same shape on a related graph:
  a handful of real cut vertices, every one shedding a leaf, none bridging two real regions.

**Decision: community detection does not earn its place.** It is not shipped as an Explore
rank signal. This is a clean deny, not a close call — 0% against a 60% bar and 0 of 173
against "any" are not measurement noise. The likely structural reason (consistent with ADR
0061's own warning that "the bounded ego graph may be too star-shaped"): Leiden optimizes
for tight modularity communities, which tend to be small, dense session-player cliques: two
different albums' credited-performer sets rarely overlap enough for their anchors to land in
the same tight community, even when the graph as a whole is well-connected and one bridging
performer away.

`community_id` is not added to the prominence sidecar the plan otherwise designs (§8).
Betweenness/bridge-contributor promotion stays closed per ADR 0063, unaffected by this
measurement.

### 2. A real recenter-timing budget, and a finding that changes Phase 1's plan

`apps/web/scripts/reprofile-site.mjs` (Phase 7 PR G's re-profile script) gains a new
`measureExplorerRecenter` measurement — click the first non-center neighbor, wait for
`centerOn()`'s own real completion signal (`explorerStage.ts` already stamps
`data-is-center="true"` onto the newly-centered node), repeat 50 times, report p50/p95/max
— plus a third profile, `--desktop-throttled` (4x CPU throttle, no device/mobile-viewport
emulation), isolating pure CPU cost from `--mobile-throttled`'s combined effect. Run against
the real committed site at 179 albums, across all three profiles (desktop unthrottled,
desktop 4x throttled, mobile Pixel-5 4x throttled).

**Finding: recenter p95 at 179 albums, TODAY, already sits at or above the plan's own
Phase 1 budget (p95 ≤ 100ms) in every profile measured, including desktop unthrottled.**
This is the single most consequential number this slice produced, stated here qualitatively
per ADR 0018 (the real millisecond figures are in
`local/benchmarks/2026-09-03-site-reprofile-179-albums-extended.json`, gitignored).

**Consequence for Phase 1:** the plan's §6 sequencing ("dictionary encoding + typed arrays
first; tiles are a pre-designed fallback behind an explicit trigger... if throttled
first-node > 3s") implicitly assumed recenter cost was currently comfortable and only
graph-size growth would threaten it. That assumption is now measured false: recentering is
already at budget at 179 albums, before any album-count growth at all. Phase 1's `graph.v4`
work should treat recenter cost as a target to *improve*, not merely preserve, and should
re-run this exact measurement (now a real, scripted, repeatable check) after the role-
dictionary/typed-array encoding change lands, before deciding whether the tiles trigger
fires.

A second, non-obvious real finding, recorded honestly rather than smoothed into an expected
narrative: recenter timing did **not** scale cleanly with CPU throttle across the three
profiles measured — the mobile (Pixel-5-viewport, 4x-throttled) profile's recenter numbers
were not worse than desktop-unthrottled's, plausibly because the smaller viewport renders
fewer visible Explorer nodes per recenter, which can matter more than the CPU throttle. This
means throttled-profile numbers must be read as their own real data points, not assumed to
be a simple multiple of the unthrottled ones (documented directly in
`docs/SITE_REPROFILE_METHOD.md`'s "Profiles" section now, so a future reader doesn't
re-derive the same caveat).

### 3. Connection-rounds cost at synthetic N=500: no rewrite needed yet

Timed `connection_rounds.generate_connection_round_pool`'s discovery loop
(`_build_two_hop_round`'s O(N)-per-pair middle search, the O(N²)·O(N) shape the plan's §5.5
flagged) against two synthetic 500-album fixtures with different shared-performer density
(a dense case with ~22% of pairs already one-hop-connected, and a sparser case closer to
the real catalog's apparent density with full one-hop AND two-hop target pools achieved).
**Both stayed comfortably under the plan's 5-minute stop/go gate** — the sparser, more
representative case used well under a quarter of the budget. Per the plan's own instruction
("apply the adjacency-list rewrite only if > ~5 min"), **no algorithmic change is made
here.** Revisit only if a future real-corpus measurement at meaningfully larger N (Phase 2's
actual round counts) crosses the 5-minute line.

### 4. A local 500-tier album fixture, for Phase 1's future gate

Built via the existing `rank-exploration-tier` CLI (ADR 0049) against the real one-hop
corpus and a 3,000-candidate shortlist: 500 albums (54 editorial, 446 graph-rich), written
to `local/analysis/exploration-tier-500/albums-500.json` (git-ignored, per
`data/albums/README.md`'s existing "never committed" convention for `rank-album-candidates`-
family output). This is the album POOL only — building an actual 500-scale
`pathfinding/graph.v3`-shaped artifact from it and reprofiling Explore against it is Phase
1's own `graph.v4` work, not repeated here; doing so now would be doing Phase 1's job early
rather than measuring for it.

### 5. Two more plan assumptions already true

- **Hardware model names are already public.** `docs/HARDWARE.md`'s node-role table already
  names "ZimaBoard 832" and "Raspberry Pi 3B" publicly; ADR 0018's own Decision section
  already states "hardware models remain public per ADR 0001" for that table specifically
  (only measured throughput/elapsed-time/memory numbers are restricted). The plan's proposed
  "amend ADR 0018 to allow hardware brand names" is a non-issue — no amendment needed.
- **A CSR→igraph adapter for the published graph already had a working `PublishedGraph`
  dataclass to build on** (`route_quality.py`, Phase 5's route-quality measurement work) —
  the plan correctly anticipated reusing it, and this ADR's §1/§2 work confirms that
  anticipation was accurate.

## Consequences

- **As originally written (2026-09-03): no product code changes** — `reprofile-site.mjs` and
  `graph_analysis.py` gain new, independently tested measurement capability; nothing in
  `apps/web`'s shipped pages or `packages/graph-core`'s builders changes. **No longer true as
  of the 2026-09-04 root-cause addendum below**, which did land a real product-code change
  (`networkExplorer.ts`'s `selectTopK` bounded-heap fix) — kept here for the historical
  record of what this ADR's original 2026-09-03 decision actually shipped, not as a current
  claim.
- Phase 1 planning should explicitly budget for recenter-cost improvement, not just
  preservation, given the finding in §2 *(superseded — see the banner at the top of this
  file)*.
- The community-detection deny (§1) closes that open question for the whole graph-expansion
  phase — Explore's prominence ranking (plan §8's `rank` formula: `albums_2hop`/`decade_span`
  weighted highest) proceeds without a community signal.

## Validation

`packages/research/tests/test_published_graph_analysis.py` (4 tests: a real-bridge case
proven against a hand-verified small graph — caught two real off-by-one topology mistakes
in the first draft of the fixture itself, fail-then-pass; a no-real-bridge decoy case; an
edgeless-graph edge case; a two-triangle modularity sanity case). `reprofile-site.mjs`'s new
`measureExplorerRecenter` reuses `centerOn()`'s own real completion signal, not a fixed
sleep. All real measurements in this ADR were run against the real committed
`pathfinding/graph.v3.json` and the real locally-served 179-album production build, not
synthetic stand-ins (synthetic fixtures were used only for the connection-rounds N=500
timing and the unit tests, where real corpus data at that scale doesn't exist).

## Revisit trigger

- Re-run the recenter measurement immediately after Phase 1's `graph.v4` encoding change
  lands, before deciding whether the tiles-fallback trigger (§6) fires.
- If a future measurement shows community detection's anchor-sharing fraction materially
  improves (e.g. after Phase 2 growth changes the graph's shape enough that album anchors
  start clustering together), revisit with a fresh real measurement — never assume the 0%
  finding here generalizes to a much larger, differently-shaped graph without re-measuring.
- Re-run the connection-rounds timing against the real corpus once Phase 2's actual round
  counts are known, not just synthetic fixtures.

## Addendum (2026-09-03): recenter re-measured after `graph.v4` cutover — real improvement, budget still open

Phase 1's role-dictionary encoding (ADR 0071) and full consumer cutover (Connect, Explore,
the research workbench, the fleet artifact-check default) are now live, and `graph.v3.json`
is retired. Per this ADR's own revisit trigger above, `measureExplorerRecenter` was re-run
against the real committed 179-album production build (now serving `graph.v4.json`), 2-3
runs per profile for stability (raw numbers, real and gitignored, in
`local/benchmarks/2026-09-03-site-reprofile-179-albums-graphv4-{desktop,desktop-throttled,
mobile-throttled}(-run2){.json}`).

**Real, substantial improvement, stated qualitatively per ADR 0018:** recenter p95 dropped
roughly 30% on desktop unthrottled and roughly 35-40% on desktop 4x-throttled, relative to
this ADR's original `graph.v3` baseline; `firstNodeVisibleMs` and the worker's JSON-parse
time both dropped by roughly a third to a half across all three profiles, consistent with
the measured raw/gzip payload reduction (ADR 0071: raw -41.5%, gzip -24.0%). Mobile
4x-throttled's recenter numbers stayed essentially flat, consistent with this ADR's original
finding that the mobile profile's smaller viewport (fewer visible nodes per recenter) — not
CPU/parse cost — dominates there.

**Budget status: desktop and desktop-throttled recenter p95 are now close to, but still
marginally above, the plan's §6 100ms budget across repeated runs; mobile-throttled's is
similarly close.** This is a real, measured improvement over the original finding (recenter
already over budget with no growth at all) but not yet a clean pass. `firstNodeVisibleMs`
and gzip payload size are both comfortably within their own §6 budgets on all three profiles
at 179 albums.

**This is a checkpoint, not the tiles-trigger decision.** The plan's §6 trigger is
explicitly gated on the local 500-tier fixture (`local/analysis/exploration-tier-500/
albums-500.json`, already built), not the real 179-album production site — Phase 1's
remaining work (`graphWorker.ts` typed-array transfer, the `prominence.v1.json` sidecar,
`explorerStage.ts` pan/zoom/pushState/paging, and the search index) still needs to land
before that real gate is run, per the plan's own Phase 1 sequencing (§11). This addendum
records that the encoding change alone measurably helped recenter cost, as ADR 0070's
original finding asked Phase 1 to treat it as a target to *improve* — it does not close the
open tiles question, which stays gated on the full §6 benchmark against the 500-tier
fixture once the rest of Phase 1 ships.

## Addendum (2026-09-03): prominence sidecar published — the ranking signal this ADR's §2 finding needed

This ADR's §2 finding warned that a raw-degree-led ranking is exactly the hub trap the
plan's own measurement identified; the plan's §8 answer (a precomputed, explainable
prominence signal replacing the contributor index's `connection_count`, which only covers
~445 indexed contributors and ties at 0 for most graph neighbors) is now real and published:
`apps/web/public/data/pathfinding/prominence.v1.json` (contract `data/contracts/
prominence-v1.md`, builder `networked_players_graph_core.prominence`, validator
`networked_players_contracts.prominence::prominence_failures`, CLI `build-prominence`/
`validate-prominence`, registered as its own `prominence` group in `PUBLIC_ARTIFACT_GROUPS`
and the Pi fleet's `_artifact_validators`/`_DEFAULT_ARTIFACTS`).

A node-aligned companion to `graph.v4.json` (parallel arrays, same index as that graph's own
`node_ids`, pinned to its `pathfinding_graph_version` so a ranking retune never forces a
graph rebuild), giving every real performer node: `degree`, `albums_1hop`/`albums_2hop`
(the latter computed cheaply — union of small per-neighbor album sets, never a brute-force
two-hop walk, since this graph's own heavy tail makes that genuinely expensive for hub
nodes), `evidence_releases`, `role_diversity`, `first_year`/`last_year`, and a precomputed
`rank` — a documented weighted sum favoring `albums_2hop`/`decade_span` (bridges between
scenes/eras) over raw `degree` (deliberately not the dominant term), matching the owner's
stated Explore discovery goal (plan §8, decided §15: "bridges between scenes/eras and band
lineups and their orbits").

Real measured artifact size (2026-09-03, the same real committed `graph.v4.json`/
`evidence/release-registry.v1.json`): 1,030,416 raw bytes, 183,564 gzip bytes for 20,845
nodes — a real byte count, not hardware performance data, published directly per the same
ADR 0018 precedent `pathfinding-graph-v4.md`'s own table already sets.

**Scope, deliberately narrow, matching every prior Phase 1 slice's own staged-publication
precedent:** published and validated only. `explorerStage.ts`'s actual neighbor-ranking
cutover (reading `rank` to order/page neighbors and choose label visibility) is separate,
later Phase 1 work — this addendum does not claim Explore's hub-trap risk is resolved in
production yet, only that the real ranking signal it needs now exists and is real,
committed, and fleet-validated.

## Addendum (2026-09-04): the real §6 gate, run against the local 500-tier fixture — recenter budget missed in every profile

Phase 1's full Interaction bundle (pushState/popstate, prominence ranking + paging, mobile
touch targets, pan/zoom — PRs #226-229) and the search index (PR #230) are now live at 179
albums. Per this ADR's own revisit trigger and the plan's §6 sequencing, the real gate run
against the local 500-tier fixture (`local/analysis/exploration-tier-500/albums-500.json`,
built in slice 0-C) was executed now, not against the real 179-album production site.

**Method, and two real gaps in tooling closed to make this measurement possible:**
`reprofile-site.mjs` previously hardcoded the real 179-catalog's own diagnostic Connect pair
("Discovery"/"The Joshua Tree") as a literal string, which made the script unusable against
any other catalog. Fixed by deriving the cold-search pair from `challenge.v3.json`'s own
first path (`pickColdPair`, mirroring the existing `pickWarmPair` derivation) — the script
now genuinely works against any committed or local catalog, not just the one it was
originally written against. Separately, Connect's combobox (PR #230, shipped the same day)
now depends on `search/index.v1.json` for ranking, which the 500-tier fixture build did not
initially include — a minimal stub contributor index (`contributors: []`, matching
`catalog_version`) was enough to build a real, valid 500-tier search index from
`build-search-index`, since Connect only ever queries it with `kinds: ["album"]`.

The 500-tier `graph.v4.json`/`prominence.v1.json`/`credit-membership.v1.json`/
`challenge.v3.json`/`catalog/albums.v1.json`/`search/index.v1.json` were built from the real
one-hop corpus (never fabricated), temporarily swapping the tracked `apps/web/public/data/`
files for a real `npm run build`+`npm run preview` run, then restoring the real files
afterward (confirmed byte-identical to the pre-swap committed state). **One deliberate,
documented deviation from production discipline:** the 500-tier `challenge.v3.json` was
built with a bounded `--max-frontier-expansion 300` and `--max-paths 100` rather than
production's unbounded `--max-frontier-expansion 0` and full per-album coverage target — an
unbounded, full-coverage attempt against this sparser synthetic fixture ran 30+ minutes
with zero progress visibility (a real, separate gap now tracked as plan §17/§18's
progress-logging slice) before being killed. This means the 500-tier fixture's own
*coverage* numbers (111 of 500 albums appear in a found path) are not comparable to what a
real production round would produce — only the payload-size and interaction-timing numbers
below are treated as real signal.

**Real numbers, stated qualitatively per ADR 0018 (raw figures in
`local/benchmarks/2026-09-04-site-reprofile-500-tier-{desktop,desktop-throttled,
mobile-throttled}.json`, gitignored), against the plan's §6 budgets:**

| Budget | Desktop | Desktop 4x-throttled | Mobile 4x-throttled |
|---|---|---|---|
| `graph.v4.json` gzip ≤ 2.5 MB | **pass** (comfortably under) | same artifact | same artifact |
| Throttled first-node ≤ 3 s | n/a (well under) | **pass** (close to the line) | **pass** (close to the line) |
| Recenter p95 ≤ 100 ms | **miss** | **miss** | **miss** |
| JS heap ≤ 150 MB | **pass** (well under) | same | same |

**Recenter p95 misses budget in all three profiles at 500-album scale** — worse than the
already-marginal 179-album post-`graph.v4` figures this ADR's first addendum recorded, and
worse in the *opposite* direction from what a naive read of that addendum's "real,
substantial improvement" framing might suggest: the encoding change helped, but graph-size
growth from 179→500 albums (41,414 nodes / 94,680 edges at 500, vs. 20,845 / 76,646 at 179 —
node/edge growth notably sublinear relative to the 2.79x album-count ratio, as expected from
overlapping performer neighborhoods) outpaced that improvement. Payload size, first-node
timing, and heap all stay within budget — this is specifically a **recenter-interaction-cost**
problem, not a payload or memory one.

**Decision, per the plan's own stated rule ("a miss triggers the tiles ADR before further
growth"): Phase 1 does not clear its own §6 gate.** This is a measured "not yet," in the same
spirit as this ADR's §1 community-detection deny and ADR 0063's bridge-contributor deny — a
real threshold compared against a real number, not a judgment call. Growing the catalog
toward Phase 2's ~500-album target on the current single-file Explore renderer would ship a
recenter interaction the plan's own budget already calls too slow, at the very scale Phase 2
targets.

**What this does NOT decide:** whether tiles are the right fix, or whether a cheaper
recenter-cost optimization (e.g., trimming per-recenter DOM work, a lower per-recenter
neighbor cap before paging, or a virtualized render) could close a ~30-70ms gap without the
tiles architecture's own real costs (a second load path, a recentering-onto-non-anchor-node
complication the plan's own §6 already flagged). That investigation is real, separate design
work — the plan names it explicitly as "design tiles under a new ADR before further growth,"
which this addendum defers to rather than pre-empting.

## Revisit trigger (added 2026-09-04)

- Before Phase 2 catalog growth begins: design the tiles fallback (or a cheaper alternative)
  under its own ADR, informed by this addendum's real numbers, and re-run this exact §6
  benchmark against whatever change is made — against the 500-tier fixture again, not just
  179 albums, since this addendum's whole point is that 179-album numbers were not
  predictive of 500-album behavior.
- Once `challenge.py`/`onehop.py` gain progress logging (plan §18/slice 2-0b), rebuild the
  500-tier fixture with production's real unbounded `--max-frontier-expansion 0` and full
  per-album `--max-paths` coverage, so a future coverage-sensitive measurement (e.g. sitemap
  composition at true production discipline) has a fixture to match, rather than reusing this
  addendum's deliberately-bounded one.

**Superseded by the 2026-09-04 root-cause addendum below — kept for the historical record,
not as the current read of the situation.**

## Addendum (2026-09-04): root-cause investigation and controlled remeasurement — the original miss was substantially a benchmark artifact

Before committing to the tiles design this ADR's previous addendum called for, a deep-dive
investigation traced `centerOn`'s full call graph (`explorerStage.ts`, `networkExplorer.ts`'s
`buildView`, `NetworkExplorer.astro`'s render shell) to find out *why* recenter cost would
scale with total graph size at all, since Explore is architecturally a bounded 1-hop ego view
(ADR 0052) whose recenter cost should depend only on the current node's own capped
neighborhood.

**Finding: no O(total-graph-size) cost exists anywhere in the recenter path.** The center
node's own index is found via an O(1) prebuilt `Map` (`buildArtistIndex`, built once at
page init, never rebuilt per recenter); the candidate loop is bounded by the center node's
own CSR row; `MAX_NEIGHBORS = 24` is a fixed literal constant unrelated to catalog size.
Every genuinely O(total-graph-size) operation (graph parse/validation, the artist-index and
prominence/contributor-index map builds) runs exactly once at page init, never inside
`centerOn` itself.

**One real, small, unrelated inefficiency found and fixed regardless:** `buildView`'s
candidate loop was sorting a center node's *full, uncapped* raw degree before slicing to
`MAX_NEIGHBORS` — an `O(d log d)` cost on the center's own raw degree, not a bounded
partial-selection. Measured against the real 179-album graph's own worst-case hub (degree
897): ~0.16ms, real but far too small to explain the original ~50ms regression by itself.
Replaced with a bounded max-heap top-K selection (`selectTopK` in `networkExplorer.ts`),
`O(d log k)` instead of `O(d log d)` — verified byte-for-byte identical output to a full sort
across 20 random rank distributions × 6 cap sizes on a synthetic 300-degree hub fixture
(`apps/web/tests/network-explorer-state.spec.ts`).

**The dominant real cause: a benchmark methodology confound.**
`measureExplorerRecenter` always clicked "the first non-center neighbor currently
rendered" — since neighbors render sorted by prominence rank descending, this is always the
*highest-ranked* neighbor, so 50 repeats is a deterministic greedy walk toward the graph's
own most structurally prominent hub nodes, not a representative sample of recenter cost. The
first several iterations of any such walk (or of the underlying JIT/cache warm-up, or both)
consistently cost more than the rest, which then settle into a much tighter band — and
because a 50-sample p95/max statistic is highly sensitive to just 2-3 elevated early samples,
this transient dominated the originally-reported numbers. Two fix attempts were tried, one
discarded:

- **Discarded: a `page.goBack()`-based "repeat the exact same edge" control.** Restoring the
  original center via browser back navigation between each timed sample measured **worse and
  far noisier** than the plain walk (p95 535ms / max 1502ms vs. the walk's own 213ms / 496ms,
  both on the real 179-album site) — the extra history round-trip's own overhead was a bigger
  confound than the one it was meant to remove.
- **Adopted: a warm-up discard.** `RECENTER_WARMUP_ITERATIONS` (10) untimed recenters now run
  before the real, timed loop starts. This alone tightened the 179-album desktop-unthrottled
  distribution from samples ranging up to 496-490ms (with a 213-172ms p95) down to a
  consistent 88-125ms band (p95 117-121ms across two runs) — a dramatically cleaner signal,
  with no new confound introduced.

**Real, controlled, two-runs-per-cell comparison (179 vs. the local 500-tier fixture), stated
qualitatively per ADR 0018 (raw figures in `local/benchmarks/2026-09-04-site-reprofile-{179,
500-tier}-warmup-fix-*.json`, gitignored):**

| Profile | 179-album p50 / p95 / max | 500-album p50 / p95 / max |
|---|---|---|
| Desktop unthrottled (2 runs each) | ~102-103 / 117-121 / 120-125 | ~102-104 / 133-140 / 158-165 |
| Desktop 4x-throttled | ~105 / 121 / 131 | ~102 / 114 / 118 |
| Mobile 4x-throttled | ~100 / 113 / 124 | ~100 / 112 / 126 |

**Corrected conclusion, replacing the previous addendum's "misses in all three profiles":**

1. **Median recenter cost (p50) is essentially identical regardless of catalog size, in
   every profile** — direct, controlled confirmation of the static-analysis finding above:
   recenter cost genuinely does not scale with total graph size.
2. **p95/max show a modest, real, and repeatable (confirmed across 2 runs) increase
   specifically on desktop *unthrottled* at 500 vs. 179 albums** (roughly +15-40ms) — **but
   not on either throttled profile**, where 500-album numbers are flat or marginally better
   than 179-album's. This is a real, narrow, profile-specific effect, not a general
   catalog-size scaling problem, and its own cause is not yet identified (a candidate for
   future investigation, not blocking).
3. **The recenter budget (p95 ≤ 100ms) is marginally missed in essentially the SAME way at
   both catalog sizes, in every profile.** This is a pre-existing condition — present at 179
   albums, before any Phase 2 growth at all, matching this ADR's own first addendum's "close
   to, but still marginally above" framing — not a new failure introduced by growing to 500
   albums.

**Revised decision: tiles are not indicated by this evidence.** Tiles solve a cost that scales
*with* catalog/payload size; the real, controlled data shows recenter cost is roughly
constant across a 2.79x catalog-size range, with only a narrow, small, single-profile
exception. Building a tiles architecture — a genuinely large investment (a second load path,
the recentering-onto-non-anchor-node complication this ADR already flagged) — would not
address a scaling problem, because the evidence no longer shows one. **Phase 2 catalog
growth is not blocked on an Explore rendering-architecture change.** The remaining ~10-40ms
gap-to-budget is a general, roughly-constant per-recenter cost (plausibly the full `innerHTML`
DOM rebuild `renderView` does on every recenter, or generic browser style-recalc/layout
work) worth a future, much smaller optimization pass if desired — not an architecture
decision, and not a Phase 2 gate.

## Revisit trigger (added 2026-09-04, root-cause addendum)

- If a future measurement at real Phase 2 catalog scale (not this bounded synthetic fixture)
  shows the desktop-unthrottled-specific p95 gap growing further, investigate that narrow
  effect specifically (e.g. via a DevTools/Playwright performance trace) rather than
  reflexively re-opening the tiles question.
- If a genuinely smaller, low-risk win to close the remaining ~10-40ms gap-to-budget is later
  identified (e.g. incremental DOM diffing instead of `renderView`'s full `innerHTML`
  rebuild), it can be pursued on its own merits — not because Phase 2 is blocked on it, since
  this addendum found it is not.
