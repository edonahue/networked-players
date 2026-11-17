// schema.org JSON-LD builders for record and player pages. Built only from
// data the pages already load; never includes Discogs image URLs.

import type { AlbumV2 } from "./challenge";

export const SITE_ORIGIN = "https://networked-players.com";

/** Serialise for an inline <script type="application/ld+json">. JSON.stringify
 * handles quoting; `<` is escaped so no string value can close the script tag
 * (or open a comment), and U+2028/2029 are escaped for older parsers. */
export function jsonLdScript(data: unknown): string {
  return JSON.stringify(data)
    .replaceAll("<", "\\u003c")
    .replaceAll(" ", "\\u2028")
    .replaceAll(" ", "\\u2029");
}

export function musicAlbumJsonLd(album: AlbumV2, artistPageId?: number) {
  return {
    "@context": "https://schema.org",
    "@type": "MusicAlbum",
    name: album.title,
    url: `${SITE_ORIGIN}/albums/${album.id}/`,
    byArtist: {
      "@type": "MusicGroup",
      name: album.artist,
      ...(artistPageId !== undefined
        ? { url: `${SITE_ORIGIN}/contributors/${artistPageId}/` }
        : {}),
    },
    ...(album.year ? { datePublished: String(album.year) } : {}),
  };
}

export function personJsonLd(artistId: number, name: string) {
  return {
    "@context": "https://schema.org",
    "@type": "Person",
    name,
    url: `${SITE_ORIGIN}/contributors/${artistId}/`,
  };
}
