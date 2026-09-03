// Build-time-generated /llms.txt (crawler/agent context file, referenced
// from robots.txt). Was a static public/llms.txt describing a much earlier
// state of the project -- "no public API or full public catalog," the
// album experience "still uses a small, versioned, synthetic static
// dataset until a real cohort completes human review" -- all false since
// the real, CC0-dump-derived catalog shipped. Generated the same way
// sitemap.xml.ts is, so its counts can never go stale the way the old
// static file did: catalogStats is the same build-time derivation
// about.astro uses.

import type { APIRoute } from "astro";
import { catalogStats } from "../data/catalogStats";
import site from "../data/site.json";

export const prerender = true;

export const GET: APIRoute = async ({ site: siteUrl }) => {
  const base = siteUrl ? siteUrl.toString().replace(/\/$/, "") : "";
  const {
    studioAlbumCount,
    artistCount,
    documentedConnectionCount,
    oneHopRoundCount,
    twoHopRoundCount,
  } = catalogStats;

  const body = `# Networked Players

> ${site.description}

Networked Players (networked-players.com) is an evidence-first music-credit graph and game by Erich Donahue. The core idea: connect artists through **documented performance** (who played or sang on which recording), and present a path between two artists where every hop is backed by release-level evidence and provenance. It deliberately does **not** infer artistic influence, friendship, or lineage -- a documented performance credit proves participation, nothing more.

## Current state (honest)

The album grid, evidence viewer, and every game mode run on a real, Discogs monthly-dump-derived catalog (CC0-licensed): ${studioAlbumCount} studio albums, ${artistCount} artists, ${documentedConnectionCount} documented performance paths between albums. Connection Guesser (${oneHopRoundCount} one-hop and ${twoHopRoundCount} two-hop rounds, plus a frozen Connection of the Day schedule), Connect Two Records (search any two catalog albums for a documented route through their credited contributors, with role-restricted modes), Record Routes (guess how many documented-credit hops connect two records), and Explore (an open-ended, bounded network view of the performers documented around one album) all draw from this same catalog and its evidence. A separate archived demo at /demo/ runs on a small, curated, API-sourced Discogs subset predating both the dump pipeline and the performer-only graph model -- it is not the main catalog and is not part of the current site.

## Data & rights stance

- Publishable catalog facts derive from CC0 Discogs monthly data dumps, always carried with provenance (snapshot date, source URL, parser/schema versions, original role text).
- Private collection membership is never published. Raw Discogs API responses, images, marketplace, and pricing data are restricted and are not republished.
- Cover art is hotlinked directly from Discogs' own CDN, never downloaded or rehosted.

## Site

- Home: ${base}/
- About: ${base}/about/
- Albums: ${base}/albums/
- Explore: ${base}/explore/
- Contributors: ${base}/contributors/
- Play: ${base}/play/
- Legacy demo: ${base}/demo/
- Repository: ${site.repositoryUrl}
- Sitemap: ${base}/sitemap.xml

## Author

- Erich Donahue -- ${site.authorUrl}
- GitHub: https://github.com/edonahue
`;

  return new Response(body, {
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
};
