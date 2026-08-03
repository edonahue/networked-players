// Network Explorer (Phase 2 Slice G): a focused, bounded, non-force-directed
// expandable graph around one album or contributor at a time. Pure, DOM-free
// state derivation over the same pathfinding graph Connect Two Records uses
// (ADR 0050/0052) -- no new backend artifact, no unbounded growth: every
// view shows the center plus a capped neighbor radius, never the whole
// graph, and clicking a neighbor REPLACES the view (recenters) rather than
// adding to it.

import type { PathfindingGraph } from "./pathfindingGraph";
import type { Contributor } from "../data/contributors";

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
    candidates.push({
      neighborArtistId: graph.node_ids[neighborIndex],
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
  };
}

/** A node is dimmed (not removed -- evidence stays visible even
 * de-emphasized) when a role filter is active and the node matches none of
 * the active categories. The center is never dimmed. */
export function isDimmed(
  node: ExplorerNode,
  activeCategories: ReadonlySet<string>,
): boolean {
  if (node.isCenter) return false;
  if (activeCategories.size === 0) return false;
  return !node.roleCategories.some((category) =>
    activeCategories.has(category),
  );
}
