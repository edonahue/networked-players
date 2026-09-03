// The album shelf, the Explore grid, and the homepage all need to know which
// catalog albums appear as an endpoint of at least one challenge.v3.json
// documented path (ADR 0058 Slice 8 dedup -- this logic was independently
// copied five times before this file existed). Since ADR 0067 (shelf) and
// the Phase 0 expansion slice (Explore grid, homepage) none of those
// surfaces FILTER by this set any more: the album universe is the catalog
// (`challenge.albums`, resolved from `catalog/albums.v1.json` and
// cross-checked by `catalog_version`), and `connectedAlbumIds` only decides
// which albums get the honest "No documented path yet" badge.
//
// Why the filter went away: the set used to be treated as "the album
// universe," but which albums it contained depended on the challenge
// builder's candidate-pair ORDER and `max_paths` -- the committed artifact
// at 179 albums had every one of its 300 paths start from the same two
// albums and left 7 albums out, not because they were disconnected but
// because the iterator never reached them. A universe that shrinks or
// shifts with a build parameter is not a universe.

import type { AlbumV2, ChallengeV2 } from "./challenge";

export function connectedAlbumIds(challenge: ChallengeV2): Set<string> {
  return new Set(
    challenge.paths.flatMap((p) => [p.from_album_id, p.to_album_id]),
  );
}

/** Kept for callers that need the path-endpoint subset explicitly (tests,
 * diagnostics). No page derives its album grid from this any more. */
export function connectedCatalogAlbums(challenge: ChallengeV2): AlbumV2[] {
  const connectedIds = connectedAlbumIds(challenge);
  return challenge.albums.filter((album) => connectedIds.has(album.id));
}
