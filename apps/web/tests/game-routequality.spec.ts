// Unit specs for the distinct-alternate-route explanation module (ADR
// 0051, renamed post-Phase-4 cleanup audit) -- pure functions over an
// already-found path, no browser needed.

import { expect, test } from "@playwright/test";
import { explainScore } from "../src/game/routeQuality";
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
