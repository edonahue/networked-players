// Unit specs for the role-filtered Connect Two Records modes -- Rhythm
// Section and Guitar Paths, both added in a Phase 2 follow-up slice once
// role_mode_candidates.py's real measurement cleared the launch floor.
// (Behind the Glass, ADR 0053, was retired by ADR 0068 along with the
// background-engineering predicates this file used to cover.) TS ports of
// real eligibility.py/role_taxonomy.py token sets, plus findPath's
// edgeFilter parameter. No browser or fetch needed.

import { expect, test } from "@playwright/test";
import {
  guitarPathsEdgeFilter,
  isGuitarRole,
  isPerformerRole,
  isRhythmSectionRole,
  PERFORMER_TOKEN_COUNT,
  rhythmSectionEdgeFilter,
} from "../src/game/roleTaxonomy";
import { ROLE_CATEGORY_LABEL } from "../src/data/contributors";
import {
  buildArtistIndex,
  findPath,
  type PathfindingGraph,
} from "../src/game/pathfindingGraph";

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

// Pinned parity cases (ADR 0059): each verified against a real
// `is_performer_role(...)` call in eligibility.py at the time this was
// written. A future token-set edit on either side that isn't mirrored on
// the other fails one of these, the same convention this file already
// uses for the three filter-mode token sets above.
test.describe("isPerformerRole", () => {
  test("matches real production output verified against eligibility.py", () => {
    const cases: Array<[string, boolean]> = [
      ["Vocals", true],
      ["Lead Vocals, Producer", true],
      ["Producer", false],
      ["Written-By", false],
      ["Bass Guitar [Fretless]", true],
      ["Trumpet", true],
      ["Synth [Modular]", true],
      ["", false],
      ["Executive-Producer", false],
      ["Rap", true],
      ["Harmonica, Written-By", true],
    ];
    for (const [role, expected] of cases) {
      expect(isPerformerRole(role), role).toBe(expected);
    }
  });

  test("covers each instrument family with at least one representative", () => {
    for (const role of [
      "Backing Vocals",
      "Cello",
      "Drums",
      "Organ",
      "Flugelhorn",
      "Bassoon",
      "Sitar",
    ]) {
      expect(isPerformerRole(role), role).toBe(true);
    }
  });

  test("is fail-closed for empty text and non-collaborative roles", () => {
    expect(isPerformerRole("")).toBe(false);
    for (const role of [
      "Artwork By",
      "Design",
      "A&R",
      "Remixed By",
      "Written-By, Composed By",
    ]) {
      expect(isPerformerRole(role), role).toBe(false);
    }
  });

  // ADR 0068 real-corpus audit (2026-09-01): pinned parity cases for every
  // token GROUP added to eligibility.py's `_PERFORMER_ROLE_TOKENS` this
  // round, plus the tokens explicitly considered and excluded. A future
  // edit to either side's set that isn't mirrored on the other fails one
  // of these, the same convention the rest of this describe block uses.
  test("ADR 0068 audit: matches eligibility.py's expanded token set", () => {
    const included: string[] = [
      "Soprano Vocals",
      "Tenor Vocals",
      "Alto Vocals",
      "Baritone Vocals",
      "Bass Vocals",
      "Human Beatbox",
      "Whistling",
      "Featuring",
      "Performer",
      "Musician",
      "Instruments",
      "Orchestra",
      "Strings",
      "Soloist",
      "Turntables",
      "Scratches",
      "Concertmaster",
      "Zither",
      "Dulcimer",
      "Bouzouki",
      "Kora",
      "Autoharp",
      "Dobro",
      "Tambourine",
      "Cowbell",
      "Steel Drums",
      "Theremin",
      "Moog",
      "Mellotron",
      "Clavinet",
      "Rhodes",
      "Wurlitzer",
      "Vocoder",
      "Talk Box",
      "Recorder",
      "Didgeridoo",
      "Whistle",
      "Melodica",
      "Kazoo",
    ];
    for (const role of included) {
      expect(isPerformerRole(role), role).toBe(true);
    }
    // Real, measured-at-scale tokens explicitly considered and EXCLUDED
    // (see eligibility.py's own audit comment for the corpus-count
    // reasoning behind each).
    const excluded: string[] = [
      "Conductor",
      "Orchestrated By",
      "Programming",
      "Sampler",
      "Cover",
      "Leader",
    ];
    for (const role of excluded) {
      expect(isPerformerRole(role), role).toBe(false);
    }
  });

  // Round-4 Codex review finding on PR #203: the pinned per-token cases
  // above only catch drift on the specific tokens they name -- a token
  // added to (or removed from) one side's set without a matching edit on
  // the other, outside this list, would pass every pinned case. A full
  // set-equality check would need generated-fixture infrastructure this
  // repo does not otherwise have (every other Python/TS parity block in
  // this file -- isRhythmSectionRole, isGuitarRole -- uses this same pinned-example
  // convention); a plain size comparison is the cheap, real, partial
  // guard available without introducing that infrastructure for one
  // block. It cannot say WHICH token drifted, only THAT the two sets'
  // sizes disagree.
  test("token-set size matches eligibility.py's _PERFORMER_ROLE_TOKENS count", () => {
    expect(PERFORMER_TOKEN_COUNT).toBe(109);
  });

  // ADR 0068 addendum (PR 2): found via the shadow-build diagnostic against
  // the real one-hop corpus (124,760 rows), not the original PR 1 audit --
  // the identical case as "Strings".
  test("ADR 0068 addendum: Horns (shadow-diagnostic finding)", () => {
    expect(isPerformerRole("Horns")).toBe(true);
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
// 100 <-> 200 is a Guitar/Guitar edge; 200 <-> 300 is not. Uses Guitar
// Paths since Behind the Glass (the original qualifying filter here)
// was retired by ADR 0068 -- the fixture's SHAPE is what this test
// needs, not that specific mode.
function guitarThenCreditedGraph(): PathfindingGraph {
  return {
    schema_version: 1,
    catalog_version: "catalog-v1-test",
    snapshot_date: "20260601",
    generated_at: "2026-08-03T00:00:00+00:00",
    source: "test",
    license: "test",
    node_ids: new Int32Array([100, 200, 300]),
    names: ["Alice", "Bob", "Cara"],
    offsets: new Int32Array([0, 2, 4, 5]),
    neighbors: new Int32Array([1, 2, 0, 2, 0]),
    evidence_release_ids: new Int32Array([1, 9, 1, 9, 9]),
    edge_role_a: [
      "Guitar",
      "Credited artist",
      "Guitar",
      "Credited artist",
      "Credited artist",
    ],
    edge_role_b: [
      "Guitar",
      "Credited artist",
      "Guitar",
      "Credited artist",
      "Credited artist",
    ],
    pathfinding_graph_version: "pathfinding-graph-v1-20260601-test",
  };
}

test("findPath's edgeFilter restricts traversal to qualifying edges", () => {
  const graph = guitarThenCreditedGraph();
  const index = buildArtistIndex(graph);

  const unfiltered = findPath(graph, index, 100, 300, 4);
  expect(unfiltered).toEqual({ ok: true, hops: expect.any(Array) });

  const filtered = findPath(graph, index, 100, 300, 4, guitarPathsEdgeFilter);
  expect(filtered).toEqual({ ok: false, reason: "no-path" });

  const directHop = findPath(graph, index, 100, 200, 4, guitarPathsEdgeFilter);
  expect(directHop.ok).toBe(true);
});

// Drift guard added with Phase 7's preflight, which introduced a new role
// category (`audiovisual_production`) on the Python side. `ROLE_CATEGORY_LABEL`
// is what builds the contributor directory's filter chips
// (`contributorsDirectory.ts::ROLE_CATEGORY_CHIPS`), so a category the Python
// taxonomy emits but this map doesn't name silently loses its chip -- the
// contributor still renders (line 204 falls back to the raw value), but nobody
// can filter for them. These goldens mirror
// `networked_players_contracts.contributor_index._VALID_ROLE_CATEGORIES`
// exactly; update both together or this fails.
test.describe("ROLE_CATEGORY_LABEL parity", () => {
  test("names exactly the categories the published contract allows", () => {
    expect(Object.keys(ROLE_CATEGORY_LABEL).sort()).toEqual(
      [
        "arrangement",
        "audiovisual_production",
        "brass_woodwind",
        "composition",
        "engineering",
        "packaging_business",
        "percussion_keys",
        "performance",
        "production",
        "rework",
        "strings",
        "unknown",
        "vocals",
      ].sort(),
    );
  });

  test("every label is non-empty and distinct", () => {
    const labels = Object.values(ROLE_CATEGORY_LABEL);
    expect(labels.every((l) => l.trim().length > 0)).toBe(true);
    expect(new Set(labels).size).toBe(labels.length);
  });
});
