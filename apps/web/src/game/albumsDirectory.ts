// Album shelf (PR G): client-side search, sort, and decade filter over the
// album grid at /albums/ -- no fetch, unlike contributorsDirectory.ts's
// directory, since every album is already server-rendered on this page
// (179 albums is small enough to browse in full, unlike the
// 521-contributor index that needs a search-preview cap). Wiring
// hides/reorders the ALREADY-RENDERED <AlbumCard> elements via `hidden`
// and CSS `order` rather than re-implementing card markup in JS, so the
// no-JS baseline (every album, server-sorted by title) stays a real,
// working fallback. Search/sort/decade state is mirrored into the URL
// (?q=&sort=&decade=) via `history.replaceState` so a filtered view is
// bookmarkable/shareable and survives back/forward navigation, without
// spamming browser history on every keystroke.

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

export const ALL_DECADES = "all";
const UNKNOWN_DECADE = "unknown";

/** Which bounded, honestly-supported bucket an album's year falls into --
 * `year: null` (not every catalog release has one) gets its own explicit
 * bucket rather than being silently excluded from every decade filter. */
export function decadeOf(year: number | null): string {
  return year === null ? UNKNOWN_DECADE : `${Math.floor(year / 10) * 10}s`;
}

export function decadeLabel(decade: string): string {
  return decade === UNKNOWN_DECADE ? "Unknown year" : decade;
}

/** Every decade actually present in `albums`, newest first, with the
 * unknown-year bucket (if present) always last -- never a fixed universal
 * decade list, since a filter option with zero real matches would be
 * dishonest. */
export function availableDecades(albums: DirectoryAlbum[]): string[] {
  const decades = new Set(albums.map((album) => decadeOf(album.year)));
  const known = [...decades]
    .filter((d) => d !== UNKNOWN_DECADE)
    .sort((a, b) => Number.parseInt(b, 10) - Number.parseInt(a, 10));
  return decades.has(UNKNOWN_DECADE) ? [...known, UNKNOWN_DECADE] : known;
}

/** Case-insensitive substring match on title OR artist, narrowed to
 * `decade` (or every decade, via `ALL_DECADES`), then sorted by `sort`. An
 * empty query returns every matching album, still sorted -- this page is a
 * browse surface, not a search-preview, so there is no result cap. */
export function searchAlbums(
  albums: DirectoryAlbum[],
  query: string,
  sort: AlbumSort,
  decade: string = ALL_DECADES,
): DirectoryAlbum[] {
  const needle = query.trim().toLowerCase();
  const matches = albums.filter((album) => {
    const matchesQuery = needle
      ? album.title.toLowerCase().includes(needle) ||
        album.artist.toLowerCase().includes(needle)
      : true;
    const matchesDecade =
      decade === ALL_DECADES || decadeOf(album.year) === decade;
    return matchesQuery && matchesDecade;
  });
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

const DEFAULT_SORT: AlbumSort = "title";

function isAlbumSort(value: string): value is AlbumSort {
  return ALBUM_SORT_OPTIONS.some((option) => option.value === value);
}

function readStateFromUrl(validDecades: Set<string>): {
  query: string;
  sort: AlbumSort;
  decade: string;
} {
  const params = new URLSearchParams(window.location.search);
  const sortParam = params.get("sort");
  const decadeParam = params.get("decade");
  return {
    query: params.get("q") ?? "",
    sort: sortParam && isAlbumSort(sortParam) ? sortParam : DEFAULT_SORT,
    decade:
      decadeParam && validDecades.has(decadeParam) ? decadeParam : ALL_DECADES,
  };
}

function writeStateToUrl(query: string, sort: AlbumSort, decade: string): void {
  const params = new URLSearchParams();
  if (query) params.set("q", query);
  if (sort !== DEFAULT_SORT) params.set("sort", sort);
  if (decade !== ALL_DECADES) params.set("decade", decade);
  const queryString = params.toString();
  const newUrl = queryString
    ? `${window.location.pathname}?${queryString}`
    : window.location.pathname;
  window.history.replaceState(null, "", newUrl);
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
  const decadeSelect = root.querySelector<HTMLSelectElement>(
    "[data-albums-decade]",
  );
  const statusEl = root.querySelector<HTMLElement>("[data-albums-status]");
  const cards = [...root.querySelectorAll<HTMLElement>("[data-album-id]")];
  if (
    !searchInput ||
    !sortSelect ||
    !decadeSelect ||
    !statusEl ||
    cards.length === 0
  ) {
    return;
  }

  const byId = new Map<string, HTMLElement>();
  const albums: DirectoryAlbum[] = [];
  for (const card of cards) {
    const album = readAlbum(card);
    if (!album) continue;
    byId.set(album.id, card);
    albums.push(album);
  }

  for (const decade of availableDecades(albums)) {
    const option = document.createElement("option");
    option.value = decade;
    option.textContent = decadeLabel(decade);
    decadeSelect.append(option);
  }
  const validDecades = new Set([ALL_DECADES, ...availableDecades(albums)]);

  const render = () => {
    const sort = sortSelect.value as AlbumSort;
    const decade = decadeSelect.value;
    const results = searchAlbums(albums, searchInput.value, sort, decade);
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
    writeStateToUrl(searchInput.value, sort, decade);
  };

  const initial = readStateFromUrl(validDecades);
  searchInput.value = initial.query;
  sortSelect.value = initial.sort;
  decadeSelect.value = initial.decade;

  searchInput.addEventListener("input", render);
  sortSelect.addEventListener("change", render);
  decadeSelect.addEventListener("change", render);
  render();
}
