// Unit specs for the v2 pathfinding graph's virtual album-anchor nodes
// (ADR 0058) -- record-to-record search via `findAlbumRoute`. A small
// fixture graph, no browser or fetch needed, mirroring
// pathfinding-bfs.spec.ts's own hand-built-CSR pattern.
//
// Validator rejection cases load the shared, cross-language fixture set
// under data/fixtures/pathfinding-graph/ -- see pathfinding-bfs.spec.ts's
// header comment.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import {
  ALBUM_ANCHOR_SENTINEL,
  buildAlbumIndex,
  buildArtistIndex,
  findAlbumRoute,
  reverseRoute,
  stripAlbumAnchors,
  validatePathfindingGraph,
  type PathfindingGraph,
} from "../src/game/pathfindingGraph";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "../../..");
const fixtureDir = join(repoRoot, "data/fixtures/pathfinding-graph");

function loadFixture(name: string): unknown {
  return JSON.parse(readFileSync(join(fixtureDir, `${name}.json`), "utf8"));
}

// Album A's anchor (-1) connects to Alice (100); Album B's anchor (-2)
// connects to Dan (400); a Bob/Cara chain bridges them (100-200-300-400,
// the same shape pathfinding-bfs.spec.ts's chainGraph uses). Album C's
// anchor (-3) has zero neighbors -- no in-scope credited contributor.
function albumAnchorGraph(): PathfindingGraph {
  return {
    schema_version: 2,
    catalog_version: "catalog-v1-test",
    snapshot_date: "20260601",
    generated_at: "2026-08-08T00:00:00+00:00",
    source: "test",
    license: "test",
    node_ids: [-3, -2, -1, 100, 200, 300, 400],
    names: [
      "Album C (album anchor)",
      "Album B (album anchor)",
      "Album A (album anchor)",
      "Alice",
      "Bob",
      "Cara",
      "Dan",
    ],
    offsets: [0, 0, 1, 2, 4, 6, 8, 10],
    neighbors: [6, 3, 2, 4, 3, 5, 4, 6, 1, 5],
    evidence_release_ids: [20, 10, 10, 1, 1, 2, 2, 3, 20, 3],
    edge_role_a: [
      ALBUM_ANCHOR_SENTINEL,
      ALBUM_ANCHOR_SENTINEL,
      "Producer",
      "Guitar",
      "Bass",
      "Bass",
      "Cello",
      "Cello",
      "Vocals",
      "Drums",
    ],
    edge_role_b: [
      "Vocals",
      "Producer",
      ALBUM_ANCHOR_SENTINEL,
      "Bass",
      "Guitar",
      "Cello",
      "Bass",
      "Drums",
      ALBUM_ANCHOR_SENTINEL,
      "Cello",
    ],
    pathfinding_graph_version: "pathfinding-graph-v2-20260601-test",
    album_virtual_nodes: [
      { album_id: "album-a", virtual_artist_id: -1, main_release_id: 10 },
      { album_id: "album-b", virtual_artist_id: -2, main_release_id: 20 },
      { album_id: "album-c", virtual_artist_id: -3, main_release_id: 30 },
    ],
  };
}

test("validatePathfindingGraph accepts the shared well-formed v2 fixture", async () => {
  const graph = await validatePathfindingGraph(loadFixture("well-formed-v2"));
  expect(graph).not.toBeNull();
});

test("validatePathfindingGraph rejects a positive virtual_artist_id", async () => {
  const graph = albumAnchorGraph();
  const broken = {
    ...graph,
    album_virtual_nodes: [
      { ...graph.album_virtual_nodes![0], virtual_artist_id: 1 },
      graph.album_virtual_nodes![1],
      graph.album_virtual_nodes![2],
    ],
  };
  expect(await validatePathfindingGraph(broken)).toBeNull();
});

test("validatePathfindingGraph rejects a virtual id absent from node_ids", async () => {
  const graph = albumAnchorGraph();
  const broken = {
    ...graph,
    album_virtual_nodes: [
      { ...graph.album_virtual_nodes![0], virtual_artist_id: -99 },
      graph.album_virtual_nodes![1],
      graph.album_virtual_nodes![2],
    ],
  };
  expect(await validatePathfindingGraph(broken)).toBeNull();
});

test("validatePathfindingGraph rejects an unexpected top-level key set (v2 missing album_virtual_nodes)", async () => {
  const broken = loadFixture("malformed-wrong-top-level-keys");
  expect(await validatePathfindingGraph(broken)).toBeNull();
});

test("validatePathfindingGraph rejects a misplaced album-anchor sentinel", async () => {
  const broken = loadFixture("malformed-misplaced-sentinel");
  expect(await validatePathfindingGraph(broken)).toBeNull();
});

// Parity-hardening follow-up (post-#109 correctness closeout): each of
// these fixtures isolates one gap the parity investigation found between
// this validator and pathfinding_graph_failures -- shared with
// test_pathfinding_graph_contracts.py's own tests for the same files.

test("validatePathfindingGraph rejects empty required metadata", async () => {
  const broken = loadFixture("malformed-empty-metadata");
  expect(await validatePathfindingGraph(broken)).toBeNull();
});

test("validatePathfindingGraph rejects a virtual node missing a required key", async () => {
  const broken = loadFixture("malformed-virtual-node-missing-key");
  expect(await validatePathfindingGraph(broken)).toBeNull();
});

test("validatePathfindingGraph rejects a virtual node with an extra key", async () => {
  const broken = loadFixture("malformed-virtual-node-extra-key");
  expect(await validatePathfindingGraph(broken)).toBeNull();
});

test("validatePathfindingGraph rejects a fractional offset", async () => {
  const broken = loadFixture("malformed-fractional-offset");
  expect(await validatePathfindingGraph(broken)).toBeNull();
});

test("validatePathfindingGraph rejects a fractional neighbor index", async () => {
  const broken = loadFixture("malformed-fractional-neighbor");
  expect(await validatePathfindingGraph(broken)).toBeNull();
});

test("validatePathfindingGraph rejects a fractional main_release_id", async () => {
  const broken = loadFixture("malformed-fractional-main-release-id");
  expect(await validatePathfindingGraph(broken)).toBeNull();
});

test("validatePathfindingGraph rejects a non-integer node_id", async () => {
  const broken = loadFixture("malformed-node-id-wrong-type");
  expect(await validatePathfindingGraph(broken)).toBeNull();
});

// TS-local totality tests: NaN/Infinity can't exist in a JSON fixture (JSON
// has no literal for either), so these are inline-built objects, never
// JSON.parse'd. A malformed-but-object-shaped payload must return null,
// never throw.
test("validatePathfindingGraph returns null, not a thrown error, for Infinity in offsets", async () => {
  const graph = albumAnchorGraph();
  const broken = { ...graph, offsets: [...graph.offsets] };
  broken.offsets[2] = Infinity;
  await expect(validatePathfindingGraph(broken)).resolves.toBeNull();
});

test("validatePathfindingGraph returns null, not a thrown error, for NaN in neighbors", async () => {
  const graph = albumAnchorGraph();
  const broken = { ...graph, neighbors: [...graph.neighbors] };
  broken.neighbors[0] = NaN;
  await expect(validatePathfindingGraph(broken)).resolves.toBeNull();
});

test("buildAlbumIndex maps album_id to virtual_artist_id", () => {
  const index = buildAlbumIndex(albumAnchorGraph());
  expect(index.get("album-a")).toBe(-1);
  expect(index.get("album-b")).toBe(-2);
  expect(index.get("album-c")).toBe(-3);
});

test("buildAlbumIndex is empty for a v1 graph with no album_virtual_nodes", () => {
  const { album_virtual_nodes: _drop, ...v1Graph } = albumAnchorGraph();
  const index = buildAlbumIndex(v1Graph as PathfindingGraph);
  expect(index.size).toBe(0);
});

test("findAlbumRoute finds a real multi-hop route and strips both anchor hops", () => {
  const graph = albumAnchorGraph();
  const artistIndex = buildArtistIndex(graph);
  const albumIndex = buildAlbumIndex(graph);
  const result = findAlbumRoute(
    graph,
    artistIndex,
    albumIndex,
    "album-a",
    "album-b",
    4,
  );
  expect(result.ok).toBe(true);
  if (!result.ok) return;
  expect(result.endpointA).toEqual({ artistId: 100, roleText: "Producer" });
  expect(result.endpointB).toEqual({ artistId: 400, roleText: "Vocals" });
  expect(result.hops).toHaveLength(3);
  expect(result.hops[0]).toEqual({
    release_id: 1,
    artist_a_id: 100,
    artist_b_id: 200,
    role_a: "Guitar",
    role_b: "Bass",
  });
  expect(result.hops[2].artist_b_id).toBe(400);
});

test("findAlbumRoute never surfaces the album-anchor sentinel", () => {
  const graph = albumAnchorGraph();
  const artistIndex = buildArtistIndex(graph);
  const albumIndex = buildAlbumIndex(graph);
  const result = findAlbumRoute(
    graph,
    artistIndex,
    albumIndex,
    "album-a",
    "album-b",
    4,
  );
  expect(result.ok).toBe(true);
  if (!result.ok) return;
  expect(result.endpointA.roleText).not.toBe(ALBUM_ANCHOR_SENTINEL);
  expect(result.endpointB.roleText).not.toBe(ALBUM_ANCHOR_SENTINEL);
  for (const hop of result.hops) {
    expect(hop.role_a).not.toBe(ALBUM_ANCHOR_SENTINEL);
    expect(hop.role_b).not.toBe(ALBUM_ANCHOR_SENTINEL);
  }
});

test("findAlbumRoute reports a confirmed no-path for an isolated album anchor", () => {
  const graph = albumAnchorGraph();
  const artistIndex = buildArtistIndex(graph);
  const albumIndex = buildAlbumIndex(graph);
  const result = findAlbumRoute(
    graph,
    artistIndex,
    albumIndex,
    "album-a",
    "album-c",
    4,
  );
  expect(result).toEqual({ ok: false, reason: "no-path" });
});

test("findAlbumRoute is unknown-album for an id absent from albumIndex", () => {
  const graph = albumAnchorGraph();
  const artistIndex = buildArtistIndex(graph);
  const albumIndex = buildAlbumIndex(graph);
  const result = findAlbumRoute(
    graph,
    artistIndex,
    albumIndex,
    "album-a",
    "album-nonexistent",
    4,
  );
  expect(result).toEqual({ ok: false, reason: "unknown-album" });
});

test("findAlbumRoute respects a smaller hop budget", () => {
  const graph = albumAnchorGraph();
  const artistIndex = buildArtistIndex(graph);
  const albumIndex = buildAlbumIndex(graph);
  // The real distance between album-a and album-b is 3 real hops (Alice ->
  // Bob -> Cara -> Dan); a budget of 1 real hop must fail even though the
  // anchor-hop allowance would otherwise be enough BFS depth.
  const result = findAlbumRoute(
    graph,
    artistIndex,
    albumIndex,
    "album-a",
    "album-b",
    1,
  );
  expect(result).toEqual({ ok: false, reason: "no-path" });
});

test("findAlbumRoute's usedEdgeKeys includes the anchor edges, not just the middle hops", () => {
  const graph = albumAnchorGraph();
  const artistIndex = buildArtistIndex(graph);
  const albumIndex = buildAlbumIndex(graph);
  const result = findAlbumRoute(
    graph,
    artistIndex,
    albumIndex,
    "album-a",
    "album-b",
    4,
  );
  expect(result.ok).toBe(true);
  if (!result.ok) return;
  // 5 raw hops walked (2 anchor + 3 middle), even though only 3 are
  // returned in `hops` -- the exclusion set must cover all of them so a
  // second search can't just re-walk the same anchor connection.
  expect(result.usedEdgeKeys.size).toBe(5);
});

test("excluding a route's own edges forces a genuinely distinct alternate, or an honest no-path", () => {
  const graph = albumAnchorGraph();
  const artistIndex = buildArtistIndex(graph);
  const albumIndex = buildAlbumIndex(graph);
  const first = findAlbumRoute(
    graph,
    artistIndex,
    albumIndex,
    "album-a",
    "album-b",
    4,
  );
  expect(first.ok).toBe(true);
  if (!first.ok) return;

  // This fixture has exactly one route between album-a and album-b --
  // excluding its own edges must therefore report an honest no-path, not
  // silently rediscover the same route.
  const second = findAlbumRoute(
    graph,
    artistIndex,
    albumIndex,
    "album-a",
    "album-b",
    4,
    undefined,
    first.usedEdgeKeys,
  );
  expect(second).toEqual({ ok: false, reason: "no-path" });
});

test("findAlbumRoute's edgeFilter is never applied to an anchor edge", () => {
  // Regression test for a real bug (ADR 0058 Slice 7): an anchor edge's
  // role is always ALBUM_ANCHOR_SENTINEL on the virtual side, which can
  // never match a real role-filter predicate. Applying the caller's
  // filter unwrapped to anchor edges made every role-filtered search fail
  // to leave the starting album's own anchor node, regardless of real
  // connectivity. This filter matches every real middle-hop role in the
  // fixture (Guitar/Bass/Cello/Drums) but never Producer, Vocals, or the
  // sentinel -- so a route can only be found here if the two anchor edges
  // (whose real-side roles are Producer and Vocals) are exempted from it.
  const graph = albumAnchorGraph();
  const artistIndex = buildArtistIndex(graph);
  const albumIndex = buildAlbumIndex(graph);
  const middleHopRoles = new Set(["Guitar", "Bass", "Cello", "Drums"]);
  const onlyMiddleHopRoles = (roleA: string, roleB: string): boolean =>
    middleHopRoles.has(roleA) && middleHopRoles.has(roleB);

  const result = findAlbumRoute(
    graph,
    artistIndex,
    albumIndex,
    "album-a",
    "album-b",
    4,
    onlyMiddleHopRoles,
  );
  expect(result.ok).toBe(true);
  if (!result.ok) return;
  expect(result.hops).toHaveLength(3);
  expect(result.endpointA.artistId).toBe(100);
  expect(result.endpointB.artistId).toBe(400);
});

test("stripAlbumAnchors returns null for fewer than 2 hops", () => {
  expect(stripAlbumAnchors([])).toBeNull();
  expect(
    stripAlbumAnchors([
      {
        release_id: 1,
        artist_a_id: -1,
        artist_b_id: 100,
        role_a: ALBUM_ANCHOR_SENTINEL,
        role_b: "Producer",
      },
    ]),
  ).toBeNull();
});

test("stripAlbumAnchors fails closed when the sentinel isn't where it's about to be stripped from", () => {
  // Defense-in-depth (post-Phase-4 audit F7): stripAlbumAnchors must not
  // trust hop position alone. Real callers only ever reach this with a
  // validatePathfindingGraph-checked graph, where this can't happen -- but
  // the BFS layer itself should still fail closed, not silently strip the
  // wrong hop, if that upstream guarantee is ever violated. Each case below
  // isolates exactly one missing sentinel -- the other end is genuinely
  // valid, so a check that fired for the wrong reason would still be caught.
  const realMiddleHop = {
    release_id: 2,
    artist_a_id: 100,
    artist_b_id: 200,
    role_a: "Guitar",
    role_b: "Bass",
  };
  const validLeadingAnchor = {
    release_id: 1,
    artist_a_id: -1,
    artist_b_id: 100,
    role_a: ALBUM_ANCHOR_SENTINEL,
    role_b: "Producer",
  };
  const missingLeadingSentinel = {
    ...validLeadingAnchor,
    role_a: "Not the sentinel",
  };
  const validTrailingAnchor = {
    release_id: 3,
    artist_a_id: 200,
    artist_b_id: -2,
    role_a: "Bass",
    role_b: ALBUM_ANCHOR_SENTINEL,
  };
  const missingTrailingSentinel = {
    ...validTrailingAnchor,
    role_b: "Not the sentinel",
  };
  expect(
    stripAlbumAnchors([
      missingLeadingSentinel,
      realMiddleHop,
      validTrailingAnchor,
    ]),
  ).toBeNull();
  expect(
    stripAlbumAnchors([
      validLeadingAnchor,
      realMiddleHop,
      missingTrailingSentinel,
    ]),
  ).toBeNull();
  expect(
    stripAlbumAnchors([validLeadingAnchor, realMiddleHop, validTrailingAnchor]),
  ).not.toBeNull();
});

// reverseRoute (ADR 0059 Phase 5 PR 4: Swap Records reuses an already-found
// route instead of re-searching).
test("reverseRoute swaps endpoints and reverses hop order/direction", () => {
  const graph = albumAnchorGraph();
  const artistIndex = buildArtistIndex(graph);
  const albumIndex = buildAlbumIndex(graph);
  const route = findAlbumRoute(
    graph,
    artistIndex,
    albumIndex,
    "album-a",
    "album-b",
  );
  if (!route.ok) throw new Error("expected a real route in this fixture");

  const reversed = reverseRoute(route);
  expect(reversed.endpointA).toEqual(route.endpointB);
  expect(reversed.endpointB).toEqual(route.endpointA);
  expect(reversed.hops.length).toBe(route.hops.length);
  expect([...reversed.hops].reverse()).toEqual(
    route.hops.map((hop) => ({
      release_id: hop.release_id,
      artist_a_id: hop.artist_b_id,
      artist_b_id: hop.artist_a_id,
      role_a: hop.role_b,
      role_b: hop.role_a,
    })),
  );
});

test("reverseRoute produces a chain that reads correctly end to end", () => {
  const graph = albumAnchorGraph();
  const artistIndex = buildArtistIndex(graph);
  const albumIndex = buildAlbumIndex(graph);
  const route = findAlbumRoute(
    graph,
    artistIndex,
    albumIndex,
    "album-a",
    "album-b",
  );
  if (!route.ok) throw new Error("expected a real route in this fixture");
  const reversed = reverseRoute(route);

  // First hop starts from the new endpointA; last hop ends at the new
  // endpointB -- exactly what renderRoute/renderEvidenceHop assume.
  expect(reversed.hops[0].artist_a_id).toBe(reversed.endpointA.artistId);
  expect(reversed.hops[reversed.hops.length - 1].artist_b_id).toBe(
    reversed.endpointB.artistId,
  );
});

test("reverseRoute is its own inverse", () => {
  const graph = albumAnchorGraph();
  const artistIndex = buildArtistIndex(graph);
  const albumIndex = buildAlbumIndex(graph);
  const route = findAlbumRoute(
    graph,
    artistIndex,
    albumIndex,
    "album-a",
    "album-b",
  );
  if (!route.ok) throw new Error("expected a real route in this fixture");
  expect(reverseRoute(reverseRoute(route))).toEqual(route);
});
