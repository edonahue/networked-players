import type { APIRoute } from "astro";
import type { ChallengeV2 } from "../data/challenge";
import challengeData from "../../public/data/challenge.v2.json";
import { connectedCatalogAlbums } from "../data/connectedAlbums";

export const prerender = true;

const escapeXml = (value: string) =>
  value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");

const challenge = challengeData as ChallengeV2;
const connectedAlbums = connectedCatalogAlbums(challenge);
const albumPaths = connectedAlbums.map((album) => `/albums/${album.id}/`);
const explorePaths = connectedAlbums.map((album) => `/explore/${album.id}/`);

import cohortManifest from "../../public/data/cohorts/index.json";

const cohortPaths = cohortManifest.cohorts.map(
  (cohort: { cohort_id: string }) => `/cohorts/${cohort.cohort_id}/`,
);

import type { ContributorIndex } from "../data/contributors";
import contributorIndexData from "../../public/data/contributors/index.v1.json";

const contributorIndex = contributorIndexData as ContributorIndex;
const contributorPaths = contributorIndex.contributors.map(
  (contributor) => `/contributors/${contributor.artist_id}/`,
);

const paths = [
  "/",
  "/play/",
  "/play/connection/",
  "/play/daily/",
  "/play/daily/archive/",
  "/play/routes/",
  "/play/connect/",
  "/albums/",
  "/explore/",
  "/about/",
  "/demo/",
  "/cohorts/",
  "/contributors/",
  ...cohortPaths,
  ...albumPaths,
  ...explorePaths,
  ...contributorPaths,
];

export const GET: APIRoute = async ({ site }) => {
  if (!site)
    return new Response("Site URL is not configured.", { status: 500 });

  const urls = paths
    .map(
      (path) =>
        `<url><loc>${escapeXml(new URL(path, site).toString())}</loc></url>`,
    )
    .join("");

  return new Response(
    `<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${urls}</urlset>`,
    { headers: { "Content-Type": "application/xml; charset=utf-8" } },
  );
};
