#!/usr/bin/env node
// Expand the authored Meridian Tapes universe definition and derive the game
// round pool (docs/WEB_PRODUCT_PLAN.md §8). Two committed artifacts:
//
//   public/data/game/universe.v1.json   (game-universe-v1 contract)
//   public/data/game/rounds.v1.json     (game-rounds-v1 contract)
//
// Modes:
//   --write   regenerate both artifacts on disk
//   --check   (default) regenerate in memory, deep-compare against the
//             committed files, and run every validation; non-zero exit on
//             drift or any violation. Wired into `npm run check`/`build`.
//
// Validation is the point: the build fails on any distractor that actually
// satisfies the connection, any empty answer set, any unresolved reference,
// or any forbidden substring/phrase in the serialized artifacts.

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { ALBUMS, CONTRIBUTORS, KIN_PAIRS, ROLE_TEXT } from "./universe-def.mjs";

const WEB_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const UNIVERSE_PATH = join(WEB_ROOT, "public/data/game/universe.v1.json");
const ROUNDS_PATH = join(WEB_ROOT, "public/data/game/rounds.v1.json");
const CHALLENGE_V1_PATH = join(WEB_ROOT, "public/data/challenge.v1.json");

// Discogs placeholder identities excluded from playable answers (ADR 0026/0035).
const PLACEHOLDER_ARTIST_IDS = new Set([194, 151641]);

const FORBIDDEN_SUBSTRINGS = [
  "/home/",
  "data/private",
  "local" + "/",
  ".ssh",
  "DISCOGS_TOKEN",
];
const FORBIDDEN_PHRASES = ["worked with", "collaborated with", "influenced"];

const CAPS = { synOneHop: 34, synTwoHop: 14, real: 12 };
const MIN = { synthetic: 40, synTwoHop: 8, real: 6 };

// --- tiny deterministic PRNG (mirror of src/game/prng.ts) -------------------
function xmur3(str) {
  let h = 1779033703 ^ str.length;
  for (let i = 0; i < str.length; i += 1) {
    h = Math.imul(h ^ str.charCodeAt(i), 3432918353);
    h = (h << 13) | (h >>> 19);
  }
  return () => {
    h = Math.imul(h ^ (h >>> 16), 2246822507);
    h = Math.imul(h ^ (h >>> 13), 3266489909);
    h ^= h >>> 16;
    return h >>> 0;
  };
}
function rng(seed) {
  let a = xmur3(seed)();
  const random = () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  return {
    shuffle(items) {
      const copy = items.slice();
      for (let i = copy.length - 1; i > 0; i -= 1) {
        const j = Math.floor(random() * (i + 1));
        [copy[i], copy[j]] = [copy[j], copy[i]];
      }
      return copy;
    },
  };
}

// --- universe expansion ------------------------------------------------------
function buildUniverse() {
  const albums = ALBUMS.map(([id, title, act, actId, year, label, hasArt]) => ({
    id,
    title,
    act,
    act_id: actId,
    year,
    label,
    art: hasArt ? { kind: "generated" } : null,
  }));
  const contributors = CONTRIBUTORS.map(([id, name, role, performer]) => ({
    id,
    name,
    role_category: role,
    performer,
  }));
  const releases = albums.map((album, index) => ({
    id: album.id.replace("syn-a", "syn-r"),
    album_id: album.id,
    title: album.title,
    year: album.year,
    catalog_stamp: `${album.label === "Meridian" ? "MER" : "CK"}-${101 + index}`,
  }));
  const credits = [];
  for (const [id, , role, , albumList] of CONTRIBUTORS) {
    for (const short of albumList.split(" ")) {
      credits.push({
        release_id: `syn-r${short.slice(1)}`,
        contributor_id: id,
        role_text: ROLE_TEXT[role],
        role_category: role,
        credit_scope: "release_credit",
      });
    }
  }
  credits.sort(
    (a, b) =>
      a.release_id.localeCompare(b.release_id) ||
      a.contributor_id - b.contributor_id,
  );
  return {
    schema_version: 1,
    provenance: {
      source:
        "Synthetic fixture — the Meridian Tapes universe, an entirely fictional catalog invented for this repository",
      license:
        "Fictional synthetic data authored in this repository; no external source, no real artists, releases, or Discogs identifiers",
      note: "Every act, contributor, record, and credit here is invented. Ids use reserved synthetic ranges. Sleeve art is generated geometry stamped SYNTHETIC. Never present this as real catalog data.",
      generated_by:
        "apps/web/scripts/build-rounds.mjs from scripts/universe-def.mjs (deterministic expansion)",
    },
    albums,
    contributors,
    releases,
    credits,
  };
}

// --- synthetic round derivation ---------------------------------------------
function indexUniverse(universe) {
  const albumById = new Map(universe.albums.map((a) => [a.id, a]));
  const contributorById = new Map(universe.contributors.map((c) => [c.id, c]));
  const releaseByAlbum = new Map(universe.releases.map((r) => [r.album_id, r]));
  const contributorsByAlbum = new Map();
  const albumsByContributor = new Map();
  for (const credit of universe.credits) {
    const release = universe.releases.find((r) => r.id === credit.release_id);
    const albumId = release.album_id;
    if (!contributorsByAlbum.has(albumId))
      contributorsByAlbum.set(albumId, new Set());
    contributorsByAlbum.get(albumId).add(credit.contributor_id);
    if (!albumsByContributor.has(credit.contributor_id))
      albumsByContributor.set(credit.contributor_id, new Set());
    albumsByContributor.get(credit.contributor_id).add(albumId);
  }
  return {
    albumById,
    contributorById,
    releaseByAlbum,
    contributorsByAlbum,
    albumsByContributor,
  };
}

const albumRef = (album) => ({
  id: album.id,
  title: album.title,
  year: album.year,
  act: album.act,
  art: album.art,
});
const contributorRef = (c) => ({
  id: c.id,
  name: c.name,
  role_category: c.role_category,
});

function isKin(idA, idB) {
  return KIN_PAIRS.some(
    ([x, y]) => (x === idA && y === idB) || (x === idB && y === idA),
  );
}

function initials(name) {
  return name
    .split(/\s+/)
    .map((part) => `${part[0]}.`)
    .join(" ");
}

function syntheticEvidence(universe, idx, contributorIds, albumIds) {
  const rows = [];
  for (const albumId of albumIds) {
    const release = idx.releaseByAlbum.get(albumId);
    for (const credit of universe.credits) {
      if (
        credit.release_id === release.id &&
        contributorIds.includes(credit.contributor_id)
      ) {
        rows.push({
          release_ref: release.id,
          release_title: release.title,
          contributor_id: credit.contributor_id,
          credited_as: idx.contributorById.get(credit.contributor_id).name,
          role_text: credit.role_text,
          credit_scope: credit.credit_scope,
        });
      }
    }
  }
  return rows;
}

function pickDistractors(idx, seed, excludedIds, endpointAlbumIds, count) {
  const invalid = [];
  for (const contributor of idx.contributorById.values()) {
    if (excludedIds.has(contributor.id)) continue;
    const albums = idx.albumsByContributor.get(contributor.id) ?? new Set();
    const onEvery = endpointAlbumIds.every((albumId) => albums.has(albumId));
    if (onEvery) continue; // would be a valid answer — never a distractor
    invalid.push(contributor);
  }
  // Prefer contributors credited on at least one endpoint (plausible), then
  // kin of the answers, then the rest — deterministically shuffled.
  const answerIds = [...excludedIds];
  const score = (c) => {
    const albums = idx.albumsByContributor.get(c.id) ?? new Set();
    const onOne = endpointAlbumIds.some((albumId) => albums.has(albumId));
    const kin = answerIds.some((id) => isKin(id, c.id));
    return (onOne ? 2 : 0) + (kin ? 1 : 0);
  };
  const shuffled = rng(seed).shuffle(invalid);
  shuffled.sort((a, b) => score(b) - score(a));
  return shuffled.slice(0, count);
}

function syntheticDifficulty(answers, distractors) {
  const nonPerformer = answers.some((a) => !a.performer);
  const kinPresent = answers.some((a) =>
    distractors.some((d) => isKin(a.id, d.id)),
  );
  if (nonPerformer || (kinPresent && answers.length > 1)) return "hard";
  if (kinPresent || answers.length > 1) return "medium";
  return "easy";
}

function deriveSyntheticOneHop(universe, idx) {
  const rounds = [];
  const albumIds = universe.albums.map((a) => a.id);
  for (let i = 0; i < albumIds.length; i += 1) {
    for (let j = i + 1; j < albumIds.length; j += 1) {
      const a = albumIds[i];
      const b = albumIds[j];
      const albumA = idx.albumById.get(a);
      const albumB = idx.albumById.get(b);
      if (albumA.act_id === albumB.act_id) continue; // same act: too easy/odd
      const shared = [...idx.contributorsByAlbum.get(a)].filter((id) =>
        idx.contributorsByAlbum.get(b).has(id),
      );
      if (shared.length < 1 || shared.length > 2) continue;
      const answers = shared.map((id) => idx.contributorById.get(id));
      const id = `syn-1h-${a.slice(-2)}${b.slice(-2)}`;
      const distractors = pickDistractors(idx, id, new Set(shared), [a, b], 4);
      if (distractors.length < 4) continue;
      const difficulty = syntheticDifficulty(answers, distractors);
      const answer = answers[0];
      rounds.push({
        id,
        pool: "synthetic-universe",
        kind: "one_hop",
        difficulty,
        endpoints: [albumRef(albumA), albumRef(albumB)],
        answer_set: answers.map(contributorRef),
        distractors: distractors.map(contributorRef),
        clues: [
          {
            kind: "years",
            text: `The records are from ${albumA.year} and ${albumB.year}.`,
          },
          {
            kind: "role",
            text: `The connecting credit is ${ROLE_TEXT[answer.role_category].toLowerCase()} work.`,
          },
          {
            kind: "initials",
            text: `Their initials are ${initials(answer.name)}`,
          },
          {
            kind: "credit_excerpt",
            text: `Liner note, ${albumA.title}: "${ROLE_TEXT[answer.role_category]} — ▮▮▮▮▮▮"`,
          },
          {
            kind: "eliminate",
            text: "Two names struck from the tray.",
            eliminate_ids: distractors.slice(0, 2).map((d) => d.id),
          },
        ],
        evidence: syntheticEvidence(universe, idx, shared, [a, b]),
        provenance_note:
          "Synthetic-universe round: a fictional catalog with generated sleeve art, clearly stamped SYNTHETIC.",
      });
    }
  }
  rounds.sort((x, y) => x.id.localeCompare(y.id));
  return capBalanced(rounds, CAPS.synOneHop);
}

function deriveSyntheticTwoHop(universe, idx) {
  const rounds = [];
  const albumIds = universe.albums.map((a) => a.id);
  for (let i = 0; i < albumIds.length; i += 1) {
    for (let j = i + 1; j < albumIds.length; j += 1) {
      const a = albumIds[i];
      const c = albumIds[j];
      const setA = idx.contributorsByAlbum.get(a);
      const setC = idx.contributorsByAlbum.get(c);
      if ([...setA].some((id) => setC.has(id))) continue; // direct link exists
      const validMiddles = albumIds.filter((m) => {
        if (m === a || m === c) return false;
        const setM = idx.contributorsByAlbum.get(m);
        const bridgeA = [...setA].filter((id) => setM.has(id));
        const bridgeC = [...setC].filter((id) => setM.has(id));
        return (
          bridgeA.length > 0 &&
          bridgeC.length > 0 &&
          bridgeA.some((x) => !bridgeC.includes(x))
        );
      });
      if (validMiddles.length !== 1) continue; // unique middle keeps it fair
      const m = validMiddles[0];
      const setM = idx.contributorsByAlbum.get(m);
      const bridgeA = [...setA].filter((id) => setM.has(id));
      const bridgeC = [...setC].filter(
        (id) => setM.has(id) && !bridgeA.includes(id),
      );
      if (bridgeC.length === 0) continue;
      const id = `syn-2h-${a.slice(-2)}${c.slice(-2)}`;
      const answers = [...new Set([...bridgeA, ...bridgeC])].map((x) =>
        idx.contributorById.get(x),
      );
      const distractors = pickDistractors(
        idx,
        id,
        new Set([...bridgeA, ...bridgeC]),
        [a, c],
        4,
      );
      if (distractors.length < 4) continue;
      const middleAlbum = idx.albumById.get(m);
      const middleDistractors = rng(`${id}-mid`)
        .shuffle(
          albumIds.filter(
            (x) => x !== a && x !== c && !validMiddles.includes(x),
          ),
        )
        .slice(0, 3)
        .map((x) => albumRef(idx.albumById.get(x)));
      rounds.push({
        id,
        pool: "synthetic-universe",
        kind: "two_hop",
        difficulty: syntheticDifficulty(answers, distractors),
        endpoints: [
          albumRef(idx.albumById.get(a)),
          albumRef(idx.albumById.get(c)),
        ],
        middle: {
          album: albumRef(middleAlbum),
          choices: rng(`${id}-order`).shuffle([
            albumRef(middleAlbum),
            ...middleDistractors,
          ]),
        },
        answer_set: answers.map(contributorRef),
        bridge_answer_sets: [
          bridgeA.map((x) => contributorRef(idx.contributorById.get(x))),
          bridgeC.map((x) => contributorRef(idx.contributorById.get(x))),
        ],
        distractors: distractors.map(contributorRef),
        clues: [
          {
            kind: "years",
            text: `The hidden middle record is from ${middleAlbum.year}.`,
          },
          {
            kind: "role",
            text: `One bridge is ${ROLE_TEXT[idx.contributorById.get(bridgeA[0]).role_category].toLowerCase()} work; the other is ${ROLE_TEXT[idx.contributorById.get(bridgeC[0]).role_category].toLowerCase()} work.`,
          },
          {
            kind: "initials",
            text: `Bridge initials: ${initials(idx.contributorById.get(bridgeA[0]).name)} and ${initials(idx.contributorById.get(bridgeC[0]).name)}`,
          },
          {
            kind: "credit_excerpt",
            text: `Liner note, ${middleAlbum.title}: two familiar names appear in the credits — ▮▮▮▮▮▮ and ▮▮▮▮▮▮.`,
          },
          {
            kind: "eliminate",
            text: "Two names struck from the tray.",
            eliminate_ids: distractors.slice(0, 2).map((d) => d.id),
          },
        ],
        evidence: syntheticEvidence(
          universe,
          idx,
          [...new Set([...bridgeA, ...bridgeC])],
          [a, m, c],
        ),
        provenance_note:
          "Synthetic-universe round: a fictional catalog with generated sleeve art, clearly stamped SYNTHETIC.",
      });
    }
  }
  rounds.sort((x, y) => x.id.localeCompare(y.id));
  return capBalanced(rounds, CAPS.synTwoHop);
}

/** Deterministically cap a sorted round list while keeping difficulty mix. */
function capBalanced(rounds, cap) {
  if (rounds.length <= cap) return rounds;
  const byDifficulty = { easy: [], medium: [], hard: [] };
  for (const round of rounds) byDifficulty[round.difficulty].push(round);
  const kept = [];
  const order = ["easy", "medium", "hard"];
  let cursor = 0;
  while (kept.length < cap) {
    const bucket = byDifficulty[order[cursor % 3]];
    if (bucket.length > 0) kept.push(bucket.shift());
    cursor += 1;
    if (order.every((d) => byDifficulty[d].length === 0)) break;
  }
  kept.sort((x, y) => x.id.localeCompare(y.id));
  return kept;
}

// --- real-records pool (derived from the curated ADR 0012 demo data) --------
const NON_PERFORMER_ROLE =
  /(produc|engineer|master|mix|lacquer|design|photo|artwork|liner|management|coordinat)/i;

function realRoleCategory(roleText, scope) {
  const text = (roleText ?? "").toLowerCase();
  if (text.includes("produc")) return "producer";
  if (text.includes("master")) return "mastering";
  if (text.includes("mix")) return "mixing";
  if (text.includes("engineer")) return "engineer";
  if (text.includes("arrang")) return "arrangement";
  if (text.includes("guitar")) return "guitar";
  if (text.includes("bass")) return "bass";
  if (text.includes("drum")) return "drums";
  if (text.includes("sax")) return "sax";
  if (text.includes("vocal")) return "vocals";
  if (scope === "release_artist" || scope === "track_artist") return "artist";
  return "credit";
}

function deriveRealRounds(challenge) {
  const releaseById = new Map(challenge.releases.map((r) => [r.release_id, r]));
  const nameById = new Map(challenge.artists.map((a) => [a.artist_id, a.name]));
  const linkedByRelease = new Map();
  for (const release of challenge.releases) {
    const ids = new Map();
    for (const credit of release.credits) {
      if (!credit.is_linked || !credit.playable_identity) continue;
      if (credit.artist_id === null) continue;
      if (PLACEHOLDER_ARTIST_IDS.has(credit.artist_id)) continue;
      if (!ids.has(credit.artist_id)) ids.set(credit.artist_id, []);
      ids.get(credit.artist_id).push(credit);
    }
    linkedByRelease.set(release.release_id, ids);
  }
  const releaseIds = [...releaseById.keys()].sort((a, b) => a - b);
  const rounds = [];
  for (let i = 0; i < releaseIds.length; i += 1) {
    for (let j = i + 1; j < releaseIds.length; j += 1) {
      const ra = releaseById.get(releaseIds[i]);
      const rb = releaseById.get(releaseIds[j]);
      const idsA = linkedByRelease.get(ra.release_id);
      const idsB = linkedByRelease.get(rb.release_id);
      const shared = [...idsA.keys()].filter((id) => idsB.has(id));
      if (shared.length < 1 || shared.length > 3) continue;
      const id = `real-1h-${ra.release_id}-${rb.release_id}`;
      const answerRefs = shared.map((artistId) => ({
        id: artistId,
        name:
          nameById.get(artistId) ??
          idsA.get(artistId)[0].name ??
          idsB.get(artistId)[0].name,
        role_category: realRoleCategory(
          idsA.get(artistId)[0].role_text,
          idsA.get(artistId)[0].credit_scope,
        ),
      }));
      const distractorPool = [];
      const seen = new Set(shared);
      for (const [source, other] of [
        [idsA, idsB],
        [idsB, idsA],
      ]) {
        for (const [artistId, credits] of source) {
          if (seen.has(artistId) || other.has(artistId)) continue;
          seen.add(artistId);
          distractorPool.push({
            id: artistId,
            name: nameById.get(artistId) ?? credits[0].name,
            role_category: realRoleCategory(
              credits[0].role_text,
              credits[0].credit_scope,
            ),
          });
        }
      }
      const distractors = rng(id).shuffle(distractorPool).slice(0, 4);
      if (distractors.length < 4) continue;
      const sharedScopes = shared.flatMap((artistId) => [
        ...idsA.get(artistId).map((c) => c),
        ...idsB.get(artistId).map((c) => c),
      ]);
      const allNonPerformer = sharedScopes.every(
        (c) =>
          c.credit_scope.endsWith("_credit") &&
          NON_PERFORMER_ROLE.test(c.role_text ?? ""),
      );
      const anyCoBilled = shared.some(
        (artistId) =>
          idsA.get(artistId).some((c) => c.credit_scope === "release_artist") &&
          idsB.get(artistId).some((c) => c.credit_scope === "release_artist"),
      );
      const difficulty = anyCoBilled
        ? "easy"
        : allNonPerformer
          ? "hard"
          : "medium";
      const toRef = (release) => ({
        id: `real-rel-${release.release_id}`,
        title: release.title,
        year: release.released ? Number(release.released.slice(0, 4)) : null,
        act:
          release.credits
            .filter((c) => c.credit_scope === "release_artist")
            .map((c) => c.anv ?? c.name)
            .slice(0, 2)
            .join(" & ") || null,
        art:
          Array.isArray(release.images) &&
          release.images.length > 0 &&
          release.images[0].uri150?.startsWith("https://i.discogs.com/")
            ? {
                kind: "hotlink",
                uri150: release.images[0].uri150,
                uri: release.images[0].uri,
              }
            : null,
      });
      const primary = answerRefs[0];
      const evidence = shared.flatMap((artistId) =>
        [ra, rb].flatMap((release) =>
          linkedByRelease
            .get(release.release_id)
            .get(artistId)
            .slice(0, 2)
            .map((credit) => ({
              release_ref: `real-rel-${release.release_id}`,
              release_title: release.title,
              contributor_id: artistId,
              credited_as: credit.anv ?? credit.name,
              role_text: credit.role_text ?? "Release artist",
              credit_scope: credit.credit_scope,
            })),
        ),
      );
      rounds.push({
        id,
        pool: "real-records",
        kind: "one_hop",
        difficulty,
        endpoints: [toRef(ra), toRef(rb)],
        answer_set: answerRefs,
        distractors,
        clues: [
          {
            kind: "years",
            text: `The records are from ${ra.released?.slice(0, 4) ?? "?"} and ${rb.released?.slice(0, 4) ?? "?"}.`,
          },
          {
            kind: "role",
            text: `The connecting credit is ${primary.role_category} work.`,
          },
          {
            kind: "initials",
            text: `Their initials are ${initials(primary.name)}`,
          },
          {
            kind: "credit_excerpt",
            text: `Liner note, ${ra.title}: "${idsA.get(primary.id)[0].role_text ?? "Release artist"} — ▮▮▮▮▮▮"`,
          },
          {
            kind: "eliminate",
            text: "Two names struck from the tray.",
            eliminate_ids: distractors.slice(0, 2).map((d) => d.id),
          },
        ],
        evidence,
        provenance_note:
          "Real records: derived from the curated Discogs demo dataset (ADR 0012). Cover art is hotlinked from Discogs and remains presentational, not evidence.",
      });
    }
  }
  rounds.sort((x, y) => x.id.localeCompare(y.id));
  return rounds.slice(0, CAPS.real);
}

// --- validation --------------------------------------------------------------
function fail(problems, message) {
  problems.push(message);
}

function validate(universe, rounds) {
  const problems = [];
  const idx = indexUniverse(universe);

  // Universe referential integrity.
  for (const credit of universe.credits) {
    if (!universe.releases.some((r) => r.id === credit.release_id))
      fail(problems, `credit references unknown release ${credit.release_id}`);
    if (!idx.contributorById.has(credit.contributor_id))
      fail(
        problems,
        `credit references unknown contributor ${credit.contributor_id}`,
      );
  }
  for (const release of universe.releases) {
    if (!idx.albumById.has(release.album_id))
      fail(problems, `release ${release.id} references unknown album`);
  }
  for (const album of universe.albums) {
    const contributors = idx.contributorsByAlbum.get(album.id);
    if (!contributors || contributors.size < 2)
      fail(problems, `album ${album.id} has fewer than 2 credits`);
  }

  // Round correctness.
  const synthetic = rounds.rounds.filter(
    (r) => r.pool === "synthetic-universe",
  );
  const real = rounds.rounds.filter((r) => r.pool === "real-records");
  const ids = new Set();
  for (const round of rounds.rounds) {
    if (ids.has(round.id)) fail(problems, `duplicate round id ${round.id}`);
    ids.add(round.id);
    if (round.answer_set.length === 0)
      fail(problems, `round ${round.id} has an empty answer set`);
    const answerIds = new Set(round.answer_set.map((a) => a.id));
    for (const d of round.distractors) {
      if (answerIds.has(d.id))
        fail(problems, `round ${round.id} distractor ${d.id} is an answer`);
    }
    if (round.evidence.length === 0)
      fail(problems, `round ${round.id} has no evidence rows`);
    for (const answer of round.answer_set) {
      if (!round.evidence.some((row) => row.contributor_id === answer.id))
        fail(problems, `round ${round.id} answer ${answer.id} lacks evidence`);
    }
    if (round.kind === "two_hop") {
      if (!round.middle || !round.bridge_answer_sets)
        fail(problems, `two-hop round ${round.id} missing middle/bridges`);
      else if (
        !round.middle.choices.some((c) => c.id === round.middle.album.id)
      )
        fail(problems, `round ${round.id} middle answer missing from choices`);
    }
  }

  // Synthetic distractors must not satisfy the connection.
  for (const round of synthetic) {
    const endpointAlbums = round.endpoints.map((e) => e.id);
    for (const d of round.distractors) {
      const albums = idx.albumsByContributor.get(d.id) ?? new Set();
      if (endpointAlbums.every((albumId) => albums.has(albumId)))
        fail(
          problems,
          `round ${round.id} distractor ${d.id} links the endpoints`,
        );
    }
    if (round.kind === "two_hop") {
      const [a, c] = endpointAlbums;
      for (const choice of round.middle.choices) {
        if (choice.id === round.middle.album.id) continue;
        const setM = idx.contributorsByAlbum.get(choice.id);
        const setA = idx.contributorsByAlbum.get(a);
        const setC = idx.contributorsByAlbum.get(c);
        const bridgeA = [...setA].filter((x) => setM.has(x));
        const bridgeC = [...setC].filter((x) => setM.has(x));
        if (
          bridgeA.length > 0 &&
          bridgeC.length > 0 &&
          bridgeA.some((x) => !bridgeC.includes(x))
        )
          fail(
            problems,
            `round ${round.id} middle distractor ${choice.id} is a valid middle`,
          );
      }
    }
    for (const endpoint of round.endpoints) {
      if (!endpoint.id.startsWith("syn-"))
        fail(
          problems,
          `synthetic round ${round.id} has non-synthetic endpoint`,
        );
    }
  }

  // Real rounds: hotlink-only art from Discogs, playable ids only.
  for (const round of real) {
    for (const endpoint of round.endpoints) {
      if (endpoint.art && endpoint.art.kind === "hotlink") {
        for (const uri of [endpoint.art.uri150, endpoint.art.uri]) {
          if (!uri.startsWith("https://i.discogs.com/"))
            fail(problems, `round ${round.id} art is not a Discogs hotlink`);
        }
      }
    }
    for (const ref of [...round.answer_set, ...round.distractors]) {
      if (PLACEHOLDER_ARTIST_IDS.has(ref.id))
        fail(problems, `round ${round.id} uses placeholder artist ${ref.id}`);
    }
  }

  // Pool sizes.
  if (synthetic.length < MIN.synthetic)
    fail(
      problems,
      `synthetic pool ${synthetic.length} below minimum ${MIN.synthetic}`,
    );
  if (synthetic.filter((r) => r.kind === "two_hop").length < MIN.synTwoHop)
    fail(problems, `two-hop pool below minimum ${MIN.synTwoHop}`);
  if (real.length < MIN.real)
    fail(problems, `real pool ${real.length} below minimum ${MIN.real}`);
  for (const difficulty of ["easy", "medium", "hard"]) {
    if (!synthetic.some((r) => r.difficulty === difficulty))
      fail(problems, `no synthetic round with difficulty ${difficulty}`);
  }

  // Forbidden content in the serialized artifacts.
  for (const [label, artifact] of [
    ["universe", universe],
    ["rounds", rounds],
  ]) {
    const lowered = JSON.stringify(artifact).toLowerCase();
    for (const substring of FORBIDDEN_SUBSTRINGS) {
      if (lowered.includes(substring.toLowerCase()))
        fail(problems, `${label} contains forbidden substring ${substring}`);
    }
    for (const phrase of FORBIDDEN_PHRASES) {
      if (lowered.includes(phrase))
        fail(problems, `${label} contains forbidden phrase "${phrase}"`);
    }
  }

  // Provenance must self-identify as synthetic when read in isolation.
  for (const field of ["source", "license", "note"]) {
    const value = universe.provenance[field].toLowerCase();
    if (!value.includes("synthetic") && !value.includes("fiction"))
      fail(
        problems,
        `universe provenance.${field} does not self-identify as synthetic`,
      );
  }
  return problems;
}

// --- main --------------------------------------------------------------------
function buildAll() {
  const universe = buildUniverse();
  const idx = indexUniverse(universe);
  const challenge = JSON.parse(readFileSync(CHALLENGE_V1_PATH, "utf8"));
  const rounds = {
    schema_version: 1,
    provenance: {
      source:
        "Derived game rounds: a synthetic fictional universe pool plus a real-records pool derived from the curated Discogs demo dataset (public data, ADR 0012)",
      license:
        "Synthetic pool is fictional data authored in this repository; real pool derives from the committed challenge.v1.json under its own provenance",
      note: "Rounds are regenerated deterministically by apps/web/scripts/build-rounds.mjs; every distractor is validated to NOT satisfy the connection. Pools are badged in the UI. A shared credit documents participation on a recording, never influence.",
      generated_by:
        "apps/web/scripts/build-rounds.mjs (deterministic derivation)",
    },
    rounds: [
      ...deriveSyntheticOneHop(universe, idx),
      ...deriveSyntheticTwoHop(universe, idx),
      ...deriveRealRounds(challenge),
    ],
  };
  return { universe, rounds };
}

function main() {
  const mode = process.argv.includes("--write") ? "write" : "check";
  const { universe, rounds } = buildAll();
  const problems = validate(universe, rounds);
  if (problems.length > 0) {
    console.error(`build-rounds: ${problems.length} validation problem(s):`);
    for (const problem of problems) console.error(`  - ${problem}`);
    process.exit(1);
  }
  if (mode === "write") {
    mkdirSync(dirname(UNIVERSE_PATH), { recursive: true });
    writeFileSync(UNIVERSE_PATH, `${JSON.stringify(universe, null, 2)}\n`);
    writeFileSync(ROUNDS_PATH, `${JSON.stringify(rounds, null, 2)}\n`);
    const synthetic = rounds.rounds.filter(
      (r) => r.pool === "synthetic-universe",
    );
    console.log(
      `build-rounds: wrote ${universe.albums.length} albums, ${universe.credits.length} credits, ` +
        `${synthetic.length} synthetic rounds (${synthetic.filter((r) => r.kind === "two_hop").length} two-hop), ` +
        `${rounds.rounds.length - synthetic.length} real rounds`,
    );
    return;
  }
  // check: semantic comparison against committed artifacts (formatting-agnostic
  // so prettier can own whitespace).
  for (const [path, generated] of [
    [UNIVERSE_PATH, universe],
    [ROUNDS_PATH, rounds],
  ]) {
    let committed;
    try {
      committed = JSON.parse(readFileSync(path, "utf8"));
    } catch {
      console.error(
        `build-rounds: missing or unreadable artifact ${path}; run with --write`,
      );
      process.exit(1);
    }
    if (JSON.stringify(committed) !== JSON.stringify(generated)) {
      console.error(
        `build-rounds: ${path} drifted from the generated output; run \`node scripts/build-rounds.mjs --write\` and commit`,
      );
      process.exit(1);
    }
  }
  console.log("build-rounds: artifacts validated, no drift");
}

main();
