// Unit specs for the role-filtered Connect Two Records modes -- Behind the
// Glass (ADR 0053), Rhythm Section, and Guitar Paths (both added in a
// Phase 2 follow-up slice once role_mode_candidates.py's real measurement
// cleared the launch floor). TS ports of real eligibility.py/role_taxonomy.py
// token sets, plus findPath's edgeFilter parameter. No browser or fetch
// needed.

import { expect, test } from "@playwright/test";
import {
  behindTheGlassEdgeFilter,
  guitarPathsEdgeFilter,
  isEngineeringOrProductionRole,
  isGuitarRole,
  isRhythmSectionRole,
  rhythmSectionEdgeFilter,
} from "../src/game/roleTaxonomy";
import {
  buildArtistIndex,
  findPath,
  type PathfindingGraph,
} from "../src/game/pathfindingGraph";

test.describe("isEngineeringOrProductionRole", () => {
  test("recognizes real production/engineering role strings", () => {
    for (const role of [
      "Producer",
      "Co-Producer",
      "Engineer",
      "Mixed By",
      "Mastered By",
      "Recorded By",
    ]) {
      expect(isEngineeringOrProductionRole(role)).toBe(true);
    }
  });

  test("does not classify performer or non-collaborative roles", () => {
    for (const role of ["Vocals", "Guitar", "Written-By", "Design"]) {
      expect(isEngineeringOrProductionRole(role)).toBe(false);
    }
  });

  test("matches a qualifying component among several comma-separated roles", () => {
    expect(isEngineeringOrProductionRole("Vocals, Producer")).toBe(true);
  });

  test("is fail-closed for empty text", () => {
    expect(isEngineeringOrProductionRole("")).toBe(false);
  });
});

test.describe("behindTheGlassEdgeFilter", () => {
  test("requires both endpoints to qualify", () => {
    expect(behindTheGlassEdgeFilter("Producer", "Mixed By")).toBe(true);
    expect(behindTheGlassEdgeFilter("Producer", "Guitar")).toBe(false);
    expect(behindTheGlassEdgeFilter("Guitar", "Bass")).toBe(false);
  });
});

test.describe("isRhythmSectionRole", () => {
  test("recognizes real drums/bass role strings, including bracketed qualifiers", () => {
    for (const role of [
      "Drums",
      "Bass",
      "Bass Guitar",
      "Double Bass",
      "Upright Bass",
      "Bass [Fretless]",
    ]) {
      expect(isRhythmSectionRole(role)).toBe(true);
    }
  });

  test("excludes percussion, a separate display category from drums", () => {
    expect(isRhythmSectionRole("Percussion")).toBe(false);
  });

  test("does not classify unrelated roles", () => {
    for (const role of ["Vocals", "Guitar", "Producer"]) {
      expect(isRhythmSectionRole(role)).toBe(false);
    }
  });

  test("is fail-closed for empty text", () => {
    expect(isRhythmSectionRole("")).toBe(false);
  });
});

test.describe("isGuitarRole", () => {
  test("recognizes real guitar role variants", () => {
    for (const role of [
      "Guitar",
      "Acoustic Guitar",
      "Electric Guitar",
      "Lead Guitar",
      "Rhythm Guitar",
      "Slide Guitar",
      "Steel Guitar",
      "Pedal Steel",
      "Guitar [12-String]",
    ]) {
      expect(isGuitarRole(role)).toBe(true);
    }
  });

  test("does not classify bass or unrelated roles", () => {
    for (const role of ["Bass", "Vocals", "Drums"]) {
      expect(isGuitarRole(role)).toBe(false);
    }
  });
});

test.describe("rhythmSectionEdgeFilter / guitarPathsEdgeFilter", () => {
  test("rhythm section requires both endpoints to be drums/bass", () => {
    expect(rhythmSectionEdgeFilter("Drums", "Bass")).toBe(true);
    expect(rhythmSectionEdgeFilter("Drums", "Guitar")).toBe(false);
  });

  test("guitar paths requires both endpoints to be guitar", () => {
    expect(guitarPathsEdgeFilter("Guitar", "Lead Guitar")).toBe(true);
    expect(guitarPathsEdgeFilter("Guitar", "Bass")).toBe(false);
  });
});

// A -Producer/Producer- B -Credited artist/Credited artist- C: only the
// first hop qualifies under Behind the Glass.
function producerThenCreditedGraph(): PathfindingGraph {
  return {
    schema_version: 1,
    catalog_version: "catalog-v1-test",
    snapshot_date: "20260601",
    generated_at: "2026-08-03T00:00:00+00:00",
    source: "test",
    license: "test",
    node_ids: [100, 200, 300],
    names: ["Alice", "Bob", "Cara"],
    offsets: [0, 2, 4, 5],
    neighbors: [1, 2, 0, 2, 0],
    evidence_release_ids: [1, 9, 1, 9, 9],
    edge_role_a: [
      "Producer",
      "Credited artist",
      "Producer",
      "Credited artist",
      "Credited artist",
    ],
    edge_role_b: [
      "Producer",
      "Credited artist",
      "Producer",
      "Credited artist",
      "Credited artist",
    ],
    pathfinding_graph_version: "pathfinding-graph-v1-20260601-test",
  };
}

test("findPath's edgeFilter restricts traversal to qualifying edges", () => {
  const graph = producerThenCreditedGraph();
  const index = buildArtistIndex(graph);

  const unfiltered = findPath(graph, index, 100, 300, 4);
  expect(unfiltered).toEqual({ ok: true, hops: expect.any(Array) });

  const filtered = findPath(
    graph,
    index,
    100,
    300,
    4,
    behindTheGlassEdgeFilter,
  );
  expect(filtered).toEqual({ ok: false, reason: "no-path" });

  const directHop = findPath(
    graph,
    index,
    100,
    200,
    4,
    behindTheGlassEdgeFilter,
  );
  expect(directHop.ok).toBe(true);
});
