// Card text and alt text per page type, shared by the endpoints and pages so
// the og:image:alt always describes the same strings the image shows.
import type { AlbumV2 } from "../data/challenge";
import type { CardInput } from "./card";

export const albumOgPath = (id: string) => `/og/albums/${id}.png`;

export function albumCard(album: AlbumV2): CardInput {
  return {
    kicker: "Record",
    title: album.title,
    subtitle: album.artist,
    meta: album.year ? String(album.year) : undefined,
  };
}

export const albumOgAlt = (album: AlbumV2) =>
  `${album.title} by ${album.artist}${album.year ? ` (${album.year})` : ""} — Networked Players`;
