// The album grid, Explore grid, per-album static paths, and sitemap all
// need the same set: catalog albums that are actually reachable through
// challenge.v2.json's documented paths (ADR 0058 Slice 8 dedup -- this
// logic was independently copied five times before this file existed).

import type { AlbumV2, ChallengeV2 } from "./challenge";

export function connectedCatalogAlbums(challenge: ChallengeV2): AlbumV2[] {
  const connectedAlbumIds = new Set(
    challenge.paths.flatMap((p) => [p.from_album_id, p.to_album_id]),
  );
  return challenge.albums.filter((album) => connectedAlbumIds.has(album.id));
}
