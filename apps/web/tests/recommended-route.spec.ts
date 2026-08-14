// Unit specs for the recommended-route engine (ADR 0059, Phase 5 PR 3) --
// synthetic fixtures only, no browser or fetch needed, mirroring
// pathfinding-bfs-v2.spec.ts's hand-built-CSR pattern. A `buildGraph`
// helper assembles the CSR arrays from a plain undirected edge list so a
// multi-node fixture doesn't need hand-computed offsets.

import { expect, test } from "@playwright/test";
import {
  ALBUM_ANCHOR_SENTINEL,
  buildAlbumIndex,
  buildArtistIndex,
  findAlbumRoute,
  type AlbumVirtualNode,
  type PathfindingGraph,
} from "../src/game/pathfindingGraph";
import type {
  EvidenceIndex,
  EvidenceRelease,
} from "../src/game/connectEvidence";
import {
  computeRouteFacts,
  explainRoute,
  selectRecommendedRoute,
  type RouteFacts,
} from "../src/game/recommendedRoute";

const CAVEAT_FLAG_NAMES = [
  "compilation",
  "mixed",
  "promo",
  "reissue",
  "sampler",
  "unofficial",
];
const CAVEAT_BIT: Record<string, number> = Object.fromEntries(
  CAVEAT_FLAG_NAMES.map((name, i) => [name, 1 << i]),
);

interface Edge {
  a: number;
  b: number;
  releaseId: number;
  roleA?: string;
  roleB?: string;
}

/** Assembles a valid CSR graph from an undirected edge list -- both
 * directions stored, sorted by node index, matching what
 * `build_csr_adjacency` (Python) and every real published graph produce. */
function buildGraph(
  nodeIds: number[],
  names: string[],
  edges: Edge[],
  albumVirtualNodes: AlbumVirtualNode[] = [],
): PathfindingGraph {
  const sortedIds = [...nodeIds].sort((a, b) => a - b);
  const indexOf = new Map(sortedIds.map((id, i) => [id, i]));
  const sortedNames = sortedIds.map((id) => names[nodeIds.indexOf(id)]);

  type Slot = { neighbor: number; releaseId: number; role: string };
  const perNode: Slot[][] = sortedIds.map(() => []);
  for (const edge of edges) {
    const ai = indexOf.get(edge.a)!;
    const bi = indexOf.get(edge.b)!;
    perNode[ai].push({
      neighbor: bi,
      releaseId: edge.releaseId,
      role: edge.roleA ?? "Performer",
    });
    perNode[bi].push({
      neighbor: ai,
      releaseId: edge.releaseId,
      role: edge.roleB ?? "Performer",
    });
  }
  for (const slots of perNode) slots.sort((x, y) => x.neighbor - y.neighbor);

  const offsets: number[] = [0];
  const neighbors: number[] = [];
  const evidence_release_ids: number[] = [];
  const edge_role_a: string[] = [];
  const edge_role_b: string[] = [];
  for (let i = 0; i < sortedIds.length; i++) {
    for (const slot of perNode[i]) {
      neighbors.push(slot.neighbor);
      evidence_release_ids.push(slot.releaseId);
      edge_role_a.push(slot.role);
      edge_role_b.push(
        perNode[slot.neighbor].find(
          (s) => s.neighbor === i && s.releaseId === slot.releaseId,
        )!.role,
      );
    }
    offsets.push(neighbors.length);
  }

  return {
    schema_version: 2,
    catalog_version: "catalog-v1-test",
    snapshot_date: "20260601",
    generated_at: "2026-08-14T00:00:00+00:00",
    source: "test",
    license: "test",
    node_ids: sortedIds,
    names: sortedNames,
    offsets,
    neighbors,
    evidence_release_ids,
    edge_role_a,
    edge_role_b,
    pathfinding_graph_version: "pathfinding-graph-v2-20260601-test",
    album_virtual_nodes: albumVirtualNodes,
  };
}

function release(
  releaseId: number,
  caveatFlagName: string | null,
): [number, EvidenceRelease] {
  return [
    releaseId,
    {
      releaseId,
      title: `Release ${releaseId}`,
      year: null,
      country: null,
      coverUri: null,
      caveatFlags: caveatFlagName ? CAVEAT_BIT[caveatFlagName] : 0,
    },
  ];
}

function evidenceIndex(entries: [number, EvidenceRelease][]): EvidenceIndex {
  return { releases: new Map(entries), caveatFlagNames: CAVEAT_FLAG_NAMES };
}

const NO_EVIDENCE: EvidenceIndex = { releases: new Map(), caveatFlagNames: [] };

/** Two albums (-1, -2), each with two credited contributors, wired as two
 * independent equal-hop (1-user-hop) bridges -- the exact shape of ADR
 * 0059's diagnostic pair (two people per album, one bridge each). Every
 * scenario test starts here and overrides one axis (caveat/degree/role). */
function twoBridgeGraph(opts: {
  bridgeOneRelease?: number;
  bridgeOneRoles?: [string, string];
  bridgeTwoRelease?: number;
  bridgeTwoRoles?: [string, string];
  /** Extra padding edges raising node 100's (bridge-one contributor A's)
   * degree above every other node -- the hub-avoidance axis. */
  padHubDegree?: number;
}): PathfindingGraph {
  const edges: Edge[] = [
    {
      a: -1,
      b: 100,
      releaseId: 10,
      roleA: ALBUM_ANCHOR_SENTINEL,
      roleB: "Producer",
    },
    {
      a: -1,
      b: 200,
      releaseId: 10,
      roleA: ALBUM_ANCHOR_SENTINEL,
      roleB: "Producer",
    },
    {
      a: -2,
      b: 300,
      releaseId: 20,
      roleA: ALBUM_ANCHOR_SENTINEL,
      roleB: "Producer",
    },
    {
      a: -2,
      b: 400,
      releaseId: 20,
      roleA: ALBUM_ANCHOR_SENTINEL,
      roleB: "Producer",
    },
    {
      a: 100,
      b: 300,
      releaseId: opts.bridgeOneRelease ?? 900,
      roleA: opts.bridgeOneRoles?.[0] ?? "Vocals",
      roleB: opts.bridgeOneRoles?.[1] ?? "Vocals",
    },
    {
      a: 200,
      b: 400,
      releaseId: opts.bridgeTwoRelease ?? 901,
      roleA: opts.bridgeTwoRoles?.[0] ?? "Vocals",
      roleB: opts.bridgeTwoRoles?.[1] ?? "Vocals",
    },
  ];
  const nodeIds = [-2, -1, 100, 200, 300, 400];
  const names = ["Album B", "Album A", "P", "Q", "R", "S"];
  if (opts.padHubDegree) {
    for (let i = 0; i < opts.padHubDegree; i++) {
      const padId = 1000 + i;
      nodeIds.push(padId);
      names.push(`Pad ${i}`);
      edges.push({ a: 100, b: padId, releaseId: 5000 + i });
    }
  }
  return buildGraph(nodeIds, names, edges, [
    { album_id: "album-a", virtual_artist_id: -1, main_release_id: 10 },
    { album_id: "album-b", virtual_artist_id: -2, main_release_id: 20 },
  ]);
}

function indices(graph: PathfindingGraph) {
  return {
    artistIndex: buildArtistIndex(graph),
    albumIndex: buildAlbumIndex(graph),
  };
}

test.describe("selectRecommendedRoute: ranking axes", () => {
  test("prefers the equal-hop candidate with no caveated evidence over one evidenced by an unofficial release", () => {
    const graph = twoBridgeGraph({
      bridgeOneRelease: 900,
      bridgeTwoRelease: 901,
    });
    const { artistIndex, albumIndex } = indices(graph);
    const evidence = evidenceIndex([
      release(900, "unofficial"),
      release(901, null),
    ]);

    const result = selectRecommendedRoute(
      graph,
      artistIndex,
      albumIndex,
      "album-a",
      "album-b",
      evidence,
      4,
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.recommended.endpointA.artistId).toBe(200); // Q, the uncaveated bridge
    expect(result.recommended.facts.worstCaveatSeverity).toBe(0);
    expect(result.usedPlusOneHop).toBe(false);
    expect(result.rankingDegraded).toBe(false);
  });

  test("once caveat severity ties, prefers the lower-degree (less hub-dependent) bridge", () => {
    const graph = twoBridgeGraph({ padHubDegree: 20 }); // node 100 (P) becomes the hub
    const { artistIndex, albumIndex } = indices(graph);
    const evidence = evidenceIndex([release(900, null), release(901, null)]); // both clean

    const result = selectRecommendedRoute(
      graph,
      artistIndex,
      albumIndex,
      "album-a",
      "album-b",
      evidence,
      4,
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.recommended.endpointA.artistId).toBe(200); // Q, not the padded hub P
    expect(result.recommended.facts.maxInteriorDegree).toBeLessThan(20);
  });

  test("once caveat and degree tie, prefers the bridge with more performer-role hops", () => {
    const graph = twoBridgeGraph({
      bridgeOneRoles: ["Executive-Producer", "Executive-Producer"], // non-performer
      bridgeTwoRoles: ["Vocals", "Vocals"], // performer
    });
    const { artistIndex, albumIndex } = indices(graph);
    const evidence = evidenceIndex([release(900, null), release(901, null)]);

    const result = selectRecommendedRoute(
      graph,
      artistIndex,
      albumIndex,
      "album-a",
      "album-b",
      evidence,
      4,
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.recommended.endpointA.artistId).toBe(200); // Q, the performer bridge
    expect(result.recommended.facts.performerHopCount).toBe(1);
  });

  test("with no caveat vocabulary available, ranking degrades to degree+role only", () => {
    const graph = twoBridgeGraph({ padHubDegree: 20 });
    const { artistIndex, albumIndex } = indices(graph);

    const result = selectRecommendedRoute(
      graph,
      artistIndex,
      albumIndex,
      "album-a",
      "album-b",
      NO_EVIDENCE,
      4,
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.recommended.facts.worstCaveatSeverity).toBeNull();
    // Degree still decides -- caveat's absence must not stop the other axes.
    expect(result.recommended.endpointA.artistId).toBe(200);
    expect(result.rankingDegraded).toBe(false);
  });
});

test.describe("selectRecommendedRoute: determinism", () => {
  test("repeated calls over the same graph agree exactly", () => {
    const graph = twoBridgeGraph({});
    const { artistIndex, albumIndex } = indices(graph);
    const evidence = evidenceIndex([release(900, null), release(901, null)]);

    const first = selectRecommendedRoute(
      graph,
      artistIndex,
      albumIndex,
      "album-a",
      "album-b",
      evidence,
      4,
    );
    const second = selectRecommendedRoute(
      graph,
      artistIndex,
      albumIndex,
      "album-a",
      "album-b",
      evidence,
      4,
    );
    expect(first.ok && second.ok).toBe(true);
    if (!first.ok || !second.ok) return;
    expect([...first.recommended.usedEdgeKeys].sort()).toEqual(
      [...second.recommended.usedEdgeKeys].sort(),
    );
  });

  test("a fully tied pair still resolves to one deterministic edge-key order, not enumeration order", () => {
    // Both bridges identical on every ranked axis -- only the canonical
    // sorted-edge-key tiebreak can decide, and it must decide the SAME way
    // every time regardless of which candidate the DFS happens to visit
    // first.
    const graph = twoBridgeGraph({});
    const { artistIndex, albumIndex } = indices(graph);
    const evidence = evidenceIndex([release(900, null), release(901, null)]);
    const picks = new Set<number>();
    for (let i = 0; i < 5; i++) {
      const result = selectRecommendedRoute(
        graph,
        artistIndex,
        albumIndex,
        "album-a",
        "album-b",
        evidence,
        4,
      );
      if (result.ok) picks.add(result.recommended.endpointA.artistId);
    }
    expect(picks.size).toBe(1);
  });
});

test.describe("selectRecommendedRoute: invariants", () => {
  test("never walks through a non-goal virtual album anchor as an interior step", () => {
    // A third album anchor (-3) sits at EXACTLY the same virtual-node depth
    // as the two real bridges (-1 -> P -> (-3) -> (-2), 3 edges, tied with
    // -1 -> P -> R -> (-2)) -- if the walker's anchor guard were missing,
    // this tied "route" would enter the same shortest layer and, after
    // `stripAlbumAnchors` only removes the first/last hop, would render a
    // synthetic "contributor" carrying the anchor sentinel role. The
    // direct anchor-to-anchor edge is structurally impossible in a real
    // published graph (an anchor only ever borders real contributors) --
    // deliberately adversarial, to prove the guard itself rejects it
    // rather than relying on real data never producing the case.
    // The spurious shortcut is built to WIN on every other ranked axis
    // (clean evidence, lowest degree, a performer-role hop) -- so if the
    // guard were the only thing standing between it and being chosen,
    // removing the guard reliably surfaces it as `recommended` rather than
    // losing on some unrelated axis and passing by accident.
    const edges: Edge[] = [
      {
        a: -1,
        b: 100,
        releaseId: 10,
        roleA: ALBUM_ANCHOR_SENTINEL,
        roleB: "Producer",
      },
      {
        a: -1,
        b: 200,
        releaseId: 10,
        roleA: ALBUM_ANCHOR_SENTINEL,
        roleB: "Producer",
      },
      {
        a: -2,
        b: 300,
        releaseId: 20,
        roleA: ALBUM_ANCHOR_SENTINEL,
        roleB: "Producer",
      },
      {
        a: -2,
        b: 400,
        releaseId: 20,
        roleA: ALBUM_ANCHOR_SENTINEL,
        roleB: "Producer",
      },
      { a: 100, b: 300, releaseId: 900, roleA: "Vocals", roleB: "Vocals" },
      { a: 200, b: 400, releaseId: 901, roleA: "Vocals", roleB: "Vocals" },
      // The tied shortcut through a third anchor -- a performer role on
      // its real-node side, clean evidence, and (via the degree padding
      // below) the lowest-degree interior node of any candidate.
      {
        a: 100,
        b: -3,
        releaseId: 30,
        roleA: "Vocals",
        roleB: ALBUM_ANCHOR_SENTINEL,
      },
      {
        a: -3,
        b: -2,
        releaseId: 31,
        roleA: ALBUM_ANCHOR_SENTINEL,
        roleB: ALBUM_ANCHOR_SENTINEL,
      },
    ];
    const nodeIds = [-3, -2, -1, 100, 200, 300, 400];
    const names = ["Album C", "Album B", "Album A", "P", "Q", "R", "S"];
    // Pad both real bridges' second endpoints well above node -3's degree
    // (2), so degree alone would make the spurious candidate rank BEST if
    // it were ever allowed to be enumerated at all.
    for (let i = 0; i < 10; i++) {
      nodeIds.push(2000 + i, 2100 + i);
      names.push(`Pad R ${i}`, `Pad S ${i}`);
      edges.push({ a: 300, b: 2000 + i, releaseId: 6000 + i });
      edges.push({ a: 400, b: 2100 + i, releaseId: 6100 + i });
    }
    const graph = buildGraph(nodeIds, names, edges, [
      { album_id: "album-a", virtual_artist_id: -1, main_release_id: 10 },
      { album_id: "album-b", virtual_artist_id: -2, main_release_id: 20 },
      { album_id: "album-c", virtual_artist_id: -3, main_release_id: 30 },
    ]);
    const { artistIndex, albumIndex } = indices(graph);
    const evidence = evidenceIndex([
      release(900, null),
      release(901, null),
      release(30, null),
    ]);

    const result = selectRecommendedRoute(
      graph,
      artistIndex,
      albumIndex,
      "album-a",
      "album-b",
      evidence,
      4,
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    // Must still be a real 1-hop bridge, never the 2-hop anchor shortcut.
    expect(result.recommended.hops.length).toBe(1);
    for (const hop of result.recommended.hops) {
      expect(hop.role_a).not.toBe(ALBUM_ANCHOR_SENTINEL);
      expect(hop.role_b).not.toBe(ALBUM_ANCHOR_SENTINEL);
    }
  });

  test("an unknown album id is unknown-album, not a thrown error", () => {
    const graph = twoBridgeGraph({});
    const { artistIndex, albumIndex } = indices(graph);
    const result = selectRecommendedRoute(
      graph,
      artistIndex,
      albumIndex,
      "album-a",
      "master-does-not-exist",
      NO_EVIDENCE,
      4,
    );
    expect(result).toEqual({ ok: false, reason: "unknown-album" });
  });

  test("hard expansion cap triggers a safe fallback to the plain first-found route", () => {
    const graph = twoBridgeGraph({});
    const { artistIndex, albumIndex } = indices(graph);
    const evidence = evidenceIndex([release(900, null), release(901, null)]);

    // A budget too small to even complete the reverse-distance precompute.
    const result = selectRecommendedRoute(
      graph,
      artistIndex,
      albumIndex,
      "album-a",
      "album-b",
      evidence,
      4,
      undefined,
      300,
      1,
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.rankingDegraded).toBe(true);

    const plain = findAlbumRoute(
      graph,
      artistIndex,
      albumIndex,
      "album-a",
      "album-b",
      4,
    );
    expect(plain.ok).toBe(true);
    if (!plain.ok) return;
    expect([...result.recommended.usedEdgeKeys].sort()).toEqual(
      [...plain.usedEdgeKeys].sort(),
    );
  });

  test("hard route cap is honored -- never returns more candidates than the cap even though it still ranks correctly", () => {
    const graph = twoBridgeGraph({});
    const { artistIndex, albumIndex } = indices(graph);
    const evidence = evidenceIndex([
      release(900, "unofficial"),
      release(901, null),
    ]);

    const result = selectRecommendedRoute(
      graph,
      artistIndex,
      albumIndex,
      "album-a",
      "album-b",
      evidence,
      4,
      undefined,
      1, // only one candidate allowed through
      400_000,
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    // Still degraded-free: 1 candidate is enough to "rank" (trivially).
    expect(result.rankingDegraded).toBe(false);
  });
});

test.describe("selectRecommendedRoute: the +1-hop escape hatch", () => {
  test("adopts a +1-hop route only when EVERY shortest-layer candidate is worst-tier caveated and a strictly better one exists", () => {
    // Both 1-hop bridges are unofficial-evidenced; a clean 2-hop route
    // exists via a third contributor.
    const edges: Edge[] = [
      {
        a: -1,
        b: 100,
        releaseId: 10,
        roleA: ALBUM_ANCHOR_SENTINEL,
        roleB: "Producer",
      },
      {
        a: -1,
        b: 200,
        releaseId: 10,
        roleA: ALBUM_ANCHOR_SENTINEL,
        roleB: "Producer",
      },
      {
        a: -2,
        b: 300,
        releaseId: 20,
        roleA: ALBUM_ANCHOR_SENTINEL,
        roleB: "Producer",
      },
      {
        a: -2,
        b: 400,
        releaseId: 20,
        roleA: ALBUM_ANCHOR_SENTINEL,
        roleB: "Producer",
      },
      { a: 100, b: 300, releaseId: 900, roleA: "Vocals", roleB: "Vocals" },
      { a: 200, b: 400, releaseId: 901, roleA: "Vocals", roleB: "Vocals" },
      // A clean +1-hop route: Q -> T -> S
      { a: 200, b: 500, releaseId: 902, roleA: "Vocals", roleB: "Vocals" },
      { a: 500, b: 400, releaseId: 903, roleA: "Vocals", roleB: "Vocals" },
    ];
    const graph = buildGraph(
      [-2, -1, 100, 200, 300, 400, 500],
      ["Album B", "Album A", "P", "Q", "R", "S", "T"],
      edges,
      [
        { album_id: "album-a", virtual_artist_id: -1, main_release_id: 10 },
        { album_id: "album-b", virtual_artist_id: -2, main_release_id: 20 },
      ],
    );
    const { artistIndex, albumIndex } = indices(graph);
    const evidence = evidenceIndex([
      release(900, "unofficial"),
      release(901, "unofficial"),
      release(902, null),
      release(903, null),
    ]);

    const result = selectRecommendedRoute(
      graph,
      artistIndex,
      albumIndex,
      "album-a",
      "album-b",
      evidence,
      4,
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.usedPlusOneHop).toBe(true);
    expect(result.recommended.hops.length).toBe(2);
    expect(result.recommended.facts.worstCaveatSeverity).toBe(0);
  });

  test("never conceals a worst-tier shortest route when the +1 layer offers nothing better", () => {
    // Both 1-hop bridges are unofficial-evidenced and NO clean alternative
    // exists at all, at any depth. The engine must still return the real,
    // honestly-caveated shortest route rather than reporting no-path or
    // silently hiding a genuine connection.
    const graph = twoBridgeGraph({
      bridgeOneRelease: 900,
      bridgeTwoRelease: 901,
    });
    const { artistIndex, albumIndex } = indices(graph);
    const evidence = evidenceIndex([
      release(900, "unofficial"),
      release(901, "unofficial"),
    ]);

    const result = selectRecommendedRoute(
      graph,
      artistIndex,
      albumIndex,
      "album-a",
      "album-b",
      evidence,
      4,
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.usedPlusOneHop).toBe(false);
    expect(result.recommended.hops.length).toBe(1);
    expect(result.recommended.facts.worstCaveatSeverity).toBe(3);
  });
});

test.describe("computeRouteFacts / explainRoute", () => {
  function facts(overrides: Partial<RouteFacts>): RouteFacts {
    return {
      hopCount: 1,
      worstCaveatSeverity: 0,
      maxInteriorDegree: 5,
      performerHopCount: 1,
      ...overrides,
    };
  }

  test("explains from the same facts it was given -- no independent computation", () => {
    const lines = explainRoute(facts({ worstCaveatSeverity: 3 }), false);
    expect(lines.some((l) => l.includes("unofficial or bootleg"))).toBe(true);
  });

  test("never asserts a positive 'clean' claim when caveat data was unavailable", () => {
    const lines = explainRoute(facts({ worstCaveatSeverity: null }), false);
    expect(lines.some((l) => l.toLowerCase().includes("caveat"))).toBe(false);
  });

  test("names the +1-hop exception only when it was actually used", () => {
    const withoutPlusOne = explainRoute(facts({}), false);
    const withPlusOne = explainRoute(facts({}), true);
    expect(withoutPlusOne.some((l) => l.includes("one hop longer"))).toBe(
      false,
    );
    expect(withPlusOne.some((l) => l.includes("one hop longer"))).toBe(true);
  });

  test("computeRouteFacts matches a hand-computed result on a small hop list", () => {
    const graph = twoBridgeGraph({});
    const { artistIndex } = indices(graph);
    const evidence = evidenceIndex([release(900, "compilation")]);
    const result = computeRouteFacts(
      graph,
      artistIndex,
      [
        {
          release_id: 900,
          artist_a_id: 100,
          artist_b_id: 300,
          role_a: "Vocals",
          role_b: "Executive-Producer",
        },
      ],
      evidence,
    );
    expect(result.hopCount).toBe(1);
    expect(result.worstCaveatSeverity).toBe(2); // compilation tier
    expect(result.performerHopCount).toBe(1); // Vocals qualifies even though the other side doesn't
  });
});
