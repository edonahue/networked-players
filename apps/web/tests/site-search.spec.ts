// Unit specs for the client-side search ranking (graph-expansion Phase 1,
// plan §7) -- pure functions, no DOM/fetch needed.

import { expect, test } from "@playwright/test";
import { searchIndex, type SearchIndex } from "../src/game/siteSearch";

function index(): SearchIndex {
  return {
    entries: [
      {
        kind: "album",
        id: "master-1",
        label: "Fixture Side Of The Sun",
        sublabel: "Imaginary Ensemble",
        state: "present",
      },
      {
        kind: "album",
        id: "master-2",
        label: "The Barrier",
        sublabel: "Imaginary Ensemble",
        state: "present",
      },
      {
        kind: "contributor",
        id: "100",
        label: "Dana Quillfeather",
        sublabel: null,
        state: "present",
      },
      {
        kind: "contributor",
        id: "200",
        label: "Café Fictional",
        sublabel: null,
        state: "present",
      },
    ],
  };
}

test("empty or whitespace-only query returns no results", () => {
  expect(searchIndex(index(), "")).toEqual([]);
  expect(searchIndex(index(), "   ")).toEqual([]);
});

test("exact match ranks above a prefix match on a different entry", () => {
  const results = searchIndex(index(), "the barrier");
  expect(results[0].id).toBe("master-2");
});

test("a prefix match on any token, not just the first word, matches", () => {
  const results = searchIndex(index(), "side");
  expect(results.map((r) => r.id)).toContain("master-1");
});

test("substring match still finds a result with no token boundary at the query", () => {
  const results = searchIndex(index(), "illfeat");
  expect(results.map((r) => r.id)).toContain("100");
});

test("matches the sublabel (artist name), not just the label", () => {
  const results = searchIndex(index(), "imaginary ensemble");
  expect(results.map((r) => r.id).sort()).toEqual(["master-1", "master-2"]);
});

test("diacritics are folded -- an unaccented query matches an accented label", () => {
  const results = searchIndex(index(), "cafe");
  expect(results.map((r) => r.id)).toContain("200");
});

test("kinds option restricts results to the requested kind", () => {
  const results = searchIndex(index(), "e", { kinds: ["contributor"] });
  expect(results.every((r) => r.kind === "contributor")).toBe(true);
});

test("limit caps the number of returned results", () => {
  const results = searchIndex(index(), "e", { limit: 1 });
  expect(results).toHaveLength(1);
});

test("an unmatched query returns an empty array, not an error", () => {
  expect(searchIndex(index(), "zzzznonexistent")).toEqual([]);
});

test("present ranks before candidate at the same match quality", () => {
  const mixed: SearchIndex = {
    entries: [
      {
        kind: "album",
        id: "master-candidate",
        label: "Synthetic Candidate Album",
        sublabel: "Imaginary Ensemble",
        state: "candidate",
      },
      {
        kind: "album",
        id: "master-present",
        label: "Synthetic Present Album",
        sublabel: "Imaginary Ensemble",
        state: "present",
      },
    ],
  };
  const results = searchIndex(mixed, "imaginary ensemble");
  expect(results[0].id).toBe("master-present");
});

test("ranking is stable and deterministic across repeated calls", () => {
  const first = searchIndex(index(), "imaginary ensemble").map((r) => r.id);
  const second = searchIndex(index(), "imaginary ensemble").map((r) => r.id);
  expect(first).toEqual(second);
});
