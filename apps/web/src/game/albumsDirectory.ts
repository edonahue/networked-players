// Album shelf (PR G): client-side search and sort over the album grid at
// /albums/ -- no fetch, unlike contributorsDirectory.ts's directory, since
// every album is already server-rendered on this page (179 albums is small
// enough to browse in full, unlike the 521-contributor index that needs a
// search-preview cap). Wiring hides/reorders the ALREADY-RENDERED
// <AlbumCard> elements via `hidden` and CSS `order` rather than
// re-implementing card markup in JS, so the no-JS baseline (every album,
// server-sorted by title) stays a real, working fallback.

export interface DirectoryAlbum {
  id: string;
  title: string;
  artist: string;
  year: number | null;
}

export type AlbumSort = "title" | "artist" | "year-desc" | "year-asc";

function byTitle(a: DirectoryAlbum, b: DirectoryAlbum): number {
  return a.title.localeCompare(b.title) || a.artist.localeCompare(b.artist);
}

function byArtist(a: DirectoryAlbum, b: DirectoryAlbum): number {
  return a.artist.localeCompare(b.artist) || a.title.localeCompare(b.title);
}

// Albums with no known year (year: null) sort last regardless of direction --
// an unknown year is neither "newest" nor "oldest," so it shouldn't jump to
// the opposite end just because the sort direction flipped.
function byYearDesc(a: DirectoryAlbum, b: DirectoryAlbum): number {
  if (a.year === null && b.year === null) return byTitle(a, b);
  if (a.year === null) return 1;
  if (b.year === null) return -1;
  return b.year - a.year || byTitle(a, b);
}

function byYearAsc(a: DirectoryAlbum, b: DirectoryAlbum): number {
  if (a.year === null && b.year === null) return byTitle(a, b);
  if (a.year === null) return 1;
  if (b.year === null) return -1;
  return a.year - b.year || byTitle(a, b);
}

const COMPARATORS: Record<
  AlbumSort,
  (a: DirectoryAlbum, b: DirectoryAlbum) => number
> = {
  title: byTitle,
  artist: byArtist,
  "year-desc": byYearDesc,
  "year-asc": byYearAsc,
};

export const ALBUM_SORT_OPTIONS: { value: AlbumSort; label: string }[] = [
  { value: "title", label: "Title A–Z" },
  { value: "artist", label: "Artist A–Z" },
  { value: "year-desc", label: "Year (newest)" },
  { value: "year-asc", label: "Year (oldest)" },
];

/** Case-insensitive substring match on title OR artist, then sorted by
 * `sort`. An empty query returns every album, still sorted -- this page is
 * a browse surface, not a search-preview, so there is no result cap. */
export function searchAlbums(
  albums: DirectoryAlbum[],
  query: string,
  sort: AlbumSort,
): DirectoryAlbum[] {
  const needle = query.trim().toLowerCase();
  const matches = needle
    ? albums.filter(
        (album) =>
          album.title.toLowerCase().includes(needle) ||
          album.artist.toLowerCase().includes(needle),
      )
    : albums.slice();
  return matches.sort(COMPARATORS[sort]);
}

function readAlbum(card: HTMLElement): DirectoryAlbum | null {
  const id = card.dataset.albumId;
  const title = card.dataset.albumTitle;
  const artist = card.dataset.albumArtist;
  if (id === undefined || title === undefined || artist === undefined) {
    return null;
  }
  const yearRaw = card.dataset.albumYear;
  const year = yearRaw ? Number(yearRaw) : null;
  return { id, title, artist, year: Number.isFinite(year) ? year : null };
}

export function initAlbumsDirectory(): void {
  const root = document.querySelector<HTMLElement>(
    "[data-testid='albums-directory']",
  );
  if (!root) return;

  const searchInput = root.querySelector<HTMLInputElement>(
    "[data-albums-search]",
  );
  const sortSelect =
    root.querySelector<HTMLSelectElement>("[data-albums-sort]");
  const statusEl = root.querySelector<HTMLElement>("[data-albums-status]");
  const cards = [...root.querySelectorAll<HTMLElement>("[data-album-id]")];
  if (!searchInput || !sortSelect || !statusEl || cards.length === 0) return;

  const byId = new Map<string, HTMLElement>();
  const albums: DirectoryAlbum[] = [];
  for (const card of cards) {
    const album = readAlbum(card);
    if (!album) continue;
    byId.set(album.id, card);
    albums.push(album);
  }

  const render = () => {
    const sort = sortSelect.value as AlbumSort;
    const results = searchAlbums(albums, searchInput.value, sort);
    const visibleIds = new Set(results.map((album) => album.id));
    results.forEach((album, index) => {
      const card = byId.get(album.id);
      if (!card) return;
      card.hidden = false;
      card.style.order = String(index);
    });
    for (const [id, card] of byId) {
      if (!visibleIds.has(id)) card.hidden = true;
    }
    statusEl.textContent =
      results.length === 0
        ? "No albums match your search."
        : `Showing ${results.length} of ${albums.length} albums.`;
  };

  searchInput.addEventListener("input", render);
  sortSelect.addEventListener("change", render);
  render();
}
