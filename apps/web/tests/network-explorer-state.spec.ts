// Unit specs for the Network Explorer's pure state derivation (ADR 0052) --
// a small fixture graph, no browser needed.

import { expect, test } from "@playwright/test";
import { buildArtistIndex } from "../src/game/pathfindingGraph";
import type { PathfindingGraph } from "../src/game/pathfindingGraph";
import {
  MAX_NEIGHBORS,
  buildView,
  isDimmed,
} from "../src/game/networkExplorer";
import type { Contributor } from "../src/data/contributors";

// A star graph: center 100 connects to 200, 300, 400.
function starGraph(): PathfindingGraph {
  return {
    schema_version: 1,
    catalog_version: "catalog-v1-test",
    snapshot_date: "20260601",
    generated_at: "2026-08-03T00:00:00+00:00",
    source: "test",
    license: "test",
    node_ids: [100, 200, 300, 400],
    names: ["Alice", "Bob", "Cara", "Dan"],
    offsets: [0, 3, 4, 5, 6],
    neighbors: [1, 2, 3, 0, 0, 0],
    evidence_release_ids: [1, 2, 3, 1, 2, 3],
    edge_role_a: [
      "Producer",
      "Producer",
      "Producer",
      "Guitar",
      "Bass",
      "Drums",
    ],
    edge_role_b: [
      "Guitar",
      "Bass",
      "Drums",
      "Producer",
      "Producer",
      "Producer",
    ],
    pathfinding_graph_version: "pathfinding-graph-v1-20260601-test",
  };
}

function contributor(
  overrides: Partial<Contributor> & { artist_id: number },
): Contributor {
  return {
    name: `Artist ${overrides.artist_id}`,
    role_categories: ["engineering"],
    role_text_examples: [],
    albums: [],
    decade_activity: [],
    connection_count: 1,
    neighboring_contributor_ids: [],
    evidence: [],
    ...overrides,
  };
}

test("buildView centers on the requested artist and includes its neighbors", () => {
  const graph = starGraph();
  const index = buildArtistIndex(graph);
  const view = buildView(graph, index, new Map(), 100);
  expect(view).not.toBeNull();
  expect(view?.center.artistId).toBe(100);
  expect(view?.center.isCenter).toBe(true);
  expect(view?.neighbors.map((n) => n.artistId).sort()).toEqual([
    200, 300, 400,
  ]);
  expect(view?.truncated).toBe(false);
});

test("buildView returns null for an artist outside the graph", () => {
  const graph = starGraph();
  const index = buildArtistIndex(graph);
  expect(buildView(graph, index, new Map(), 999999)).toBeNull();
});

test("buildView ranks neighbors by degree and truncates beyond the cap", () => {
  // Reuse the star graph but request a cap of 2 -- the higher-degree
  // neighbors (by connection_count) should be kept.
  const graph = starGraph();
  const index = buildArtistIndex(graph);
  const byId = new Map<number, Contributor>([
    [200, contributor({ artist_id: 200, connection_count: 5 })],
    [300, contributor({ artist_id: 300, connection_count: 50 })],
    [400, contributor({ artist_id: 400, connection_count: 1 })],
  ]);
  const view = buildView(graph, index, byId, 100, 2);
  expect(view?.neighbors.map((n) => n.artistId)).toEqual([300, 200]);
  expect(view?.truncated).toBe(true);
});

test("MAX_NEIGHBORS is the default cap", () => {
  const graph = starGraph();
  const index = buildArtistIndex(graph);
  const view = buildView(graph, index, new Map(), 100);
  expect(view?.neighbors.length).toBeLessThanOrEqual(MAX_NEIGHBORS);
});

test("isDimmed never dims the center", () => {
  const center = {
    artistId: 100,
    name: "Alice",
    roleCategories: [],
    isCenter: true,
  };
  expect(isDimmed(center, new Set(["vocals"]))).toBe(false);
});

test("isDimmed leaves nodes undimmed when no filter is active", () => {
  const node = {
    artistId: 200,
    name: "Bob",
    roleCategories: ["engineering"],
    isCenter: false,
  };
  expect(isDimmed(node, new Set())).toBe(false);
});

test("isDimmed dims a neighbor whose categories don't match the active filter", () => {
  const node = {
    artistId: 200,
    name: "Bob",
    roleCategories: ["engineering"],
    isCenter: false,
  };
  expect(isDimmed(node, new Set(["vocals"]))).toBe(true);
});

test("isDimmed does not dim a neighbor matching the active filter", () => {
  const node = {
    artistId: 200,
    name: "Bob",
    roleCategories: ["vocals", "strings"],
    isCenter: false,
  };
  expect(isDimmed(node, new Set(["vocals"]))).toBe(false);
});
