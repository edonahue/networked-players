// The Explore grid, per-album static paths, and sitemap all need the same
// set: catalog albums that are actually reachable through
// challenge.v2.json's documented paths (ADR 0058 Slice 8 dedup -- this
// logic was independently copied five times before this file existed). The
// album shelf (/albums/) itself stopped using this filter as of ADR 0067 --
// it shows the full catalog and marks unconnected albums honestly instead
// of hiding them -- but `connectedAlbumIds` is exported so that page can
// still label which albums are which.

import type { AlbumV2, ChallengeV2 } from "./challenge";

export function connectedAlbumIds(challenge: ChallengeV2): Set<string> {
  return new Set(
    challenge.paths.flatMap((p) => [p.from_album_id, p.to_album_id]),
  );
}

export function connectedCatalogAlbums(challenge: ChallengeV2): AlbumV2[] {
  const connectedIds = connectedAlbumIds(challenge);
  return challenge.albums.filter((album) => connectedIds.has(album.id));
}
