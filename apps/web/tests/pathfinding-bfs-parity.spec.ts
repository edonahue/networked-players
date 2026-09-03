// Cross-language BFS parity (ADR 0051's named gap): pins real output from
// Python's compact_graph_bench.py (build_csr_adjacency + bfs_over_csr)
// against pathfindingGraph.ts's findPath, the same "manually-pinned golden
// value" pattern game-canonical.spec.ts already uses for canonical.py/
// canonical.ts parity -- not an automated cross-runner harness, just a
// one-time Python invocation whose real output is hardcoded here.
//
// The fixture graph below is deliberately byte-identical to
// pathfinding-bfs.spec.ts's chainGraph() (same node_ids/offsets/neighbors/
// evidence_release_ids) -- build_csr_adjacency's own docstring guarantees
// determinism from the same edge set, and TS's chainGraph was hand-built
// to match that same CSR shape, so this test's Python invocation below
// reproduces it exactly rather than inventing a second fixture.
//
// Reproduce with:
//   cd packages/graph-core && uv run python3 -c "
//   from networked_players_graph_core.compact_graph_bench import build_csr_adjacency, bfs_over_csr
//   edges = [(100, 200, 1), (200, 300, 2), (300, 400, 3)]
//   graph = build_csr_adjacency(edges)
//   print(bfs_over_csr(graph, 100, 400, max_hops=4))
//   print(bfs_over_csr(graph, 100, 400, max_hops=2))
//   print(bfs_over_csr(graph, 100, 100, max_hops=4))
//   "
//
// Covers: hop-list shape/values on a found path, and no-path/same-artist
// agreement. Does NOT cover: role text (edge_role_a/edge_role_b -- Python's
// bench module doesn't model roles at all), findPath's edgeFilter
// parameter, or FrontierTooLargeBench/"inconclusive" (Python signals via a
// raised exception, TS via a typed union member that no code path produces
// today -- see ADR 0051's revisit trigger).

import { expect, test } from "@playwright/test";
import {
  buildArtistIndex,
  findPath,
  type PathfindingGraph,
} from "../src/game/pathfindingGraph";

function chainGraph(): PathfindingGraph {
  return {
    schema_version: 1,
    catalog_version: "catalog-v1-test",
    snapshot_date: "20260601",
    generated_at: "2026-08-03T00:00:00+00:00",
    source: "test",
    license: "test",
    node_ids: new Int32Array([100, 200, 300, 400]),
    names: ["Alice", "Bob", "Cara", "Dan"],
    offsets: new Int32Array([0, 1, 3, 5, 6]),
    neighbors: new Int32Array([1, 0, 2, 1, 3, 2]),
    evidence_release_ids: new Int32Array([1, 1, 2, 2, 3, 3]),
    // Python's bench module carries no role text; placeholders here since
    // pathfindingGraph.ts's shape requires them but this parity test
    // doesn't assert on them.
    edge_role_a: ["n/a", "n/a", "n/a", "n/a", "n/a", "n/a"],
    edge_role_b: ["n/a", "n/a", "n/a", "n/a", "n/a", "n/a"],
    pathfinding_graph_version: "pathfinding-graph-v1-20260601-test",
  };
}

test("TS findPath matches Python bfs_over_csr's real output for a found path", () => {
  const graph = chainGraph();
  const index = buildArtistIndex(graph);
  const result = findPath(graph, index, 100, 400, 4);

  // Real Python output (pinned): bfs_over_csr(graph, 100, 400, max_hops=4) ==
  // [{'artist_a_id': 100, 'artist_b_id': 200, 'release_id': 1},
  //  {'artist_a_id': 200, 'artist_b_id': 300, 'release_id': 2},
  //  {'artist_a_id': 300, 'artist_b_id': 400, 'release_id': 3}]
  expect(result.ok).toBe(true);
  if (!result.ok) return;
  expect(
    result.hops.map(({ artist_a_id, artist_b_id, release_id }) => ({
      artist_a_id,
      artist_b_id,
      release_id,
    })),
  ).toEqual([
    { artist_a_id: 100, artist_b_id: 200, release_id: 1 },
    { artist_a_id: 200, artist_b_id: 300, release_id: 2 },
    { artist_a_id: 300, artist_b_id: 400, release_id: 3 },
  ]);
});

test("TS findPath agrees with Python's confirmed no-path within a smaller hop budget", () => {
  const graph = chainGraph();
  const index = buildArtistIndex(graph);
  const result = findPath(graph, index, 100, 400, 2);

  // Real Python output (pinned): bfs_over_csr(graph, 100, 400, max_hops=2) is None
  expect(result).toEqual({ ok: false, reason: "no-path" });
});

test("TS findPath agrees with Python's same-artist empty path", () => {
  const graph = chainGraph();
  const index = buildArtistIndex(graph);
  const result = findPath(graph, index, 100, 100, 4);

  // Real Python output (pinned): bfs_over_csr(graph, 100, 100, max_hops=4) == []
  expect(result).toEqual({ ok: true, hops: [] });
});
