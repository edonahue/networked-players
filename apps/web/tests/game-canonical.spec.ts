// Unit specs for canonical.ts -- pure-node tests in the Playwright runner
// (same pattern as game-engine.spec.ts: no browser, no server). Corrective
// slice 4.6: proves the TypeScript canonical-hashing port agrees with the
// Python implementation it must match byte-for-byte
// (packages/contracts/src/networked_players_contracts/canonical.py).

import { expect, test } from "@playwright/test";
import { canonicalJson, contentHash, roundContentFingerprint } from "../src/game/canonical";

test("canonicalJson sorts keys at every nesting level", () => {
  const a = { b: 2, a: { y: 1, x: [3, 2, 1] } };
  const b = { a: { x: [3, 2, 1], y: 1 }, b: 2 };
  expect(canonicalJson(a)).toBe(canonicalJson(b));
  expect(canonicalJson(a)).toBe('{"a":{"x":[3,2,1],"y":1},"b":2}');
});

test("canonicalJson has no insignificant whitespace", () => {
  expect(canonicalJson({ a: 1, b: [1, 2] })).toBe('{"a":1,"b":[1,2]}');
});

test("canonicalJson leaves non-ASCII characters unescaped", () => {
  expect(canonicalJson({ name: "Café" })).toBe('{"name":"Café"}');
});

test("contentHash is deterministic and order-independent", async () => {
  const a = { id: "conn-x", clues: [{ kind: "years", text: "1990" }] };
  const b = { clues: [{ text: "1990", kind: "years" }], id: "conn-x" };
  expect(await contentHash(a)).toBe(await contentHash(b));
});

test("contentHash changes when a nested value changes", async () => {
  const a = { id: "conn-x", distractors: [{ id: 1, name: "Alice" }] };
  const b = { id: "conn-x", distractors: [{ id: 1, name: "Alicia" }] };
  expect(await contentHash(a)).not.toBe(await contentHash(b));
});

test("roundContentFingerprint agrees byte-for-byte with the Python implementation", async () => {
  // Reference value computed independently in Python:
  //   uv run python3 -c "
  //     from networked_players_graph_core.connection_rounds import round_content_fingerprint
  //     sample = {'id': 'conn-x', 'clues': [{'kind': 'role', 'text': 'Bass work.'}],
  //               'nested': {'b': 2, 'a': [1, 2, 3], 'name': 'Café'}}
  //     print(round_content_fingerprint(sample))"
  // Includes a non-ASCII character deliberately -- the one real risk of the
  // two languages' JSON serializers disagreeing (Python's ensure_ascii vs.
  // JSON.stringify's default of leaving non-ASCII unescaped).
  const sample = {
    id: "conn-x",
    clues: [{ kind: "role", text: "Bass work." }],
    nested: { b: 2, a: [1, 2, 3], name: "Café" },
  };
  expect(await roundContentFingerprint(sample)).toBe("rfp-9d7599b2937baab3");
});
