// Types for the public album-hop-distances artifact
// (apps/web/public/data/contributors/album-hop-distances.v1.json,
// data/contracts/album-hop-distances-v1.md, ADR 0048 addendum).
//
// A companion to contributors.ts's ContributorIndex, deliberately a
// separate artifact rather than a field on it -- that index is
// runtime-fetched by already-loaded client JS and validated as an exact
// key set, so neither changing albums[]'s element type nor adding a new
// required key to it is a safe in-place change.

/** `hop_distance` is the minimum number of documented credit-hops from
 * this artist's nearest occurrence in any path/round to this endpoint
 * album -- `0` means directly adjacent, not "0 because they appear
 * somewhere in the path". Frontend copy must surface this whenever
 * `hop_distance !== 0` (hop_distance 1 is a real, if close, chain -- not
 * the endpoint's own credit). */
export interface AlbumHopDistanceEntry {
  artist_id: number;
  album_id: string;
  hop_distance: number;
}

export interface AlbumHopDistances {
  schema_version: number;
  catalog_version: string;
  album_hop_distances_version: string;
  generated_at: string;
  source: string;
  license: string;
  entries: AlbumHopDistanceEntry[];
}

/** artist_id -> that artist's own entries (already sorted by
 * (hop_distance, album_id) within each artist_id group, since the
 * published artifact is sorted by (artist_id, hop_distance, album_id)
 * overall). */
export function albumHopDistancesByArtist(
  distances: AlbumHopDistances,
): Map<number, AlbumHopDistanceEntry[]> {
  const byArtist = new Map<number, AlbumHopDistanceEntry[]>();
  for (const entry of distances.entries) {
    const existing = byArtist.get(entry.artist_id);
    if (existing) {
      existing.push(entry);
    } else {
      byArtist.set(entry.artist_id, [entry]);
    }
  }
  return byArtist;
}
