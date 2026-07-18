// Contract and correctness validation for the committed game artifacts
// (public/data/game/*.json), independent of scripts/build-rounds.mjs's own
// checks: the script is exercised via --check (drift + internal validation),
// then the artifacts are re-verified here from first principles so a bug in
// the generator's validator can't silently pass its own output.

import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import type { GameRounds, GameUniverse } from "../src/game/types";

const webRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const universe = JSON.parse(
  readFileSync(join(webRoot, "public/data/game/universe.v1.json"), "utf8"),
) as GameUniverse;
const roundsArtifact = JSON.parse(
  readFileSync(join(webRoot, "public/data/game/rounds.v1.json"), "utf8"),
) as GameRounds;
const challenge = JSON.parse(
  readFileSync(join(webRoot, "public/data/challenge.v1.json"), "utf8"),
) as {
  releases: Array<{
    release_id: number;
    credits: Array<{
      artist_id: number | null;
      is_linked: boolean;
      playable_identity: boolean;
    }>;
  }>;
};

const FORBIDDEN_SUBSTRINGS = [
  "/home/",
  "data/private",
  "local" + "/",
  ".ssh",
  "DISCOGS_TOKEN",
];
const FORBIDDEN_PHRASES = ["worked with", "collaborated with", "influenced"];

test("build-rounds --check passes (validation + no drift)", () => {
  execFileSync("node", ["scripts/build-rounds.mjs", "--check"], {
    cwd: webRoot,
    stdio: "pipe",
  });
});

test("running derivation twice is deterministic", () => {
  const first = execFileSync("node", ["scripts/build-rounds.mjs", "--check"], {
    cwd: webRoot,
    stdio: "pipe",
  }).toString();
  const second = execFileSync("node", ["scripts/build-rounds.mjs", "--check"], {
    cwd: webRoot,
    stdio: "pipe",
  }).toString();
  expect(first).toBe(second);
});

test("pool sizes and difficulty coverage meet the plan's floor", () => {
  const synthetic = roundsArtifact.rounds.filter(
    (r) => r.pool === "synthetic-universe",
  );
  const real = roundsArtifact.rounds.filter((r) => r.pool === "real-records");
  expect(synthetic.length).toBeGreaterThanOrEqual(40);
  expect(
    synthetic.filter((r) => r.kind === "two_hop").length,
  ).toBeGreaterThanOrEqual(8);
  expect(real.length).toBeGreaterThanOrEqual(6);
  for (const difficulty of ["easy", "medium", "hard"] as const) {
    expect(
      synthetic.some((r) => r.difficulty === difficulty),
      `synthetic pool needs a ${difficulty} round`,
    ).toBe(true);
  }
});

test("no distractor satisfies the connection (synthetic, first principles)", () => {
  const releaseAlbum = new Map(
    universe.releases.map((r) => [r.id, r.album_id]),
  );
  const albumsByContributor = new Map<number, Set<string>>();
  for (const credit of universe.credits) {
    const albumId = releaseAlbum.get(credit.release_id)!;
    if (!albumsByContributor.has(credit.contributor_id))
      albumsByContributor.set(credit.contributor_id, new Set());
    albumsByContributor.get(credit.contributor_id)!.add(albumId);
  }
  for (const round of roundsArtifact.rounds) {
    if (round.pool !== "synthetic-universe") continue;
    const answerIds = new Set(round.answer_set.map((a) => a.id));
    for (const distractor of round.distractors) {
      expect(answerIds.has(distractor.id)).toBe(false);
      const albums = albumsByContributor.get(distractor.id) ?? new Set();
      const linksBoth = round.endpoints.every((e) => albums.has(e.id));
      expect(
        linksBoth,
        `round ${round.id}: distractor ${distractor.name} links both endpoints`,
      ).toBe(false);
    }
  }
});

test("no distractor satisfies the connection (real, first principles)", () => {
  const linkedByRelease = new Map<number, Set<number>>();
  for (const release of challenge.releases) {
    const ids = new Set<number>();
    for (const credit of release.credits) {
      if (credit.is_linked && credit.playable_identity && credit.artist_id)
        ids.add(credit.artist_id);
    }
    linkedByRelease.set(release.release_id, ids);
  }
  for (const round of roundsArtifact.rounds) {
    if (round.pool !== "real-records") continue;
    const endpointIds = round.endpoints.map((e) =>
      Number(e.id.replace("real-rel-", "")),
    );
    for (const answer of round.answer_set) {
      for (const releaseId of endpointIds) {
        expect(
          linkedByRelease.get(releaseId)!.has(answer.id),
          `round ${round.id}: answer ${answer.name} missing on release ${releaseId}`,
        ).toBe(true);
      }
    }
    for (const distractor of round.distractors) {
      const onBoth = endpointIds.every((releaseId) =>
        linkedByRelease.get(releaseId)!.has(distractor.id),
      );
      expect(
        onBoth,
        `round ${round.id}: distractor ${distractor.name} is credited on both`,
      ).toBe(false);
    }
  }
});

test("every round carries evidence for every answer and a provenance note", () => {
  for (const round of roundsArtifact.rounds) {
    expect(round.evidence.length).toBeGreaterThan(0);
    expect(round.provenance_note.length).toBeGreaterThan(10);
    for (const answer of round.answer_set) {
      expect(
        round.evidence.some((row) => row.contributor_id === answer.id),
        `round ${round.id}: answer ${answer.name} lacks evidence rows`,
      ).toBe(true);
    }
    if (round.kind === "two_hop") {
      expect(round.middle).toBeTruthy();
      expect(round.bridge_answer_sets).toBeTruthy();
      expect(
        round.middle!.choices.some((c) => c.id === round.middle!.album.id),
      ).toBe(true);
    }
  }
});

test("artifacts are free of forbidden substrings and influence phrasing", () => {
  for (const [label, artifact] of [
    ["universe", universe],
    ["rounds", roundsArtifact],
  ] as const) {
    const lowered = JSON.stringify(artifact).toLowerCase();
    for (const substring of FORBIDDEN_SUBSTRINGS) {
      expect(
        lowered.includes(substring.toLowerCase()),
        `${label} must not contain ${substring}`,
      ).toBe(false);
    }
    for (const phrase of FORBIDDEN_PHRASES) {
      expect(
        lowered.includes(phrase),
        `${label} must not contain "${phrase}"`,
      ).toBe(false);
    }
  }
});

test("synthetic provenance self-identifies in isolation; ids stay in reserved ranges", () => {
  for (const field of ["source", "license", "note"] as const) {
    const value = universe.provenance[field].toLowerCase();
    expect(
      value.includes("synthetic") || value.includes("fiction"),
      `provenance.${field} must self-identify`,
    ).toBe(true);
  }
  for (const album of universe.albums) expect(album.id).toMatch(/^syn-a\d{2}$/);
  for (const c of universe.contributors)
    expect(c.id).toBeGreaterThanOrEqual(90000000);
  for (const round of roundsArtifact.rounds) {
    if (round.pool === "synthetic-universe") {
      for (const e of round.endpoints) expect(e.id).toMatch(/^syn-a/);
      if (e2eArtIsHotlink(round))
        throw new Error("synthetic round hotlinks art");
    } else {
      for (const e of round.endpoints) {
        expect(e.id).toMatch(/^real-rel-\d+$/);
        if (e.art) {
          expect(e.art.kind).toBe("hotlink");
          if (e.art.kind === "hotlink") {
            expect(e.art.uri150.startsWith("https://i.discogs.com/")).toBe(
              true,
            );
          }
        }
      }
    }
  }
});

function e2eArtIsHotlink(round: GameRounds["rounds"][number]): boolean {
  return round.endpoints.some(
    (e) => e.art !== null && e.art.kind === "hotlink",
  );
}
