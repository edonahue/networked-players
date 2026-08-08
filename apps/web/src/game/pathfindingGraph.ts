// Runtime type + validation + BFS for the pathfinding graph artifact
// (apps/web/public/data/pathfinding/graph.v1.json / graph.v2.json,
// data/contracts/pathfinding-graph-v1.md / pathfinding-graph-v2.md, ADR
// 0050/0051/0058). A TypeScript port of compact_graph_bench.py's
// build_csr_adjacency/bfs_over_csr -- see ADR 0051's revisit trigger:
// there is no shared cross-language parity test yet, so keep this file's
// BFS logic in careful lockstep with the Python reference by inspection
// until one exists.
//
// v2 (ADR 0058) adds virtual album-anchor nodes -- one synthetic node per
// catalog album, connected to that album's real credited contributors.
// findPath itself needs no changes for this; findAlbumRoute below is a
// thin wrapper that searches between two albums' virtual nodes and strips
// the (never user-visible) anchor hops from the result.
//
// Nothing here trusts a TypeScript type assertion as runtime proof -- the
// fetched JSON is untrusted input, validated field-by-field before use,
// mirroring routesResolver.ts's hardened pattern.

export interface AlbumVirtualNode {
  album_id: string;
  virtual_artist_id: number;
  main_release_id: number;
}

export interface PathfindingGraph {
  schema_version: number;
  catalog_version: string;
  snapshot_date: string;
  generated_at: string;
  source: string;
  license: string;
  node_ids: number[];
  names: string[];
  offsets: number[];
  neighbors: number[];
  evidence_release_ids: number[];
  edge_role_a: string[];
  edge_role_b: string[];
  pathfinding_graph_version: string;
  /** Present only when schema_version === 2. */
  album_virtual_nodes?: AlbumVirtualNode[];
}

export interface PathHop {
  release_id: number;
  artist_a_id: number;
  artist_b_id: number;
  role_a: string;
  role_b: string;
}

/** Reserved role-text value marking the virtual side of an album-anchor
 * edge (v2 graphs only) -- never surfaced to a caller, since
 * `stripAlbumAnchors`/`findAlbumRoute` always remove the hop it appears
 * on before returning a result. Kept identical to the Python-side copy in
 * `networked_players_graph_core.pathfinding_graph.ALBUM_ANCHOR_SENTINEL`
 * (duplicated deliberately -- this file has no Python dependency). */
export const ALBUM_ANCHOR_SENTINEL = "__np_album_anchor__";

/** Two extra hops of BFS budget to cover the two album-anchor edges
 * (album -> first real contributor, last real contributor -> album) that
 * `findAlbumRoute` adds on top of a caller's real, user-facing hop
 * budget -- never surfaced as real hops once stripped. */
const ALBUM_ANCHOR_HOP_BUDGET = 2;

/** `no-path`: the search space was exhausted within the hop budget with no
 * path found -- a confirmed result. `inconclusive`: reserved for a future
 * per-node fan-out cap (mirroring compact_graph_bench.py's
 * `FrontierTooLargeBench`); never produced today, since this graph's bounded
 * scope (ADR 0050) makes an in-memory BFS cheap regardless of degree -- kept
 * as a distinct value so the UI never has to be rewritten to distinguish
 * the two later. `unknown-album`: one or both endpoints aren't in this
 * graph's scope at all. */
export type PathfindingFailureReason =
  | "fetch-failed"
  | "parse-failed"
  | "invalid-graph"
  | "unknown-album"
  | "inconclusive"
  | "no-path";

export type PathfindingResult =
  | { ok: true; hops: PathHop[] }
  | { ok: false; reason: PathfindingFailureReason };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isNumberArray(value: unknown): value is number[] {
  return Array.isArray(value) && value.every((v) => typeof v === "number");
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((v) => typeof v === "string");
}

/** Every structural invariant `pathfinding_graph_failures` (the Python
 * contract validator) also checks -- offsets length/monotonicity, parallel
 * array lengths, neighbor indices in range, and (schema_version 2 only)
 * album_virtual_nodes' negative/disjoint virtual ids resolving into
 * node_ids. A malformed or truncated fetch must be caught here, not
 * partway through a BFS. */
export function validatePathfindingGraph(
  value: unknown,
): PathfindingGraph | null {
  if (!isRecord(value)) return null;
  if (value.schema_version !== 1 && value.schema_version !== 2) return null;
  if (typeof value.catalog_version !== "string" || !value.catalog_version)
    return null;
  if (
    typeof value.pathfinding_graph_version !== "string" ||
    !value.pathfinding_graph_version
  ) {
    return null;
  }
  if (!isNumberArray(value.node_ids) || value.node_ids.length === 0)
    return null;
  const nodeCount = value.node_ids.length;
  if (!isStringArray(value.names) || value.names.length !== nodeCount)
    return null;
  if (!isNumberArray(value.offsets) || value.offsets.length !== nodeCount + 1)
    return null;
  if (value.offsets[0] !== 0) return null;
  if (!isNumberArray(value.neighbors)) return null;
  const slotCount = value.neighbors.length;
  if (value.offsets[nodeCount] !== slotCount) return null;
  if (
    !isNumberArray(value.evidence_release_ids) ||
    value.evidence_release_ids.length !== slotCount
  ) {
    return null;
  }
  if (
    !isStringArray(value.edge_role_a) ||
    value.edge_role_a.length !== slotCount
  )
    return null;
  if (
    !isStringArray(value.edge_role_b) ||
    value.edge_role_b.length !== slotCount
  )
    return null;
  for (const neighbor of value.neighbors) {
    if (neighbor < 0 || neighbor >= nodeCount) return null;
  }

  if (value.schema_version === 2) {
    if (!Array.isArray(value.album_virtual_nodes)) return null;
    const nodeIdSet = new Set(value.node_ids);
    const seenAlbumIds = new Set<string>();
    const seenVirtualIds = new Set<number>();
    for (const entry of value.album_virtual_nodes) {
      if (!isRecord(entry)) return null;
      const { album_id, virtual_artist_id, main_release_id } = entry;
      if (typeof album_id !== "string" || !album_id) return null;
      if (seenAlbumIds.has(album_id)) return null;
      seenAlbumIds.add(album_id);
      if (typeof virtual_artist_id !== "number" || virtual_artist_id >= 0)
        return null;
      if (seenVirtualIds.has(virtual_artist_id)) return null;
      seenVirtualIds.add(virtual_artist_id);
      if (!nodeIdSet.has(virtual_artist_id)) return null;
      if (typeof main_release_id !== "number") return null;
    }
  }

  return value as unknown as PathfindingGraph;
}

/** Built once per graph, reused across searches within a session. */
export function buildArtistIndex(graph: PathfindingGraph): Map<number, number> {
  const index = new Map<number, number>();
  graph.node_ids.forEach((artistId, i) => index.set(artistId, i));
  return index;
}

/** Built once per v2 graph, reused across searches within a session --
 * `album_id -> virtual_artist_id`, mirroring `buildArtistIndex`'s shape.
 * Empty for a v1 graph (no `album_virtual_nodes`). */
export function buildAlbumIndex(graph: PathfindingGraph): Map<string, number> {
  const index = new Map<string, number>();
  for (const entry of graph.album_virtual_nodes ?? []) {
    index.set(entry.album_id, entry.virtual_artist_id);
  }
  return index;
}

/** Bounded BFS over the CSR graph, mirroring `bfs_over_csr`'s exact
 * contract: an empty hop list for the same artist, a real hop list on
 * success, or a typed failure reason -- never a thrown exception for an
 * ordinary "no path" outcome. */
export function findPath(
  graph: PathfindingGraph,
  artistIndex: Map<number, number>,
  fromArtistId: number,
  toArtistId: number,
  maxHops = 4,
  edgeFilter?: (roleA: string, roleB: string) => boolean,
): PathfindingResult {
  const start = artistIndex.get(fromArtistId);
  const goal = artistIndex.get(toArtistId);
  if (start === undefined || goal === undefined) {
    return { ok: false, reason: "unknown-album" };
  }
  if (start === goal) return { ok: true, hops: [] };

  const parentOf = new Map<number, { parent: number; slot: number }>();
  const visited = new Set<number>([start]);
  let frontier = [start];

  for (let hop = 0; hop < maxHops; hop++) {
    const next: number[] = [];
    for (const node of frontier) {
      const begin = graph.offsets[node];
      const end = graph.offsets[node + 1];
      for (let slot = begin; slot < end; slot++) {
        const neighbor = graph.neighbors[slot];
        if (visited.has(neighbor)) continue;
        if (
          edgeFilter &&
          !edgeFilter(graph.edge_role_a[slot], graph.edge_role_b[slot])
        ) {
          continue;
        }
        visited.add(neighbor);
        parentOf.set(neighbor, { parent: node, slot });
        if (neighbor === goal) {
          return {
            ok: true,
            hops: reconstructPath(graph, parentOf, start, goal),
          };
        }
        next.push(neighbor);
      }
    }
    frontier = next;
    if (frontier.length === 0) break;
  }
  return { ok: false, reason: "no-path" };
}

function reconstructPath(
  graph: PathfindingGraph,
  parentOf: Map<number, { parent: number; slot: number }>,
  start: number,
  goal: number,
): PathHop[] {
  const hops: PathHop[] = [];
  let node = goal;
  while (node !== start) {
    const step = parentOf.get(node);
    if (!step) break;
    const { parent, slot } = step;
    hops.push({
      release_id: graph.evidence_release_ids[slot],
      artist_a_id: graph.node_ids[parent],
      artist_b_id: graph.node_ids[node],
      role_a: graph.edge_role_a[slot],
      role_b: graph.edge_role_b[slot],
    });
    node = parent;
  }
  hops.reverse();
  return hops;
}

export interface AlbumEndpoint {
  artistId: number;
  roleText: string;
}

export type AlbumRouteResult =
  | {
      ok: true;
      endpointA: AlbumEndpoint;
      hops: PathHop[];
      endpointB: AlbumEndpoint;
    }
  | { ok: false; reason: PathfindingFailureReason };

/** Removes the leading/trailing album-anchor hop from a raw `findPath`
 * result between two virtual album nodes, returning each side's real
 * endpoint contributor + role and the middle hops only. `null` for
 * anything shorter than 2 hops -- the minimum possible distance between
 * two distinct virtual nodes (album -> shared real contributor -> album),
 * since virtual nodes are never directly connected to each other; a
 * shorter result would indicate a structural inconsistency, not a real
 * route. */
export function stripAlbumAnchors(hops: PathHop[]): {
  endpointA: AlbumEndpoint;
  hops: PathHop[];
  endpointB: AlbumEndpoint;
} | null {
  if (hops.length < 2) return null;
  const first = hops[0];
  const last = hops[hops.length - 1];
  return {
    endpointA: { artistId: first.artist_b_id, roleText: first.role_b },
    hops: hops.slice(1, hops.length - 1),
    endpointB: { artistId: last.artist_a_id, roleText: last.role_a },
  };
}

/** Record-to-record search (ADR 0058): finds a route between two albums'
 * virtual anchor nodes, then strips the anchor hops so the result reads
 * as "a person credited on Album A ... a person credited on Album B,"
 * never exposing the synthetic anchors or `ALBUM_ANCHOR_SENTINEL` to a
 * caller. `maxHops` is the real, user-facing hop budget between people
 * (defaults to 4, matching the pre-v2 artist-to-artist search); the
 * anchor edges get `ALBUM_ANCHOR_HOP_BUDGET` extra hops of BFS budget on
 * top of that, invisibly. Requires a v2 graph (`albumIndex` built via
 * `buildAlbumIndex`) -- an album id absent from it (a v1 graph, or an
 * album with no virtual node) is `unknown-album`. */
export function findAlbumRoute(
  graph: PathfindingGraph,
  artistIndex: Map<number, number>,
  albumIndex: Map<string, number>,
  fromAlbumId: string,
  toAlbumId: string,
  maxHops = 4,
  edgeFilter?: (roleA: string, roleB: string) => boolean,
): AlbumRouteResult {
  const fromVirtualId = albumIndex.get(fromAlbumId);
  const toVirtualId = albumIndex.get(toAlbumId);
  if (fromVirtualId === undefined || toVirtualId === undefined) {
    return { ok: false, reason: "unknown-album" };
  }

  const result = findPath(
    graph,
    artistIndex,
    fromVirtualId,
    toVirtualId,
    maxHops + ALBUM_ANCHOR_HOP_BUDGET,
    edgeFilter,
  );
  if (!result.ok) return result;

  const stripped = stripAlbumAnchors(result.hops);
  if (!stripped) return { ok: false, reason: "no-path" };
  return { ok: true, ...stripped };
}

export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

const DEFAULT_GRAPH_URL = "/data/pathfinding/graph.v1.json";

/** Fetches and validates the pathfinding graph, caching it in
 * `sessionStorage` (not `localStorage` -- large and disposable, unlike the
 * persistent `np.game.v1` progression store) so repeated searches within one
 * session don't re-fetch/re-parse a multi-MB artifact (real measured size
 * as of ADR 0058's role-text join fix -- see data/contracts/
 * pathfinding-graph-v1.md / pathfinding-graph-v2.md). A corrupt or
 * unreadable cache entry is discarded, never thrown -- storage failures
 * degrade to a fresh fetch, matching store.ts's "losing local state is
 * preferable to breaking play" philosophy.
 *
 * `url` defaults to the v1 artifact for existing callers; a caller that
 * wants the v2 (virtual album-anchor) graph passes the v2 path explicitly
 * -- the cache key is derived from `url` itself so a v1 fetch and a v2
 * fetch never collide in the same session's storage (a cached v1 blob
 * being handed back for a v2 request would silently omit
 * `album_virtual_nodes`, both shapes now pass `validatePathfindingGraph`). */
export async function loadPathfindingGraph(
  storage: StorageLike | null,
  url: string = DEFAULT_GRAPH_URL,
): Promise<{ graph: PathfindingGraph } | { error: PathfindingFailureReason }> {
  const cacheKey = `np.pathfinding-graph:${url}`;
  if (storage) {
    try {
      const cached = storage.getItem(cacheKey);
      if (cached) {
        const parsed = validatePathfindingGraph(JSON.parse(cached));
        if (parsed) return { graph: parsed };
      }
    } catch {
      // fall through to a fresh fetch
    }
  }

  let response: Response;
  try {
    response = await fetch(url);
  } catch {
    return { error: "fetch-failed" };
  }
  if (!response.ok) return { error: "fetch-failed" };

  let raw: unknown;
  try {
    raw = await response.json();
  } catch {
    return { error: "parse-failed" };
  }

  const graph = validatePathfindingGraph(raw);
  if (!graph) return { error: "invalid-graph" };

  if (storage) {
    try {
      storage.setItem(cacheKey, JSON.stringify(graph));
    } catch {
      // sessionStorage full/unavailable -- searches still work, just refetch each time
    }
  }
  return { graph };
}
