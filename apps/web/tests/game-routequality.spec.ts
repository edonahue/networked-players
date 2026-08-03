// Unit specs for the "more musical route" scoring module (ADR 0051) -- pure
// functions over an already-found path, no browser needed.

import { expect, test } from "@playwright/test";
import {
  explainScore,
  hubPenalty,
  roleSignalScore,
  scorePath,
} from "../src/game/routeQuality";
import type { PathHop } from "../src/game/pathfindingGraph";
import type { Contributor } from "../src/data/contributors";

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

function hop(a: number, b: number, releaseId = 1): PathHop {
  return {
    release_id: releaseId,
    artist_a_id: a,
    artist_b_id: b,
    role_a: "Role",
    role_b: "Role",
  };
}

test("roleSignalScore rewards performer hops over production-only hops", () => {
  const performerHop = [hop(1, 2)];
  const productionHop = [hop(3, 4)];
  const byId = new Map<number, Contributor>([
    [1, contributor({ artist_id: 1, role_categories: ["vocals"] })],
    [2, contributor({ artist_id: 2, role_categories: ["strings"] })],
    [3, contributor({ artist_id: 3, role_categories: ["production"] })],
    [4, contributor({ artist_id: 4, role_categories: ["engineering"] })],
  ]);
  expect(roleSignalScore(performerHop, byId)).toBeGreaterThan(
    roleSignalScore(productionHop, byId),
  );
});

test("hubPenalty counts each distinct contributor once, not once per hop touched", () => {
  const byId = new Map<number, Contributor>([
    [1, contributor({ artist_id: 1, connection_count: 5 })],
    [2, contributor({ artist_id: 2, connection_count: 5 })],
    [3, contributor({ artist_id: 3, connection_count: 5 })],
  ]);
  // A real chained path: 1-2-3. Artist 2 bridges both hops (the normal
  // shape of any path), and must not be double-penalized for it.
  const chained = [hop(1, 2), hop(2, 3)];
  const expectedPenalty =
    Math.log10(6) /* artist 1 */ +
    Math.log10(6) /* artist 2 */ +
    Math.log10(6); /* artist 3 */
  expect(hubPenalty(chained, byId)).toBeCloseTo(expectedPenalty, 5);
});

test("hubPenalty grows with contributor degree", () => {
  const lowDegree = new Map<number, Contributor>([
    [1, contributor({ artist_id: 1, connection_count: 1 })],
    [2, contributor({ artist_id: 2, connection_count: 1 })],
  ]);
  const highDegree = new Map<number, Contributor>([
    [1, contributor({ artist_id: 1, connection_count: 500 })],
    [2, contributor({ artist_id: 2, connection_count: 500 })],
  ]);
  const hops = [hop(1, 2)];
  expect(hubPenalty(hops, highDegree)).toBeGreaterThan(
    hubPenalty(hops, lowDegree),
  );
});

test("scorePath prefers fewer hops above all else", () => {
  const byId = new Map<number, Contributor>([
    [1, contributor({ artist_id: 1, role_categories: ["production"] })],
    [2, contributor({ artist_id: 2, role_categories: ["production"] })],
  ]);
  const oneHop = [hop(1, 2)];
  const twoHops = [hop(1, 3), hop(3, 2)];
  expect(scorePath(oneHop, byId)).toBeGreaterThan(scorePath(twoHops, byId));
});

test("explainScore always names the hop count and never hides the reasoning", () => {
  const byId = new Map<number, Contributor>([
    [1, contributor({ artist_id: 1, role_categories: ["vocals"] })],
    [2, contributor({ artist_id: 2, role_categories: ["production"] })],
  ]);
  const explanation = explainScore([hop(1, 2)], byId);
  expect(explanation[0]).toBe("1 hop");
  expect(explanation.some((line) => line.includes("performer"))).toBe(true);
  expect(explanation.some((line) => line.includes("hub"))).toBe(true);
});

test("explainScore reports no high-degree hub for a low-degree path", () => {
  const byId = new Map<number, Contributor>([
    [1, contributor({ artist_id: 1, connection_count: 2 })],
    [2, contributor({ artist_id: 2, connection_count: 2 })],
    [3, contributor({ artist_id: 3, connection_count: 2 })],
  ]);
  const explanation = explainScore([hop(1, 2), hop(2, 3)], byId);
  expect(explanation).toContain("no highly-connected hub in this path");
});

test("explainScore flags a genuinely high-degree hub in the path", () => {
  const byId = new Map<number, Contributor>([
    [1, contributor({ artist_id: 1, connection_count: 2 })],
    [2, contributor({ artist_id: 2, connection_count: 500 })],
    [3, contributor({ artist_id: 3, connection_count: 2 })],
  ]);
  const explanation = explainScore([hop(1, 2), hop(2, 3)], byId);
  expect(explanation).toContain(
    "passes through a highly-connected hub contributor",
  );
});
