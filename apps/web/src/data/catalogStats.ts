// Real, build-time-derived counts describing the current catalog and game
// pools -- used anywhere copy needs to state a number (about.astro,
// llms.txt.ts). Extracted after the same hardcoded "140 studio albums, 250
// artists, 300 documented connections" numbers were found stale in BOTH
// about.json and public/llms.txt following the Phase 7 catalog expansion
// (140 -> 179 albums): one derivation, reused, instead of two copies that
// can drift independently again.

import type { ChallengeV2 } from "./challenge";
import challengeData from "../../public/data/challenge.v3.json";
import dailyManifestData from "../../public/data/game/daily-manifest.v1.json";

const challenge = challengeData as ChallengeV2;
const dailyManifest = dailyManifestData as {
  generations: { rounds_url: string }[];
};

// The round counts come from the CURRENT daily-manifest generation's own
// rounds pool, not a hardcoded file path -- that pool's identity changes at
// every ADR 0066 cutover (gen-1 -> gen-2 -> ...), so resolving "the newest
// generation" here is the only way this stays accurate past the next one.
// `import.meta.glob` (not a runtime fs read) because Astro/Vite resolves
// relative paths against the SOURCE file at build time; a runtime
// `readFileSync` next to `import.meta.url` breaks once bundled, since the
// emitted chunk lives somewhere else entirely.
const roundsFiles = import.meta.glob<{ rounds: { kind: string }[] }>(
  "../../public/data/game/{rounds.v1,generations/*/rounds}.json",
  { eager: true, import: "default" },
);
const newestGeneration = dailyManifest.generations.at(-1);
if (!newestGeneration) {
  throw new Error("daily-manifest.v1.json has no generations");
}
const roundsFileKey = `../../public${newestGeneration.rounds_url}`;
const currentRounds = roundsFiles[roundsFileKey];
if (!currentRounds) {
  throw new Error(
    `newest generation's rounds_url (${newestGeneration.rounds_url}) matched no globbed file`,
  );
}
const oneHopRoundCount = currentRounds.rounds.filter(
  (round) => round.kind === "one_hop",
).length;
const twoHopRoundCount = currentRounds.rounds.filter(
  (round) => round.kind === "two_hop",
).length;
// A real published pool always has both kinds -- zero of either means the
// `kind` field name/values assumption above no longer matches the artifact,
// which should fail the build loudly, not publish "0 one-hop... rounds."
if (oneHopRoundCount === 0 || twoHopRoundCount === 0) {
  throw new Error(
    `expected both round kinds present in ${newestGeneration.rounds_url}, got ` +
      `${oneHopRoundCount} one_hop / ${twoHopRoundCount} two_hop`,
  );
}

export const catalogStats = {
  studioAlbumCount: challenge.albums.length,
  artistCount: challenge.artists.length,
  documentedConnectionCount: challenge.paths.length,
  oneHopRoundCount,
  twoHopRoundCount,
};
