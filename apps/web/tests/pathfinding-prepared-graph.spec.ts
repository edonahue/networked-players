// Unit specs for loadPreparedGraph's module-level cache (post-Phase-4
// cleanup audit F11/F12) -- mocks global fetch to prove the graph is only
// ever fetched/parsed once per URL across repeated calls, and that a
// failed attempt doesn't get stuck: a later call retries fresh. No browser
// needed, mirroring pathfinding-bfs.spec.ts's own pure-node pattern.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { loadPreparedGraph } from "../src/game/pathfindingGraph";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "../../..");
const fixtureDir = join(repoRoot, "data/fixtures/pathfinding-graph");

function loadFixtureText(name: string): string {
  return readFileSync(join(fixtureDir, `${name}.json`), "utf8");
}

async function withMockedFetch<T>(
  handler: (url: string) => Response,
  run: () => Promise<T>,
): Promise<T> {
  const original = globalThis.fetch;
  globalThis.fetch = (async (input: RequestInfo | URL) =>
    handler(String(input))) as typeof fetch;
  try {
    return await run();
  } finally {
    globalThis.fetch = original;
  }
}

test("loadPreparedGraph fetches and parses the graph at most once across repeated calls", async () => {
  const wellFormedV1 = loadFixtureText("well-formed-v1");
  let fetchCount = 0;
  const url = "https://example.test/prepared-graph-cache-check-success.json";

  await withMockedFetch(
    () => {
      fetchCount++;
      return new Response(wellFormedV1, { status: 200 });
    },
    async () => {
      const first = await loadPreparedGraph(null, url);
      const second = await loadPreparedGraph(null, url);
      const third = await loadPreparedGraph(null, url);
      expect("prepared" in first).toBe(true);
      expect("prepared" in second).toBe(true);
      expect("prepared" in third).toBe(true);
      // Same object identity, not just equal fetch counts -- proves the
      // second/third call reused the first call's already-built indexes
      // rather than rebuilding them from a re-parsed graph.
      if ("prepared" in first && "prepared" in second) {
        expect(second.prepared).toBe(first.prepared);
      }
      expect(fetchCount).toBe(1);
    },
  );
});

test("loadPreparedGraph does not cache a failure -- a later call retries fresh", async () => {
  const wellFormedV1 = loadFixtureText("well-formed-v1");
  let fetchCount = 0;
  const url = "https://example.test/prepared-graph-cache-check-retry.json";

  await withMockedFetch(
    () => {
      fetchCount++;
      // First call fails (network down); every later call succeeds (the
      // network recovered) -- a real caller must be able to retry, not be
      // stuck replaying the first failure for the rest of the session.
      if (fetchCount === 1) {
        return new Response(null, { status: 500 });
      }
      return new Response(wellFormedV1, { status: 200 });
    },
    async () => {
      const first = await loadPreparedGraph(null, url);
      expect(first).toEqual({ error: "fetch-failed" });

      const second = await loadPreparedGraph(null, url);
      expect("prepared" in second).toBe(true);
      expect(fetchCount).toBe(2);
    },
  );
});
