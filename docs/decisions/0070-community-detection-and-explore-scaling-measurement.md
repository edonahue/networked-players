# ADR 0070: Community detection is measured and denied; Explore scaling gets a real recenter budget

- **Status:** Accepted
- **Date:** 2026-09-03
- **Extends:** [ADR 0055](0055-research-graph-library-selection.md) (igraph selection),
  [ADR 0061](0061-scope-tier-corpus-design-deferred.md), [ADR 0063](0063-bridge-contributors-promotion-rejected.md)
  (betweenness/bridge-contributor promotion, rejected) without modifying any of them
- **Relates to:** [ADR 0052](0052-network-explorer-svg-bounded-radius.md) (recenter as the
  primary Explore interaction, still holds), [ADR 0069](0069-public-universe-model-and-expansion-policy.md)

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

- No product code changes. `reprofile-site.mjs` and `graph_analysis.py` gain new,
  independently tested measurement capability; nothing in `apps/web`'s shipped pages or
  `packages/graph-core`'s builders changes.
- Phase 1 planning should explicitly budget for recenter-cost improvement, not just
  preservation, given the finding in §2.
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
