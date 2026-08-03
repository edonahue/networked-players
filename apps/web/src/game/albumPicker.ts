// Client-side substring filter over the pathfinding graph's own album scope
// (ADR 0051) -- no live search API, per apps/web/AGENTS.md's static-first
// rule. Pure filtering logic, unit-testable without a DOM.

export interface PickableAlbum {
  id: string;
  title: string;
  artist: string;
  artist_id: number;
  year: number | null;
}

/** Case-insensitive substring match against title or artist, capped at
 * `limit` results. An empty query returns no results (the picker shows
 * nothing until the visitor starts typing, rather than a long unfiltered
 * list). */
export function filterAlbums(
  albums: PickableAlbum[],
  query: string,
  limit = 8,
): PickableAlbum[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [];
  const matches: PickableAlbum[] = [];
  for (const album of albums) {
    if (
      album.title.toLowerCase().includes(needle) ||
      album.artist.toLowerCase().includes(needle)
    ) {
      matches.push(album);
      if (matches.length >= limit) break;
    }
  }
  return matches;
}
