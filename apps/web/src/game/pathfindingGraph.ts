// Runtime type + validation + BFS for the pathfinding graph artifact
// (apps/web/public/data/pathfinding/graph.v1.json, data/contracts/
// pathfinding-graph-v1.md, ADR 0050/0051). A TypeScript port of
// compact_graph_bench.py's build_csr_adjacency/bfs_over_csr -- see ADR
// 0051's revisit trigger: there is no shared cross-language parity test yet,
// so keep this file's BFS logic in careful lockstep with the Python
// reference by inspection until one exists.
//
// Nothing here trusts a TypeScript type assertion as runtime proof -- the
// fetched JSON is untrusted input, validated field-by-field before use,
// mirroring routesResolver.ts's hardened pattern.

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
}

export interface PathHop {
  release_id: number;
  artist_a_id: number;
  artist_b_id: number;
  role_a: string;
  role_b: string;
}

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
 * array lengths, neighbor indices in range. A malformed or truncated fetch
 * must be caught here, not partway through a BFS. */
export function validatePathfindingGraph(
  value: unknown,
): PathfindingGraph | null {
  if (!isRecord(value)) return null;
  if (value.schema_version !== 1) return null;
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
  return value as unknown as PathfindingGraph;
}

/** Built once per graph, reused across searches within a session. */
export function buildArtistIndex(graph: PathfindingGraph): Map<number, number> {
  const index = new Map<number, number>();
  graph.node_ids.forEach((artistId, i) => index.set(artistId, i));
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

export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

const SESSION_CACHE_KEY = "np.pathfinding-graph.v1";

/** Fetches and validates the pathfinding graph, caching it in
 * `sessionStorage` (not `localStorage` -- large and disposable, unlike the
 * persistent `np.game.v1` progression store) so repeated searches within one
 * session don't re-fetch/re-parse a ~1.8MB artifact. A corrupt or
 * unreadable cache entry is discarded, never thrown -- storage failures
 * degrade to a fresh fetch, matching store.ts's "losing local state is
 * preferable to breaking play" philosophy. */
export async function loadPathfindingGraph(
  storage: StorageLike | null,
): Promise<{ graph: PathfindingGraph } | { error: PathfindingFailureReason }> {
  if (storage) {
    try {
      const cached = storage.getItem(SESSION_CACHE_KEY);
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
    response = await fetch("/data/pathfinding/graph.v1.json");
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
      storage.setItem(SESSION_CACHE_KEY, JSON.stringify(graph));
    } catch {
      // sessionStorage full/unavailable -- searches still work, just refetch each time
    }
  }
  return { graph };
}
