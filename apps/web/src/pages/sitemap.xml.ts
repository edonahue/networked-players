import type { APIRoute } from "astro";
import type { ChallengeV2 } from "../data/challenge";
import challengeData from "../../public/data/challenge.v2.json";

export const prerender = true;

const escapeXml = (value: string) =>
  value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");

const challenge = challengeData as ChallengeV2;
const connectedAlbumIds = new Set(
  challenge.paths.flatMap((p) => [p.from_album_id, p.to_album_id]),
);
const albumPaths = challenge.albums
  .filter((album) => connectedAlbumIds.has(album.id))
  .map((album) => `/play/${album.id}/`);

const paths = ["/", "/about/", "/demo/", ...albumPaths];

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
