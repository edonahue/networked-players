// Unit specs for the round engine, scoring, PRNG, and sleeve generator —
// pure-node tests in the Playwright runner (same pattern as
// cohort-manifest.spec.ts: no browser, no server).

import { expect, test } from "@playwright/test";
import { createEngine } from "../src/game/engine";
import { createRng, dailySeed } from "../src/game/prng";
import { rateRound, ratingGlyph, summarizeSet } from "../src/game/scoring";
import { sleeveSvg } from "../src/game/sleeves";
import type { GameAlbum, GameRound } from "../src/game/types";

const contributor = (id: number, name: string) => ({
  id,
  name,
  role_category: "bass",
});

function oneHopRound(): GameRound {
  return {
    id: "test-1h",
    pool: "synthetic-universe",
    kind: "one_hop",
    difficulty: "easy",
    endpoints: [
      { id: "syn-a01", title: "A", year: 1974, act: "Act A", art: null },
      { id: "syn-a02", title: "B", year: 1975, act: "Act B", art: null },
    ],
    answer_set: [contributor(1, "Answer One")],
    distractors: [contributor(2, "Wrong Two"), contributor(3, "Wrong Three")],
    clues: [
      { kind: "years", text: "years" },
      { kind: "role", text: "role" },
    ],
    evidence: [
      {
        release_ref: "syn-r01",
        release_title: "A",
        contributor_id: 1,
        credited_as: "Answer One",
        role_text: "Bass",
        credit_scope: "release_credit",
      },
    ],
    provenance_note: "test",
  };
}

function twoHopRound(): GameRound {
  return {
    ...oneHopRound(),
    id: "test-2h",
    kind: "two_hop",
    middle: {
      album: { id: "syn-a03", title: "M", year: 1976, act: "Act M", art: null },
      choices: [
        { id: "syn-a03", title: "M", year: 1976, act: "Act M", art: null },
        { id: "syn-a04", title: "X", year: 1977, act: "Act X", art: null },
      ],
    },
    bridge_answer_sets: [
      [contributor(1, "Bridge A")],
      [contributor(4, "Bridge C")],
    ],
    answer_set: [contributor(1, "Bridge A"), contributor(4, "Bridge C")],
  };
}

test("one-hop: clean solve path", () => {
  const engine = createEngine(oneHopRound());
  expect(engine.state().phase).toBe("idle");
  engine.deal();
  expect(engine.state().phase).toBe("dealing");
  engine.present();
  expect(engine.state().phase).toBe("guessing");
  engine.choose(1);
  const state = engine.state();
  expect(state.phase).toBe("revealed");
  expect(state.solved).toBe(true);
  expect(state.rating).toBe("clean");
});

test("one-hop: wrong then right rates with_clues", () => {
  const engine = createEngine(oneHopRound());
  engine.deal();
  engine.present();
  engine.choose(2);
  expect(engine.state().struck).toEqual([2]);
  expect(engine.state().phase).toBe("guessing");
  engine.choose(1);
  expect(engine.state().solved).toBe(true);
  expect(engine.state().rating).toBe("with_clues");
});

test("one-hop: attempt exhaustion resolves as revealed", () => {
  const engine = createEngine(oneHopRound());
  engine.deal();
  engine.present();
  engine.choose(2);
  engine.choose(3);
  const state = engine.state();
  expect(state.phase).toBe("revealed");
  expect(state.failed).toBe(true);
  expect(state.rating).toBe("revealed");
});

test("clue usage costs the clean rating and stops when exhausted", () => {
  const engine = createEngine(oneHopRound());
  engine.deal();
  engine.present();
  expect(engine.useClue()).toBe(0);
  expect(engine.useClue()).toBe(1);
  expect(engine.useClue()).toBe(-1); // only two clues defined
  engine.choose(1);
  expect(engine.state().rating).toBe("with_clues");
});

test("two-hop walks bridge_a, bridge_b, then middle", () => {
  const engine = createEngine(twoHopRound());
  engine.deal();
  engine.present();
  expect(engine.state().step).toBe("bridge_a");
  engine.choose(1);
  expect(engine.state().step).toBe("bridge_b");
  expect(engine.state().phase).toBe("guessing");
  engine.choose(4);
  expect(engine.state().step).toBe("middle");
  engine.choose("syn-a04"); // wrong middle
  expect(engine.state().struckAlbums).toEqual(["syn-a04"]);
  engine.choose("syn-a03");
  const state = engine.state();
  expect(state.solved).toBe(true);
  expect(state.solvedSteps).toEqual(["bridge_a", "bridge_b", "middle"]);
});

test("two-hop partial progress still fails on exhaustion", () => {
  const engine = createEngine(twoHopRound());
  engine.deal();
  engine.present();
  engine.choose(1); // bridge_a solved
  engine.choose(99); // wrong
  engine.choose(98); // wrong -> exhausted
  const state = engine.state();
  expect(state.failed).toBe(true);
  expect(state.solvedSteps).toEqual(["bridge_a"]);
});

test("reveal gives up and rates revealed", () => {
  const engine = createEngine(oneHopRound());
  engine.deal();
  engine.present();
  engine.reveal();
  expect(engine.state().rating).toBe("revealed");
});

test("prng is deterministic for identical seeds", () => {
  const a = createRng("seed-42");
  const b = createRng("seed-42");
  const seqA = [a.next(), a.next(), a.next(), a.int(100), a.int(100)];
  const seqB = [b.next(), b.next(), b.next(), b.int(100), b.int(100)];
  expect(seqA).toEqual(seqB);
  const c = createRng("seed-43");
  expect([c.next(), c.next()]).not.toEqual(seqA.slice(0, 2));
  expect(dailySeed(new Date("2026-07-18T22:11:00Z"))).toBe(
    "np-daily-2026-07-18",
  );
});

test("scoring maps outcomes to needle-drop ratings", () => {
  expect(rateRound({ solved: true, cluesUsed: 0, wrongAttempts: 0 })).toBe(
    "clean",
  );
  expect(rateRound({ solved: true, cluesUsed: 2, wrongAttempts: 0 })).toBe(
    "with_clues",
  );
  expect(rateRound({ solved: false, cluesUsed: 0, wrongAttempts: 2 })).toBe(
    "revealed",
  );
  const summary = summarizeSet(["clean", "with_clues", "revealed", "clean"]);
  expect(summary).toEqual({ played: 4, clean: 2, withClues: 1, revealed: 1 });
  expect(["●", "◐", "○"]).toEqual(
    (["clean", "with_clues", "revealed"] as const).map(ratingGlyph),
  );
});

test("sleeve generator is deterministic and always stamps SYNTHETIC", () => {
  const meridian: GameAlbum = {
    id: "syn-a01",
    title: "Late Ferry",
    act: "The Harbor Lights",
    act_id: 90001001,
    year: 1974,
    label: "Meridian",
    art: { kind: "generated" },
  };
  const kettle: GameAlbum = {
    ...meridian,
    id: "syn-a03",
    label: "Copper Kettle",
  };
  const first = sleeveSvg(meridian);
  expect(sleeveSvg(meridian)).toBe(first);
  expect(first).toContain("SYNTHETIC");
  expect(first).toContain("<svg");
  const other = sleeveSvg(kettle);
  expect(other).toContain("SYNTHETIC");
  expect(other).not.toBe(first);
});
