// Build-time companion to the search index (public/data/search/index.v1.json).
// The index lists players by name only; to send a chosen player to Explore
// centred on them (the same `/explore/<album>/?center=<artist_id>` form the
// player's own page uses) the header search needs one record to open Explore
// on, plus a short "credited for" line. This is a few KB (players plus record years) derived from the
// contributor index at build time, fetched only after the visitor engages
// search -- never the 780 KB contributor index itself.

import type { APIRoute } from "astro";
import {
  ROLE_CATEGORY_LABEL,
  type ContributorIndex,
} from "../../data/contributors";
import type { ChallengeV2 } from "../../data/challenge";
import contributorIndexData from "../../../public/data/contributors/index.v1.json";
import challengeData from "../../../public/data/challenge.v3.json";

export const prerender = true;

/** Credited-for labels shown at most this many per player. */
const MAX_ROLES = 3;

export const GET: APIRoute = () => {
  const index = contributorIndexData as ContributorIndex;
  const players: Record<string, { album: string; roles: string[] }> = {};
  for (const c of index.contributors) {
    if (c.albums.length === 0) continue;
    players[String(c.artist_id)] = {
      album: c.albums[0],
      roles: c.role_categories
        .map((r) => ROLE_CATEGORY_LABEL[r])
        .filter((l): l is string => Boolean(l) && l !== "Unclassified")
        .slice(0, MAX_ROLES),
    };
  }
  const years: Record<string, number> = {};
  for (const a of (challengeData as ChallengeV2).albums) {
    if (a.year) years[a.id] = a.year;
  }
  return new Response(JSON.stringify({ players, years }), {
    headers: { "Content-Type": "application/json" },
  });
};
