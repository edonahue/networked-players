// Unit specs for the v4 pathfinding graph (graph-expansion Phase 1, ADR
// 0071: role-text dictionary encoding). v4 keeps v3's exact CSR/
// album_virtual_nodes/graph_policy_version shape -- only edge_role_a/
// edge_role_b's TYPE (index, not text) and the new `roles` dictionary are
// new -- so this file does NOT duplicate pathfinding-bfs-v3.spec.ts's BFS
// behavior coverage: `validatePathfindingGraph` decodes the dictionary
// back into plain strings before returning (see pathfindingGraph.ts's
// header comment), so every consumer downstream of it, and every existing
// BFS test, is already covered. Only the validator itself needed new
// coverage.
//
// Validator rejection cases load the shared, cross-language fixture set
// under data/fixtures/pathfinding-graph/ -- see pathfinding-bfs.spec.ts's
// header comment.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import {
  validatePathfindingGraph,
  type PathfindingGraph,
} from "../src/game/pathfindingGraph";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "../../..");
const fixtureDir = join(repoRoot, "data/fixtures/pathfinding-graph");

function loadFixture(name: string): unknown {
  return JSON.parse(readFileSync(join(fixtureDir, `${name}.json`), "utf8"));
}

test("validatePathfindingGraph accepts the shared well-formed v4 fixture", async () => {
  const result = await validatePathfindingGraph(loadFixture("well-formed-v4"));
  expect(result).not.toBeNull();
  expect(result?.schema_version).toBe(4);
  expect(result?.graph_policy_version).toBe(1);
});

test("validatePathfindingGraph decodes v4's role dictionary back into plain strings", async () => {
  const result = await validatePathfindingGraph(loadFixture("well-formed-v4"));
  expect(result).not.toBeNull();
  // The fixture's raw wire form has edge_role_a/edge_role_b as indices
  // ([0, 0, 1, 1, 2, 2] / [2, 1, 0, 2, 0, 1]) into roles ["__np_album_anchor__",
  // "Guitar", "Bass"] -- the decoded object must expose the same text a v3
  // fixture with equivalent content would, never the raw indices.
  expect(result?.edge_role_a).toEqual([
    "__np_album_anchor__",
    "__np_album_anchor__",
    "Guitar",
    "Guitar",
    "Bass",
    "Bass",
  ]);
  expect(result?.edge_role_b).toEqual([
    "Bass",
    "Guitar",
    "__np_album_anchor__",
    "Bass",
    "__np_album_anchor__",
    "Guitar",
  ]);
  // `roles` is a wire-format detail, never exposed on the decoded object.
  expect((result as unknown as Record<string, unknown>).roles).toBeUndefined();
});

test("validatePathfindingGraph rejects a v4 graph missing the roles key", async () => {
  const graph = loadFixture("well-formed-v4") as Record<string, unknown>;
  const { roles: _omit, ...withoutField } = graph;
  const result = await validatePathfindingGraph(withoutField);
  expect(result).toBeNull();
});

test("validatePathfindingGraph rejects a v4 graph whose edge_role_a is text, not an index", async () => {
  // The whole point of v4: a v3 payload accidentally stamped schema_version:
  // 4 must fail, not silently validate.
  const v3 = loadFixture("well-formed-v3") as Record<string, unknown>;
  const result = await validatePathfindingGraph({
    ...v3,
    schema_version: 4,
    roles: ["__np_album_anchor__", "Guitar", "Bass"],
  });
  expect(result).toBeNull();
});

test("validatePathfindingGraph rejects an out-of-range role index", async () => {
  const graph = loadFixture("well-formed-v4") as {
    edge_role_a: number[];
    roles: string[];
    [key: string]: unknown;
  };
  const result = await validatePathfindingGraph({
    ...graph,
    edge_role_a: [graph.roles.length, ...graph.edge_role_a.slice(1)],
  });
  expect(result).toBeNull();
});

test("validatePathfindingGraph rejects a negative role index", async () => {
  const graph = loadFixture("well-formed-v4") as {
    edge_role_a: number[];
    [key: string]: unknown;
  };
  const result = await validatePathfindingGraph({
    ...graph,
    edge_role_a: [-1, ...graph.edge_role_a.slice(1)],
  });
  expect(result).toBeNull();
});

test("v3 and v4 fixtures both validate independently -- dual-live coexistence", async () => {
  const v3 = await validatePathfindingGraph(loadFixture("well-formed-v3"));
  const v4 = await validatePathfindingGraph(loadFixture("well-formed-v4"));
  expect(v3).not.toBeNull();
  expect(v4).not.toBeNull();
  expect(v3?.schema_version).toBe(3);
  expect(v4?.schema_version).toBe(4);
});

test("pathfinding_graph_version prefix distinguishes v4 from v3", async () => {
  const graph = loadFixture("well-formed-v4") as PathfindingGraph;
  expect(graph.pathfinding_graph_version).toMatch(/^pathfinding-graph-v4-/);
});
