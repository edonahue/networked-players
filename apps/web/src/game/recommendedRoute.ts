// The recommended-route engine (ADR 0059, Phase 5 PR 3): ranks a bounded
// set of equal-hop candidates instead of returning whichever route
// `findAlbumRoute`'s plain BFS happens to touch first. That tie-break is
// not a choice about quality -- it is an accident of CSR node-index order,
// which the ADR measured as biased toward low-Discogs-id hub artists.
//
// This module does NOT replace `findAlbumRoute` or `findPath`: the
// "Shortest documented route" a player can independently verify is still
// exactly that function's literal first-found result. This module adds a
// second, GENUINELY RANKED pick alongside it, built from source-derived
// signals only:
//
//   - evidence quality: the published registry-v2 caveat severity of each
//     hop's evidence release (compilation/mixed/promo/reissue/sampler/
//     unofficial) -- never a positive "clean" claim, only "no known
//     caveat" versus "tagged with one", per the registry's own documented
//     semantics (data/contracts/evidence-release-registry-v1.md).
//   - hub dependence: real CSR node degree (`offsets[i+1]-offsets[i]`),
//     available for 100% of nodes at zero extra cost -- the direct fix for
//     what made the removed `scorePath` (PR #104) unusable: it read
//     `contributors/index.v1.json`'s `connection_count`, which the ADR
//     measured at 1.46% node coverage.
//   - role substance: `roleTaxonomy.ts`'s `isPerformerRole`, a real
//     instrument/vocal classification, not a popularity or LLM signal.
//   - hop count, trivially equal within one enumerated layer.
//
// No LLM, embedding, vector, popularity, streaming, or external-API
// signal. No hidden blacklist: a release is only ever de-preferred by a
// field the UI is willing to show the player (the caveat flag itself).
// Nothing here implies friendship, influence, or musical lineage -- a
// shared, ranked credit remains documented co-participation and nothing
// more.

import type { EvidenceIndex } from "./connectEvidence";
import {
  ALBUM_ANCHOR_HOP_BUDGET,
  ALBUM_ANCHOR_SENTINEL,
  edgeKeysForHops,
  findAlbumRoute,
  stripAlbumAnchors,
  type AlbumEndpoint,
  type PathfindingFailureReason,
  type PathfindingGraph,
  type PathHop,
} from "./pathfindingGraph";
import { isPerformerRole } from "./roleTaxonomy";

/** Caveat severity tiers, worst first -- mirrors graph-core's
 * `EVIDENCE_CAVEAT_TIERS` (`packages/graph-core/.../graph.py`) exactly, so
 * the release the BUILDER already de-prefers when picking evidence is the
 * same one this RANKER de-prefers when picking a route. A flat "has any
 * caveat" test cannot tell a bootleg from a reissue -- measured on the
 * real corpus, that conflation traded reissue-evidenced edges for
 * unofficial-evidenced ones on aggregate, which is the wrong direction on
 * the category that matters most (see the Phase 5 PR 2 commit history).
 *
 * Severity 0 means "no flag names in this tier matched" -- callers must
 * still check `EvidenceIndex.caveatFlagNames.length > 0` separately, since
 * severity 0 is also what an unavailable registry produces. */
const CAVEAT_SEVERITY_TIERS: readonly (readonly string[])[] = [
  ["unofficial"],
  ["compilation", "mixed", "sampler"],
  ["promo", "reissue"],
];

/** Highest severity tier (3 = worst/unofficial, 1 = mildest, 0 = none)
 * present in `flags`, read against the registry's own published
 * `caveatFlagNames` bit order -- never a hardcoded bit position. */
function caveatSeverity(flags: number, caveatFlagNames: string[]): number {
  if (caveatFlagNames.length === 0) return 0;
  for (let tier = 0; tier < CAVEAT_SEVERITY_TIERS.length; tier++) {
    const names = CAVEAT_SEVERITY_TIERS[tier];
    for (let bit = 0; bit < caveatFlagNames.length; bit++) {
      if (names.includes(caveatFlagNames[bit]) && (flags >> bit) & 1) {
        return CAVEAT_SEVERITY_TIERS.length - tier;
      }
    }
  }
  return 0;
}

/** Facts a candidate is ranked and explained by -- the SAME facts, so the
 * rendered "why this route" text can never drift into a parallel
 * narrative that doesn't match the ranking that actually ran. */
export interface RouteFacts {
  hopCount: number;
  /** `null` only when the evidence registry carried no caveat vocabulary
   * at all (a v1 registry, or a fetch that failed) -- distinct from 0,
   * which means real data was available and found no caveat. */
  worstCaveatSeverity: number | null;
  /** Highest CSR degree among the route's real (non-endpoint) contributor
   * nodes. Lower is less hub-dependent. */
  maxInteriorDegree: number;
  performerHopCount: number;
}

export interface RankedRoute {
  endpointA: AlbumEndpoint;
  hops: PathHop[];
  endpointB: AlbumEndpoint;
  usedEdgeKeys: Set<string>;
  facts: RouteFacts;
}

interface RawCandidate {
  nodeIndices: number[];
  slots: number[];
}

/** Reverse-BFS distance guide from `goalIndex`, bounded by `maxDepth` and
 * a shared expansion budget -- the admissible remaining-budget bound that
 * keeps the forward walk from exploring branches that can never reach the
 * goal in time. Mirrors `route_quality.py`'s `_reverse_distances`,
 * including its two hard-won lessons from that module's own review
 * history: every scanned slot is charged to the budget BEFORE the
 * per-slot checks (a slot inspected and rejected still cost a read), and
 * expansion never continues out of a non-goal virtual album anchor (an
 * anchor is an endpoint, never a through-route). */
function reverseDistances(
  graph: PathfindingGraph,
  goalIndex: number,
  maxDepth: number,
  budget: { remaining: number },
  edgeFilter?: (roleA: string, roleB: string) => boolean,
): { distances: Map<number, number>; exhausted: boolean } {
  const distances = new Map<number, number>([[goalIndex, 0]]);
  let frontier = [goalIndex];
  let exhausted = false;

  while (frontier.length > 0 && !exhausted) {
    const next: number[] = [];
    for (const node of frontier) {
      const depth = distances.get(node) as number;
      if (depth >= maxDepth) continue;
      if (depth > 0 && graph.node_ids[node] < 0) continue;
      const begin = graph.offsets[node];
      const end = graph.offsets[node + 1];
      for (let slot = begin; slot < end; slot++) {
        if (budget.remaining <= 0) {
          exhausted = true;
          break;
        }
        budget.remaining--;
        // Filter-aware for the same reason the forward walk is: the CSR
        // is undirected (every edge stored both ways), so `node`'s own
        // outgoing slot here means exactly the same "node -> neighbor"
        // thing the forward walk would read at this same slot index --
        // no direction-flipping needed. Without this, `shortestPossible`
        // below would be the UNFILTERED shortest depth, and an exact-
        // depth search at that depth under a filter that the true
        // shortest path's edges don't satisfy would falsely report
        // no-path even though a real, filter-compliant route exists one
        // or more hops further out.
        if (
          edgeFilter &&
          !edgeFilter(graph.edge_role_a[slot], graph.edge_role_b[slot])
        ) {
          continue;
        }
        const neighbor = graph.neighbors[slot];
        if (distances.has(neighbor)) continue;
        distances.set(neighbor, depth + 1);
        next.push(neighbor);
      }
      if (exhausted) break;
    }
    frontier = next;
  }
  return { distances, exhausted };
}

/** Collects every route of exactly `targetDepth` hops from `startIndex` to
 * `goalIndex`, pruned by the reverse-distance guide. Mirrors
 * `route_quality.py`'s `walk`: every inspected adjacency slot is charged
 * to the budget before the on-path/anchor/reachability/filter checks (the
 * same forward-walk accounting fix that module's own review found), and
 * the route cap is checked BEFORE a route is appended, so a capped run
 * never holds one more route than it reports. */
function collectExactDepthRoutes(
  graph: PathfindingGraph,
  startIndex: number,
  goalIndex: number,
  targetDepth: number,
  distances: Map<number, number>,
  budget: { remaining: number },
  maxRoutes: number,
  edgeFilter?: (roleA: string, roleB: string) => boolean,
): { routes: RawCandidate[]; complete: boolean } {
  const routes: RawCandidate[] = [];
  const onPath = new Set<number>([startIndex]);
  const pathNodes = [startIndex];
  const pathSlots: number[] = [];
  let complete = true;

  function walk(node: number, depth: number): boolean {
    if (node === goalIndex) {
      if (depth === targetDepth) {
        if (routes.length >= maxRoutes) return false;
        routes.push({ nodeIndices: [...pathNodes], slots: [...pathSlots] });
      }
      return true;
    }
    const remaining = targetDepth - depth;
    if (remaining <= 0) return true;

    const begin = graph.offsets[node];
    const end = graph.offsets[node + 1];
    for (let slot = begin; slot < end; slot++) {
      if (budget.remaining <= 0) return false;
      budget.remaining--;

      const neighbor = graph.neighbors[slot];
      if (onPath.has(neighbor)) continue;
      if (graph.node_ids[neighbor] < 0 && neighbor !== goalIndex) continue;
      const reachable = distances.get(neighbor);
      if (reachable === undefined || reachable > remaining - 1) continue;
      if (
        edgeFilter &&
        !edgeFilter(graph.edge_role_a[slot], graph.edge_role_b[slot])
      ) {
        continue;
      }

      onPath.add(neighbor);
      pathNodes.push(neighbor);
      pathSlots.push(slot);
      const keepGoing = walk(neighbor, depth + 1);
      pathNodes.pop();
      pathSlots.pop();
      onPath.delete(neighbor);
      if (!keepGoing) return false;
    }
    return true;
  }

  complete = walk(startIndex, 0);
  return { routes, complete };
}

function rawCandidateToHops(
  graph: PathfindingGraph,
  candidate: RawCandidate,
): PathHop[] {
  const hops: PathHop[] = [];
  for (let i = 0; i < candidate.slots.length; i++) {
    const parent = candidate.nodeIndices[i];
    const node = candidate.nodeIndices[i + 1];
    const slot = candidate.slots[i];
    hops.push({
      release_id: graph.evidence_release_ids[slot],
      artist_a_id: graph.node_ids[parent],
      artist_b_id: graph.node_ids[node],
      role_a: graph.edge_role_a[slot],
      role_b: graph.edge_role_b[slot],
    });
  }
  return hops;
}

/** Enumeration bounds -- matched to the research harness's own corrected
 * default (`research-route-quality`'s `--max-expansions 400000`, ADR 0059
 * PR 1 round-10 fix), not chosen independently: the worst single sampled
 * pair there consumed 358,505 shared-budget slots to complete its
 * shortest layer whole, and this engine shares the same reverse-precompute
 * -plus-forward-walk budget design. A smaller client cap would silently
 * under-search exactly the pairs the research measurement proved need the
 * full budget to avoid a partial, order-dependent sample.
 *
 * Observed locally (this machine, the committed graph.v2.json artifact,
 * Node 22, warm/post-JIT): both the diagnostic pair (Discovery/The Joshua
 * Tree) and the research sample's worst pair (master-24047/master-3878)
 * run in ~34ms under these caps -- see the ADR's PR 3 addendum for the
 * reproduction script. Neither pair came close to exhausting the budget
 * (`shortestLayerComplete: true` for both), so this is comfortably inside
 * a single click-to-result interaction, not a worst-case timing. */
export const DEFAULT_MAX_EXPANSIONS = 400_000;
export const DEFAULT_MAX_ROUTES = 300;

export interface RankedLayer {
  targetDepth: number;
  candidates: RankedRoute[];
  complete: boolean;
}

function degreeOf(graph: PathfindingGraph, nodeIndex: number): number {
  return graph.offsets[nodeIndex + 1] - graph.offsets[nodeIndex];
}

/** Public so both the ranking engine and a plain `findAlbumRoute` result
 * (the distinct-alternate route, which is never enumerated/ranked, only
 * found by exclusion BFS) can be explained from the same facts. Works
 * directly on already-stripped hops -- every artist id in `hops` is a
 * real contributor by construction (`stripAlbumAnchors` already removed
 * the two virtual album-anchor hops), so no endpoint special-casing is
 * needed here the way the raw virtual-node candidate needed it. */
export function computeRouteFacts(
  graph: PathfindingGraph,
  artistIndex: Map<number, number>,
  hops: PathHop[],
  evidenceIndex: EvidenceIndex,
): RouteFacts {
  const haveCaveatData = evidenceIndex.caveatFlagNames.length > 0;
  let worstKnownSeverity = 0;
  // Distinct from "checked and found no caveat": the published graph is
  // cached in sessionStorage and can outlive a deploy that ships a fresh
  // registry (`loadPathfindingGraph`'s own caching), so a release id this
  // hop's graph references may simply be ABSENT from an otherwise-real,
  // populated registry -- exactly the staleness pattern ADR 0059's PR 2
  // section measured (3,728 ids the old graph referenced but the new
  // registry didn't cover, understating caveats when conflated with "no
  // caveat"). Reading `?? 0` for a missing release would repeat that
  // mistake at query time instead of build time.
  let anyReleaseMissing = false;
  let performerHopCount = 0;
  const interiorNodeIndices = new Set<number>();

  for (const hop of hops) {
    if (haveCaveatData) {
      const release = evidenceIndex.releases.get(hop.release_id);
      if (release === undefined) {
        anyReleaseMissing = true;
      } else {
        worstKnownSeverity = Math.max(
          worstKnownSeverity,
          caveatSeverity(release.caveatFlags, evidenceIndex.caveatFlagNames),
        );
      }
    }
    if (isPerformerRole(hop.role_a) || isPerformerRole(hop.role_b)) {
      performerHopCount++;
    }
    const aIndex = artistIndex.get(hop.artist_a_id);
    const bIndex = artistIndex.get(hop.artist_b_id);
    if (aIndex !== undefined) interiorNodeIndices.add(aIndex);
    if (bIndex !== undefined) interiorNodeIndices.add(bIndex);
  }

  let maxInteriorDegree = 0;
  for (const nodeIndex of interiorNodeIndices) {
    maxInteriorDegree = Math.max(maxInteriorDegree, degreeOf(graph, nodeIndex));
  }

  // A known caveat is reported regardless of what else is unknown --
  // hiding a REAL caveat behind uncertainty about an unrelated hop would
  // conceal evidence, which this whole engine exists never to do. Only a
  // would-be "clean" claim (worstKnownSeverity 0) downgrades to unknown
  // when some evidence couldn't be checked at all.
  const worstCaveatSeverity = !haveCaveatData
    ? null
    : anyReleaseMissing && worstKnownSeverity === 0
      ? null
      : worstKnownSeverity;

  return {
    hopCount: hops.length,
    worstCaveatSeverity,
    maxInteriorDegree,
    performerHopCount,
  };
}

/** Ascending = better. Deterministic total order: caveat severity, then
 * hub dependence, then role substance, then a canonical string tiebreak
 * over the route's own edge keys -- stable regardless of CSR enumeration
 * order, so two runs over the same graph always agree. */
function compareRanked(a: RankedRoute, b: RankedRoute): number {
  const aCaveat = a.facts.worstCaveatSeverity ?? 0;
  const bCaveat = b.facts.worstCaveatSeverity ?? 0;
  if (aCaveat !== bCaveat) return aCaveat - bCaveat;
  if (a.facts.maxInteriorDegree !== b.facts.maxInteriorDegree) {
    return a.facts.maxInteriorDegree - b.facts.maxInteriorDegree;
  }
  const aNonPerformer = a.facts.hopCount - a.facts.performerHopCount;
  const bNonPerformer = b.facts.hopCount - b.facts.performerHopCount;
  if (aNonPerformer !== bNonPerformer) return aNonPerformer - bNonPerformer;
  const aKey = [...a.usedEdgeKeys].sort().join("|");
  const bKey = [...b.usedEdgeKeys].sort().join("|");
  return aKey < bKey ? -1 : aKey > bKey ? 1 : 0;
}

/** Enumerates and ranks every route at exactly `targetDepth` virtual-node
 * hops between two album anchors. `distances`/`budget` are shared with the
 * caller so a subsequent +1-hop call (see `selectRecommendedRoute`) never
 * re-runs the reverse precompute -- the single most expensive part of the
 * search (ADR 0059 measured it as the largest component, up to 86% of the
 * whole bounded search). */
function rankExactDepthLayer(
  graph: PathfindingGraph,
  artistIndex: Map<number, number>,
  startIndex: number,
  goalIndex: number,
  targetDepth: number,
  distances: Map<number, number>,
  budget: { remaining: number },
  evidenceIndex: EvidenceIndex,
  maxRoutes: number,
  edgeFilter?: (roleA: string, roleB: string) => boolean,
): RankedLayer {
  const { routes, complete } = collectExactDepthRoutes(
    graph,
    startIndex,
    goalIndex,
    targetDepth,
    distances,
    budget,
    maxRoutes,
    edgeFilter,
  );
  const ranked: RankedRoute[] = [];
  for (const raw of routes) {
    const hops = rawCandidateToHops(graph, raw);
    const stripped = stripAlbumAnchors(hops);
    if (!stripped) continue; // structurally impossible for a real v2 graph; skip defensively
    ranked.push({
      ...stripped,
      usedEdgeKeys: edgeKeysForHops(hops),
      facts: computeRouteFacts(
        graph,
        artistIndex,
        stripped.hops,
        evidenceIndex,
      ),
    });
  }
  ranked.sort(compareRanked);
  return { targetDepth, candidates: ranked, complete };
}

export type RecommendedRouteResult =
  | {
      ok: true;
      recommended: RankedRoute;
      /** True only when every shortest-layer candidate carried the worst
       * caveat severity AND a strictly better-evidenced route existed one
       * hop further out -- the sole, hard-capped, explicitly-labeled
       * exception to "recommend from the shortest layer" (ADR 0059). */
      usedPlusOneHop: boolean;
      shortestLayerComplete: boolean;
      /** True whenever `recommended` was not chosen from a COMPLETE
       * ranked layer -- either because enumeration couldn't run at all
       * (caps exhausted before finding any candidate) and degraded to
       * `findAlbumRoute`'s plain first-found route, or because a route/
       * expansion cap fired mid-enumeration and left a real but
       * arbitrary, CSR-order-dependent PARTIAL candidate set. Either way
       * `recommended` is still a real, correct route -- just not one a
       * genuine ranking is known to have picked as the best available,
       * so the label downgrades from "Recommended" to "Shortest"
       * accordingly. Required fallback per ADR 0059's invariant list. */
      rankingDegraded: boolean;
    }
  | { ok: false; reason: PathfindingFailureReason };

/** The recommended-route engine's single entry point. Enumerates the
 * complete shortest virtual-node layer between two albums, ranks it, and
 * -- only when every shortest-layer candidate is evidenced at the worst
 * caveat severity -- checks one hop further for a better-evidenced
 * alternative. Falls back to `findAlbumRoute`'s plain result if bounded
 * enumeration cannot produce a real candidate at all. */
export function selectRecommendedRoute(
  graph: PathfindingGraph,
  artistIndex: Map<number, number>,
  albumIndex: Map<string, number>,
  fromAlbumId: string,
  toAlbumId: string,
  evidenceIndex: EvidenceIndex,
  maxUserHops = 4,
  edgeFilter?: (roleA: string, roleB: string) => boolean,
  maxRoutes = DEFAULT_MAX_ROUTES,
  maxExpansions = DEFAULT_MAX_EXPANSIONS,
): RecommendedRouteResult {
  const fallback = (): RecommendedRouteResult => {
    const plain = findAlbumRoute(
      graph,
      artistIndex,
      albumIndex,
      fromAlbumId,
      toAlbumId,
      maxUserHops,
      edgeFilter,
    );
    if (!plain.ok) return plain;
    return {
      ok: true,
      recommended: {
        endpointA: plain.endpointA,
        hops: plain.hops,
        endpointB: plain.endpointB,
        usedEdgeKeys: plain.usedEdgeKeys,
        facts: {
          hopCount: plain.hops.length,
          worstCaveatSeverity: null,
          maxInteriorDegree: 0,
          performerHopCount: 0,
        },
      },
      usedPlusOneHop: false,
      shortestLayerComplete: false,
      rankingDegraded: true,
    };
  };

  // `albumIndex` maps album_id -> VIRTUAL ARTIST ID (a negative node_ids
  // value, e.g. -23), not a CSR node index -- the same two-step lookup
  // `findAlbumRoute` does via `findPath`'s own `artistIndex.get`. Every
  // function below this point operates on node INDICES into
  // `graph.offsets`/`graph.neighbors`, so skipping the second lookup and
  // passing the virtual artist id straight through silently walks the
  // wrong node (caught by a real diagnostic-pair run returning a false
  // "no-path" for a documented 1-hop connection).
  const fromVirtualId = albumIndex.get(fromAlbumId);
  const toVirtualId = albumIndex.get(toAlbumId);
  if (fromVirtualId === undefined || toVirtualId === undefined) {
    return { ok: false, reason: "unknown-album" };
  }
  const startIndex = artistIndex.get(fromVirtualId);
  const goalIndex = artistIndex.get(toVirtualId);
  if (startIndex === undefined || goalIndex === undefined) {
    return { ok: false, reason: "unknown-album" };
  }
  const maxDepth = maxUserHops + ALBUM_ANCHOR_HOP_BUDGET;
  // Never applied to an anchor edge -- its role is always the sentinel,
  // which cannot match a real role-filter predicate, and applying the
  // caller's filter to it unwrapped would make every role-filtered search
  // fail to leave the start album's anchor at all. Same fix
  // `findAlbumRoute` already applies; unreachable from connect.ts today
  // (role-filtered searches use `findAlbumRoute` directly, never this
  // engine) but a real correctness requirement for this exported function
  // regardless of today's one caller.
  const anchorAwareFilter = edgeFilter
    ? (roleA: string, roleB: string): boolean =>
        roleA === ALBUM_ANCHOR_SENTINEL || roleB === ALBUM_ANCHOR_SENTINEL
          ? true
          : edgeFilter(roleA, roleB)
    : undefined;

  const budget = { remaining: maxExpansions };
  // No deeper than `maxDepth`: the forward walk only ever consults a
  // distance value at `targetDepth - 1` (checked at its own depth-0 step),
  // and `targetDepth` never exceeds `maxDepth` -- the shortest layer is
  // gated by `shortestPossible <= maxDepth` above, and the +1-hop layer by
  // `shortestPossible + 1 <= maxDepth` below. An earlier version passed
  // `maxDepth + 1` "so the +1-hop call could reuse this guide", which was
  // already one layer more than even that stated intent needed -- a real
  // review finding: on the shared 400,000-slot budget the ADR's own worst
  // measured pair already consumes 358,505 of, an unnecessary extra layer
  // of reverse-BFS could be the difference between completing and
  // spuriously exhausting the budget on a denser pair.
  const { distances, exhausted } = reverseDistances(
    graph,
    goalIndex,
    maxDepth,
    budget,
    anchorAwareFilter,
  );
  if (exhausted) return fallback();

  const shortestPossible = distances.get(startIndex);
  if (shortestPossible === undefined) {
    return { ok: false, reason: "no-path" };
  }
  if (shortestPossible > maxDepth) {
    return { ok: false, reason: "no-path" };
  }

  const shortestLayer = rankExactDepthLayer(
    graph,
    artistIndex,
    startIndex,
    goalIndex,
    shortestPossible,
    distances,
    budget,
    evidenceIndex,
    maxRoutes,
    anchorAwareFilter,
  );
  if (shortestLayer.candidates.length === 0) {
    return shortestLayer.complete
      ? { ok: false, reason: "no-path" }
      : fallback();
  }

  const WORST_SEVERITY = CAVEAT_SEVERITY_TIERS.length;
  const best = shortestLayer.candidates[0];
  const everyCandidateWorstTier = shortestLayer.candidates.every(
    (c) => (c.facts.worstCaveatSeverity ?? 0) === WORST_SEVERITY,
  );

  if (
    shortestLayer.complete &&
    everyCandidateWorstTier &&
    best.facts.worstCaveatSeverity === WORST_SEVERITY &&
    shortestPossible + 1 <= maxDepth
  ) {
    // Gated on `shortestLayer.complete`: a truncated layer's
    // "every candidate is worst-tier" is only true of the candidates
    // ENUMERATED so far, not of the real layer -- an uncollected candidate
    // beyond the cap could have been clean. Searching +1 hop under that
    // false premise would recommend an unnecessarily longer route while a
    // real, undiscovered shortest-hop clean route sat just past the cap.
    const plusOneLayer = rankExactDepthLayer(
      graph,
      artistIndex,
      startIndex,
      goalIndex,
      shortestPossible + 1,
      distances,
      budget,
      evidenceIndex,
      maxRoutes,
      anchorAwareFilter,
    );
    const plusOneBest = plusOneLayer.candidates[0];
    if (
      plusOneBest &&
      (plusOneBest.facts.worstCaveatSeverity ?? 0) < WORST_SEVERITY
    ) {
      return {
        ok: true,
        recommended: plusOneBest,
        usedPlusOneHop: true,
        shortestLayerComplete: shortestLayer.complete,
        // A truncated +1 layer may not have found the TRUE best of that
        // layer, only *a* better-than-worst-tier candidate -- real
        // evidence such a route exists, but not the same rigor the
        // "Recommended" label claims. Mirrors the shortest-layer check
        // below for the same reason: a partial, CSR-order-dependent
        // prefix is not a sample (ADR 0059).
        rankingDegraded: !plusOneLayer.complete,
      };
    }
  }

  return {
    ok: true,
    recommended: best,
    usedPlusOneHop: false,
    shortestLayerComplete: shortestLayer.complete,
    // A route cap or expansion-budget cap firing mid-enumeration leaves
    // `candidates` non-empty but ARBITRARY -- an accident of CSR walk
    // order, exactly the bias this whole engine exists to remove. Ranking
    // a partial layer and still calling it "Recommended" would silently
    // reintroduce that bias; `best` is still returned (a real, correct
    // route beats none), but the claim downgrades honestly.
    rankingDegraded: !shortestLayer.complete,
  };
}

const SEVERITY_LABELS: Record<number, string> = {
  3: "an unofficial or bootleg release",
  2: "a compilation, mix, or sampler",
  1: "a promo or reissue pressing",
};

/** Human-readable facts, generated directly from `RouteFacts` -- never a
 * parallel narrative computed some other way (ADR 0059's honest-labels
 * requirement). Presentational only; never re-derives or overrides the
 * ranking that already ran. */
export function explainRoute(
  facts: RouteFacts,
  usedPlusOneHop: boolean,
): string[] {
  const lines: string[] = [
    `${facts.hopCount} hop${facts.hopCount === 1 ? "" : "s"}`,
  ];

  if (facts.worstCaveatSeverity !== null) {
    lines.push(
      facts.worstCaveatSeverity > 0
        ? `at least one hop is evidenced by ${SEVERITY_LABELS[facts.worstCaveatSeverity] ?? "a caveated release"}`
        : "no hop's evidence carries a published caveat",
    );
  }

  lines.push(
    facts.performerHopCount === facts.hopCount
      ? "every hop is bridged by a documented performer"
      : `${facts.performerHopCount} of ${facts.hopCount} hop${facts.hopCount === 1 ? "" : "s"} bridged by a documented performer`,
  );

  lines.push(
    `most-connected contributor on this route has ${facts.maxInteriorDegree} documented connection${facts.maxInteriorDegree === 1 ? "" : "s"}`,
  );

  if (usedPlusOneHop) {
    lines.push(
      "one hop longer than the shortest documented route, because every shortest-hop option was evidenced only by " +
        (SEVERITY_LABELS[3] ?? "a caveated release"),
    );
  }

  return lines;
}
