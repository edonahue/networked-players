// Unit specs for the pathfinding graph's TS BFS port (ADR 0051) -- a small
// fixture graph, no browser or fetch needed. Mirrors
// test_compact_graph_bench.py's Python fixture cases (see that ADR's
// revisit trigger: there is no shared cross-language parity harness yet).
//
// Validator rejection cases load the shared, cross-language fixture set
// under data/fixtures/pathfinding-graph/ (each file generated with a real
// content-hashed `pathfinding_graph_version`, verified against the Python
// validator in packages/contracts/tests/test_pathfinding_graph_contracts.py)
// instead of hand-built inline objects, so a new malformed case added there
// is automatically exercised on both sides.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import {
  buildArtistIndex,
  findPath,
  validatePathfindingGraph,
  type PathfindingGraph,
} from "../src/game/pathfindingGraph";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "../../..");
const fixtureDir = join(repoRoot, "data/fixtures/pathfinding-graph");

function loadFixture(name: string): unknown {
  return JSON.parse(readFileSync(join(fixtureDir, `${name}.json`), "utf8"));
}

// A -1- B -2- C -3- D chain, matching the CSR shape build_csr_adjacency
// would produce for the same edges (both directions stored, sorted).
function chainGraph(): PathfindingGraph {
  return {
    schema_version: 1,
    catalog_version: "catalog-v1-test",
    snapshot_date: "20260601",
    generated_at: "2026-08-03T00:00:00+00:00",
    source: "test",
    license: "test",
    node_ids: [100, 200, 300, 400],
    names: ["Alice", "Bob", "Cara", "Dan"],
    // node 0 (100): neighbor 200 via release 1
    // node 1 (200): neighbors 100 (release 1), 300 (release 2)
    // node 2 (300): neighbors 200 (release 2), 400 (release 3)
    // node 3 (400): neighbor 300 (release 3)
    offsets: [0, 1, 3, 5, 6],
    neighbors: [1, 0, 2, 1, 3, 2],
    evidence_release_ids: [1, 1, 2, 2, 3, 3],
    edge_role_a: ["Guitar", "Bass", "Bass", "Cello", "Cello", "Drums"],
    edge_role_b: ["Bass", "Guitar", "Cello", "Bass", "Drums", "Cello"],
    pathfinding_graph_version: "pathfinding-graph-v1-20260601-test",
  };
}

test("finds the shortest path across multiple hops", () => {
  const graph = chainGraph();
  const index = buildArtistIndex(graph);
  const result = findPath(graph, index, 100, 400, 4);
  expect(result.ok).toBe(true);
  if (result.ok) {
    expect(result.hops).toHaveLength(3);
    expect(result.hops[0].artist_a_id).toBe(100);
    expect(result.hops[2].artist_b_id).toBe(400);
  }
});

test("confirms no path within a smaller hop budget", () => {
  const graph = chainGraph();
  const index = buildArtistIndex(graph);
  const result = findPath(graph, index, 100, 400, 2);
  expect(result).toEqual({ ok: false, reason: "no-path" });
});

test("same artist returns an empty path", () => {
  const graph = chainGraph();
  const index = buildArtistIndex(graph);
  const result = findPath(graph, index, 100, 100, 4);
  expect(result).toEqual({ ok: true, hops: [] });
});

test("an artist outside the graph is unknown-album, not a thrown error", () => {
  const graph = chainGraph();
  const index = buildArtistIndex(graph);
  const result = findPath(graph, index, 999999, 100, 4);
  expect(result).toEqual({ ok: false, reason: "unknown-album" });
});

test("reconstructed hops carry real role text and release ids", () => {
  const graph = chainGraph();
  const index = buildArtistIndex(graph);
  const result = findPath(graph, index, 100, 300, 4);
  expect(result.ok).toBe(true);
  if (result.ok) {
    expect(result.hops).toEqual([
      {
        release_id: 1,
        artist_a_id: 100,
        artist_b_id: 200,
        role_a: "Guitar",
        role_b: "Bass",
      },
      {
        release_id: 2,
        artist_a_id: 200,
        artist_b_id: 300,
        role_a: "Bass",
        role_b: "Cello",
      },
    ]);
  }
});

test("validatePathfindingGraph accepts a well-formed v1 graph", async () => {
  const graph = await validatePathfindingGraph(loadFixture("well-formed-v1"));
  expect(graph).not.toBeNull();
});

test("validatePathfindingGraph rejects mismatched parallel array lengths", async () => {
  const broken = { ...chainGraph(), edge_role_a: ["only one"] };
  expect(await validatePathfindingGraph(broken)).toBeNull();
});

test("validatePathfindingGraph rejects an out-of-range neighbor index", async () => {
  const broken = { ...chainGraph(), neighbors: [1, 0, 2, 1, 3, 99] };
  expect(await validatePathfindingGraph(broken)).toBeNull();
});

test("validatePathfindingGraph rejects a non-object", async () => {
  expect(await validatePathfindingGraph(null)).toBeNull();
  expect(await validatePathfindingGraph("not a graph")).toBeNull();
});

test("validatePathfindingGraph rejects non-monotonic offsets", async () => {
  const broken = loadFixture("malformed-non-monotonic-offsets");
  expect(await validatePathfindingGraph(broken)).toBeNull();
});

test("validatePathfindingGraph rejects unsorted node_ids", async () => {
  const broken = loadFixture("malformed-unsorted-node-ids");
  expect(await validatePathfindingGraph(broken)).toBeNull();
});

test("validatePathfindingGraph rejects duplicate node_ids", async () => {
  const broken = loadFixture("malformed-duplicate-node-ids");
  expect(await validatePathfindingGraph(broken)).toBeNull();
});

test("validatePathfindingGraph rejects a tampered pathfinding_graph_version hash", async () => {
  const broken = loadFixture("malformed-tampered-hash");
  expect(await validatePathfindingGraph(broken)).toBeNull();
});
