// Cross-language BFS parity for the v2 virtual-album-anchor code path
// (ADR 0058), extending pathfinding-bfs-parity.spec.ts's existing
// manually-pinned-golden-value pattern -- not an automated dual-runner;
// this remains a real, one-time Python invocation whose output is
// hardcoded here, same as before. This slice does not close ADR 0051's
// named "no automated cross-language BFS parity harness" gap, only
// extends the existing pattern to cover the new virtual-node construction
// (`build_csr_adjacency`'s `extra_node_ids` parameter) and search
// (`bfs_over_csr` between two negative/virtual ids).
//
// The fixture graph below is deliberately byte-identical to
// pathfinding-bfs-v2.spec.ts's albumAnchorGraph() (same node_ids/offsets/
// neighbors/evidence_release_ids) -- confirmed against the real Python
// invocation below, not just asserted.
//
// Reproduce with:
//   cd packages/graph-core && uv run python3 -c "
//   from networked_players_graph_core.compact_graph_bench import build_csr_adjacency, bfs_over_csr
//   edges = [(100, 200, 1), (200, 300, 2), (300, 400, 3), (-1, 100, 10), (-2, 400, 20)]
//   graph = build_csr_adjacency(edges, extra_node_ids=[-3])
//   print('node_ids', graph.node_ids)
//   print('offsets', graph.offsets)
//   print('neighbors', graph.neighbors)
//   print('evidence_release_ids', graph.evidence_release_ids)
//   print('route a->b (maxhops=6):', bfs_over_csr(graph, -1, -2, max_hops=6))
//   print('route a->c (maxhops=6):', bfs_over_csr(graph, -1, -3, max_hops=6))
//   print('route a->b (maxhops=3):', bfs_over_csr(graph, -1, -2, max_hops=3))
//   "
//
// Covers: virtual-node CSR construction (node_ids/offsets/neighbors
// exactly matching Python's real output, including an isolated
// zero-degree virtual node), and a found vs. confirmed-no-path route
// between two virtual ids. Does NOT cover: role text (Python's bench
// module has no role model at all, same gap the v1 parity test already
// names), or findAlbumRoute's own anchor-stripping (that's TS-only logic
// with no Python analog -- covered instead by pathfinding-bfs-v2.spec.ts).

import { expect, test } from "@playwright/test";
import {
  ALBUM_ANCHOR_SENTINEL,
  buildArtistIndex,
  findPath,
  type PathfindingGraph,
} from "../src/game/pathfindingGraph";

function albumAnchorGraph(): PathfindingGraph {
  return {
    schema_version: 2,
    catalog_version: "catalog-v1-test",
    snapshot_date: "20260601",
    generated_at: "2026-08-08T00:00:00+00:00",
    source: "test",
    license: "test",
    node_ids: new Int32Array([-3, -2, -1, 100, 200, 300, 400]),
    names: [
      "Album C (album anchor)",
      "Album B (album anchor)",
      "Album A (album anchor)",
      "Alice",
      "Bob",
      "Cara",
      "Dan",
    ],
    offsets: new Int32Array([0, 0, 1, 2, 4, 6, 8, 10]),
    neighbors: new Int32Array([6, 3, 2, 4, 3, 5, 4, 6, 1, 5]),
    evidence_release_ids: new Int32Array([20, 10, 10, 1, 1, 2, 2, 3, 20, 3]),
    // Python's bench module carries no role text; placeholders here since
    // pathfindingGraph.ts's shape requires them but this parity test
    // doesn't assert on them (except confirming the sentinel is absent
    // from Python's own hop dicts, which don't carry roles at all).
    edge_role_a: [
      ALBUM_ANCHOR_SENTINEL,
      ALBUM_ANCHOR_SENTINEL,
      "n/a",
      "n/a",
      "n/a",
      "n/a",
      "n/a",
      "n/a",
      "n/a",
      "n/a",
    ],
    edge_role_b: [
      "n/a",
      "n/a",
      ALBUM_ANCHOR_SENTINEL,
      "n/a",
      "n/a",
      "n/a",
      "n/a",
      "n/a",
      ALBUM_ANCHOR_SENTINEL,
      "n/a",
    ],
    pathfinding_graph_version: "pathfinding-graph-v2-20260601-test",
    album_virtual_nodes: [
      { album_id: "album-a", virtual_artist_id: -1, main_release_id: 10 },
      { album_id: "album-b", virtual_artist_id: -2, main_release_id: 20 },
      { album_id: "album-c", virtual_artist_id: -3, main_release_id: 30 },
    ],
  };
}

test("TS findPath matches Python bfs_over_csr's real output between two virtual ids", () => {
  const graph = albumAnchorGraph();
  const index = buildArtistIndex(graph);
  const result = findPath(graph, index, -1, -2, 6);

  // Real Python output (pinned): bfs_over_csr(graph, -1, -2, max_hops=6) ==
  // [{'artist_a_id': -1, 'artist_b_id': 100, 'release_id': 10},
  //  {'artist_a_id': 100, 'artist_b_id': 200, 'release_id': 1},
  //  {'artist_a_id': 200, 'artist_b_id': 300, 'release_id': 2},
  //  {'artist_a_id': 300, 'artist_b_id': 400, 'release_id': 3},
  //  {'artist_a_id': 400, 'artist_b_id': -2, 'release_id': 20}]
  expect(result.ok).toBe(true);
  if (!result.ok) return;
  expect(
    result.hops.map(({ artist_a_id, artist_b_id, release_id }) => ({
      artist_a_id,
      artist_b_id,
      release_id,
    })),
  ).toEqual([
    { artist_a_id: -1, artist_b_id: 100, release_id: 10 },
    { artist_a_id: 100, artist_b_id: 200, release_id: 1 },
    { artist_a_id: 200, artist_b_id: 300, release_id: 2 },
    { artist_a_id: 300, artist_b_id: 400, release_id: 3 },
    { artist_a_id: 400, artist_b_id: -2, release_id: 20 },
  ]);
});

test("TS findPath agrees with Python's confirmed no-path to an isolated virtual node", () => {
  const graph = albumAnchorGraph();
  const index = buildArtistIndex(graph);
  const result = findPath(graph, index, -1, -3, 6);

  // Real Python output (pinned): bfs_over_csr(graph, -1, -3, max_hops=6) is None
  expect(result).toEqual({ ok: false, reason: "no-path" });
});

test("TS findPath agrees with Python's confirmed no-path within a smaller hop budget", () => {
  const graph = albumAnchorGraph();
  const index = buildArtistIndex(graph);
  const result = findPath(graph, index, -1, -2, 3);

  // Real Python output (pinned): bfs_over_csr(graph, -1, -2, max_hops=3) is None
  expect(result).toEqual({ ok: false, reason: "no-path" });
});
