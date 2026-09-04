// Client-side prefix/substring search over the published search index
// (graph-expansion Phase 1, plan §7). Pure, DOM-free ranking logic --
// fetching and caching the index itself lives in `loadSearchIndex` below;
// no library, no runtime dependency on the cluster or Discogs.
//
// Tokenization/normalization happens HERE, at query time, against both the
// query and every entry's own label/sublabel -- the index artifact itself
// stores only plain text (see data/contracts/search-index-v1.md), so this
// is the one place that logic exists, not duplicated between the Python
// builder and this module.

export interface SearchEntry {
  kind: "album" | "contributor";
  id: string;
  label: string;
  sublabel: string | null;
  state: "present" | "candidate";
}

export interface SearchIndex {
  entries: SearchEntry[];
}

const SEARCH_INDEX_URL = "/data/search/index.v1.json";

/** Lowercases and strips combining diacritical marks (`NFD` decomposition
 * separates a base letter from its accent, then this drops the accent) --
 * "café" and "cafe" match the same query, matching the plan's own "tokens:
 * lowercase, diacritics folded" spec. */
function normalize(text: string): string {
  return text
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

/** Splits on anything that isn't a letter or digit -- "Dark Side" tokenizes
 * to ["dark", "side"], so a query can prefix-match ANY word in a label, not
 * only its first one. */
function tokenize(text: string): string[] {
  return normalize(text)
    .split(/[^a-z0-9]+/)
    .filter(Boolean);
}

/** Ascending: 0 is the best possible match. Exact (the whole normalized
 * label/sublabel equals the query) beats a prefix match on any token, which
 * beats a plain substring match anywhere in the text -- the plan's own
 * "exact > prefix > substring" ranking. `null` means "does not match this
 * query at all." */
function matchRank(haystacks: string[], needle: string): 0 | 1 | 2 | null {
  if (haystacks.some((h) => h === needle)) return 0;
  if (
    haystacks.some(
      (h) =>
        h.startsWith(needle) || tokenize(h).some((t) => t.startsWith(needle)),
    )
  ) {
    return 1;
  }
  if (haystacks.some((h) => h.includes(needle))) return 2;
  return null;
}

export interface SearchOptions {
  /** Restricts results to these kinds -- e.g. Connect's album picker only
   * ever wants `["album"]`, never a contributor result. Omit to search
   * every kind. */
  kinds?: SearchEntry["kind"][];
  limit?: number;
}

/** Ranked search over an already-loaded index. Match quality (exact/
 * prefix/substring) is the primary sort key; within an equal quality,
 * `"present"` beats `"candidate"` (the plan's own "present before
 * candidate" tiebreak -- moot until Phase 3 publishes the first candidate
 * entries, but the ordering is already correct for when it does); a
 * final tiebreak on the entry's own position in the index keeps repeated
 * calls deterministic. An empty or all-whitespace query returns no
 * results -- callers show nothing until a visitor starts typing, matching
 * the previous Connect combobox's own behavior. */
export function searchIndex(
  index: SearchIndex,
  query: string,
  options: SearchOptions = {},
): SearchEntry[] {
  const needle = normalize(query.trim());
  if (!needle) return [];
  const limit = options.limit ?? 8;

  const scored: {
    entry: SearchEntry;
    quality: 0 | 1 | 2;
    statePenalty: 0 | 1;
    position: number;
  }[] = [];
  index.entries.forEach((entry, position) => {
    if (options.kinds && !options.kinds.includes(entry.kind)) return;
    const haystacks = [entry.label, entry.sublabel ?? ""].map(normalize);
    const quality = matchRank(haystacks, needle);
    if (quality === null) return;
    const statePenalty = entry.state === "present" ? 0 : 1;
    scored.push({ entry, quality, statePenalty, position });
  });
  // A real three-key comparator, not a packed single integer -- growth
  // (Phase 2 onward adds hundreds more albums and thousands more
  // contributors) must never risk `position` overflowing into the
  // quality/state tiers above it, which a packed encoding would eventually
  // do at some catalog size.
  scored.sort(
    (a, b) =>
      a.quality - b.quality ||
      a.statePenalty - b.statePenalty ||
      a.position - b.position,
  );
  return scored.slice(0, limit).map((s) => s.entry);
}

/** Fetched and cached once per page load (module-level promise, matching
 * `loadPreparedGraph`'s own load-once-reuse shape) -- repeated searches
 * within one session never re-fetch. A fetch failure resolves to an empty
 * index rather than rejecting: every real caller already renders an honest
 * "no results" state for zero matches, so degrading search silently is
 * preferable to breaking the page it's embedded in (the same "losing a
 * nice-to-have beats breaking play" philosophy `store.ts` documents for
 * its own storage failures). */
let indexPromise: Promise<SearchIndex> | null = null;

export function loadSearchIndex(): Promise<SearchIndex> {
  if (!indexPromise) {
    indexPromise = (async () => {
      try {
        const response = await fetch(SEARCH_INDEX_URL);
        if (!response.ok) return { entries: [] };
        const payload = (await response.json()) as SearchIndex;
        return { entries: payload.entries ?? [] };
      } catch {
        return { entries: [] };
      }
    })();
  }
  return indexPromise;
}
