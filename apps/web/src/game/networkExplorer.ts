// Network Explorer (Phase 2 Slice G): a focused, bounded, non-force-directed
// expandable graph around one album or contributor at a time. Pure, DOM-free
// state derivation over the same pathfinding graph Connect Two Records uses
// (ADR 0050/0052) -- no new backend artifact, no unbounded growth: every
// view shows the center plus a capped neighbor radius, never the whole
// graph, and clicking a neighbor REPLACES the view (recenters) rather than
// adding to it.

import type { PathfindingGraph } from "./pathfindingGraph";
import type { Contributor } from "../data/contributors";
import { isBackgroundEngineeringRole } from "./roleTaxonomy";

export const MAX_NEIGHBORS = 24;

export interface ExplorerNode {
  artistId: number;
  name: string;
  roleCategories: string[];
  isCenter: boolean;
}

export interface ExplorerEdge {
  neighborArtistId: number;
  releaseId: number;
  roleCenter: string;
  roleNeighbor: string;
}

export interface ExplorerView {
  center: ExplorerNode;
  neighbors: ExplorerNode[];
  edges: ExplorerEdge[];
  /** True when this center has more real neighbors than `MAX_NEIGHBORS` --
   * shown so the UI can say "showing 24 of 61", never imply completeness. */
  truncated: boolean;
  /** The real total neighbor count before truncation -- always
   * `neighbors.length` when `truncated` is false, always the count "showing
   * 24 of 61" needs when it's true. Exposed unconditionally rather than
   * only when truncated, so a caller never has to special-case which field
   * holds the real total. */
  totalNeighborCount: number;
}

function roleCategoriesFor(
  artistId: number,
  contributorByArtistId: Map<number, Contributor>,
): string[] {
  return contributorByArtistId.get(artistId)?.role_categories ?? [];
}

/** The bounded neighborhood of one artist in the pathfinding graph, ranked
 * by the neighbor's own degree (connection_count) so the most-documented,
 * most-navigable contributors surface first when a hub has more real
 * neighbors than the display cap. Returns null if the artist isn't in this
 * graph's scope at all. */
export function buildView(
  graph: PathfindingGraph,
  artistIndex: Map<number, number>,
  contributorByArtistId: Map<number, Contributor>,
  centerArtistId: number,
  maxNeighbors: number = MAX_NEIGHBORS,
): ExplorerView | null {
  // Defense-in-depth, mirroring the neighbor-side guard below: a v2 graph's
  // node_ids legitimately contains negative virtual album-anchor ids
  // (ADR 0058), so artistIndex.get would otherwise happily resolve one and
  // build a "view" centered on a synthetic album node rather than a real
  // contributor. Every real caller (explorerStage.ts) only ever passes a
  // real, positive artist id today -- this guard has no effect on any
  // currently-reachable input, only on a future caller that might not
  // uphold that.
  if (centerArtistId < 0) return null;
  const centerIndex = artistIndex.get(centerArtistId);
  if (centerIndex === undefined) return null;

  const start = graph.offsets[centerIndex];
  const end = graph.offsets[centerIndex + 1];
  const candidates: {
    neighborArtistId: number;
    releaseId: number;
    roleCenter: string;
    roleNeighbor: string;
  }[] = [];
  for (let slot = start; slot < end; slot++) {
    const neighborIndex = graph.neighbors[slot];
    const neighborArtistId = graph.node_ids[neighborIndex];
    // v2 graphs (ADR 0058) add one synthetic, negative-id virtual node per
    // catalog album, bidirectionally edge-connected to every real credited
    // contributor -- Explorer walks real people's real neighborhoods, never
    // a virtual album anchor. Real Discogs artist_ids are always positive,
    // so this also doubles as a defensive check against the sentinel role
    // ever leaking through on a v2 graph.
    if (neighborArtistId < 0) continue;
    candidates.push({
      neighborArtistId,
      releaseId: graph.evidence_release_ids[slot],
      roleCenter: graph.edge_role_a[slot],
      roleNeighbor: graph.edge_role_b[slot],
    });
  }

  const degreeOf = (artistId: number) =>
    contributorByArtistId.get(artistId)?.connection_count ?? 0;
  candidates.sort(
    (a, b) => degreeOf(b.neighborArtistId) - degreeOf(a.neighborArtistId),
  );

  const shown = candidates.slice(0, maxNeighbors);
  const center: ExplorerNode = {
    artistId: centerArtistId,
    name: graph.names[centerIndex],
    roleCategories: roleCategoriesFor(centerArtistId, contributorByArtistId),
    isCenter: true,
  };
  const neighbors: ExplorerNode[] = shown.map((edge) => ({
    artistId: edge.neighborArtistId,
    name:
      graph.names[artistIndex.get(edge.neighborArtistId) ?? -1] ??
      `Artist ${edge.neighborArtistId}`,
    roleCategories: roleCategoriesFor(
      edge.neighborArtistId,
      contributorByArtistId,
    ),
    isCenter: false,
  }));
  const edges: ExplorerEdge[] = shown.map((edge) => ({
    neighborArtistId: edge.neighborArtistId,
    releaseId: edge.releaseId,
    roleCenter: edge.roleCenter,
    roleNeighbor: edge.roleNeighbor,
  }));

  return {
    center,
    neighbors,
    edges,
    truncated: candidates.length > maxNeighbors,
    totalNeighborCount: candidates.length,
  };
}

/** A node is dimmed (not removed -- evidence stays visible even
 * de-emphasized) for either of two reasons, the center exempt from both:
 * a role filter is active and the node matches none of the active
 * categories, or (2026-08-31 addition, independent of any filter) the
 * edge connecting this neighbor to the current center is
 * background-engineering-only (Mastered By/Recorded By/Mixed By on either
 * side, `roleTaxonomy.ts`'s `isBackgroundEngineeringRole`) -- a real
 * documented credit, just visually de-emphasized the same way an
 * unfiltered role already is. `edge` is the neighbor's own edge to the
 * center; omitted (or the center's own call, which has none) skips that
 * second check. */
export function isDimmed(
  node: ExplorerNode,
  activeCategories: ReadonlySet<string>,
  edge?: ExplorerEdge,
): boolean {
  if (node.isCenter) return false;
  if (activeCategories.size > 0) {
    if (
      !node.roleCategories.some((category) => activeCategories.has(category))
    ) {
      return true;
    }
  }
  if (
    edge &&
    (isBackgroundEngineeringRole(edge.roleCenter) ||
      isBackgroundEngineeringRole(edge.roleNeighbor))
  ) {
    return true;
  }
  return false;
}
