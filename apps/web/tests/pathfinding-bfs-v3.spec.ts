// Unit specs for the v3 pathfinding graph (ADR 0068: performer-gated
// traversal). v3 keeps v2's exact CSR/album_virtual_nodes shape -- only
// which edges exist changed, plus one new top-level `graph_policy_version`
// field -- so this file does NOT duplicate pathfinding-bfs-v2.spec.ts's BFS
// behavior coverage (findAlbumRoute, stripAlbumAnchors, buildAlbumIndex,
// ...): those operate on an already-validated PathfindingGraph object and
// don't care which schema version produced it. Only `validatePathfindingGraph`
// itself needed new coverage.
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

test("validatePathfindingGraph accepts the shared well-formed v3 fixture", async () => {
  const result = await validatePathfindingGraph(loadFixture("well-formed-v3"));
  expect(result).not.toBeNull();
  expect(result?.schema_version).toBe(3);
  expect(result?.graph_policy_version).toBe(1);
});

test("validatePathfindingGraph rejects a non-positive graph_policy_version", async () => {
  const result = await validatePathfindingGraph(
    loadFixture("malformed-graph-policy-version-non-positive"),
  );
  expect(result).toBeNull();
});

test("validatePathfindingGraph rejects a v3 graph missing graph_policy_version", async () => {
  const graph = loadFixture("well-formed-v3") as Record<string, unknown>;
  const { graph_policy_version: _omit, ...withoutField } = graph;
  const result = await validatePathfindingGraph(withoutField);
  expect(result).toBeNull();
});

test("validatePathfindingGraph rejects a non-numeric graph_policy_version", async () => {
  const graph = loadFixture("well-formed-v3") as Record<string, unknown>;
  const result = await validatePathfindingGraph({
    ...graph,
    graph_policy_version: "1",
  });
  expect(result).toBeNull();
});

test("v2 and v3 fixtures both validate independently -- dual-live coexistence", async () => {
  const v2 = await validatePathfindingGraph(loadFixture("well-formed-v2"));
  const v3 = await validatePathfindingGraph(loadFixture("well-formed-v3"));
  expect(v2).not.toBeNull();
  expect(v3).not.toBeNull();
  expect(v2?.schema_version).toBe(2);
  expect(v3?.schema_version).toBe(3);
});

test("pathfinding_graph_version prefix distinguishes v3 from v2", async () => {
  const graph = loadFixture("well-formed-v3") as PathfindingGraph;
  expect(graph.pathfinding_graph_version).toMatch(/^pathfinding-graph-v3-/);
});
