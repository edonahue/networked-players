// Contributors directory (ADR 0058 Slice 8): a client-side search, role
// filter, and "most connected" list over the public contributor index
// (apps/web/public/data/contributors/index.v1.json, ADR 0048) -- zero new
// backend, reusing the index's already-public connection_count field.
// Explicitly not attempting a betweenness-based "bridge contributors" list
// here -- that needs the private one-hop corpus, not the published index.

import { ROLE_CATEGORY_LABEL, type Contributor } from "../data/contributors";
import { escapeHtml, sessionStorageOrNull } from "./domUtils";
import type { StorageLike } from "./store";

export interface DirectoryContributor {
  artist_id: number;
  name: string;
  role_categories: string[];
  connection_count: number;
}

export function toDirectoryContributor(c: Contributor): DirectoryContributor {
  return {
    artist_id: c.artist_id,
    name: c.name,
    role_categories: c.role_categories,
    connection_count: c.connection_count,
  };
}

function byConnectionCountDesc(
  a: DirectoryContributor,
  b: DirectoryContributor,
): number {
  return (
    b.connection_count - a.connection_count || a.name.localeCompare(b.name)
  );
}

/** The default view: the most-connected contributors in the published
 * index, highest degree first. */
export function mostConnected(
  contributors: DirectoryContributor[],
  limit = 20,
): DirectoryContributor[] {
  return [...contributors].sort(byConnectionCountDesc).slice(0, limit);
}

/** Case-insensitive substring match on name, optionally narrowed to
 * contributors carrying at least one of `activeCategories` (chip filters
 * are OR'd together, not AND'd -- picking two role categories widens the
 * result set, matching a typical faceted-filter expectation). An empty
 * query with no active categories returns `mostConnected` instead of the
 * full 549-entry list, so the page never renders an undifferentiated
 * wall. */
export function searchContributors(
  contributors: DirectoryContributor[],
  query: string,
  activeCategories: ReadonlySet<string>,
  limit = 40,
): DirectoryContributor[] {
  const needle = query.trim().toLowerCase();
  if (!needle && activeCategories.size === 0) {
    return mostConnected(contributors, limit);
  }
  const matches: DirectoryContributor[] = [];
  for (const contributor of [...contributors].sort(byConnectionCountDesc)) {
    if (needle && !contributor.name.toLowerCase().includes(needle)) continue;
    if (
      activeCategories.size > 0 &&
      !contributor.role_categories.some((category) =>
        activeCategories.has(category),
      )
    ) {
      continue;
    }
    matches.push(contributor);
    if (matches.length >= limit) break;
  }
  return matches;
}

export const ROLE_CATEGORY_CHIPS: { value: string; label: string }[] =
  Object.entries(ROLE_CATEGORY_LABEL).map(([value, label]) => ({
    value,
    label,
  }));

const CONTRIBUTOR_INDEX_URL = "/data/contributors/index.v1.json";
const CACHE_KEY = "np.contributors-directory:v1";

interface ContributorIndexPayload {
  contributors: Contributor[];
}

/** Fetches and caches the full contributor index in `sessionStorage` (same
 * discipline as `loadPathfindingGraph`) so navigating back to the
 * directory within one session doesn't re-fetch a ~57 KB gzipped
 * artifact. Reduces every contributor down to the small shape the
 * directory actually needs before caching, so the cached blob stays
 * small even though the source artifact carries full evidence per
 * contributor. */
export async function loadDirectoryContributors(
  storage: StorageLike | null,
  url: string = CONTRIBUTOR_INDEX_URL,
): Promise<
  | { contributors: DirectoryContributor[] }
  | { error: "fetch-failed" | "parse-failed" }
> {
  if (storage) {
    try {
      const cached = storage.getItem(CACHE_KEY);
      if (cached) {
        const parsed = JSON.parse(cached);
        if (Array.isArray(parsed)) return { contributors: parsed };
      }
    } catch {
      // fall through to a fresh fetch
    }
  }

  let response: Response;
  try {
    response = await fetch(url);
  } catch {
    return { error: "fetch-failed" };
  }
  if (!response.ok) return { error: "fetch-failed" };

  let raw: unknown;
  try {
    raw = await response.json();
  } catch {
    return { error: "parse-failed" };
  }

  const payload = raw as Partial<ContributorIndexPayload>;
  if (!Array.isArray(payload.contributors)) return { error: "parse-failed" };
  const contributors = payload.contributors.map(toDirectoryContributor);

  if (storage) {
    try {
      storage.setItem(CACHE_KEY, JSON.stringify(contributors));
    } catch {
      // sessionStorage full/unavailable -- search still works, just refetches next time
    }
  }
  return { contributors };
}

function renderResults(
  target: HTMLElement,
  results: DirectoryContributor[],
): void {
  target.innerHTML = results
    .map(
      (c) =>
        `<a class="contributor-card" href="/contributors/${c.artist_id}/">` +
        `<span class="contributor-card__name">${escapeHtml(c.name)}</span>` +
        `<span class="contributor-card__id">${c.connection_count} documented connection${c.connection_count === 1 ? "" : "s"}</span>` +
        `</a>`,
    )
    .join("");
}

export async function initContributorsDirectory(): Promise<void> {
  const root = document.querySelector<HTMLElement>(
    "[data-testid='contributors-directory']",
  );
  if (!root) return;

  const searchInput = root.querySelector<HTMLInputElement>(
    "[data-contributors-search]",
  );
  const statusEl = root.querySelector<HTMLElement>(
    "[data-contributors-status]",
  );
  const headingEl = root.querySelector<HTMLElement>(
    "[data-contributors-heading]",
  );
  const resultsEl = root.querySelector<HTMLElement>(
    "[data-contributors-results]",
  );
  const chipButtons = root.querySelectorAll<HTMLButtonElement>(
    "[data-contributors-category]",
  );
  if (!searchInput || !statusEl || !headingEl || !resultsEl) return;

  const activeCategories = new Set<string>();

  const result = await loadDirectoryContributors(sessionStorageOrNull());
  if ("error" in result) {
    statusEl.textContent =
      result.error === "fetch-failed"
        ? "Couldn't load the contributors directory. Try reloading the page."
        : "The contributors directory looked corrupted. Try reloading the page.";
    return;
  }
  const contributors = result.contributors;
  statusEl.hidden = true;
  statusEl.textContent = "";

  const render = () => {
    const query = searchInput.value;
    const trimmed = query.trim();
    const filters: string[] = [...activeCategories].map(
      (category) => ROLE_CATEGORY_LABEL[category] ?? category,
    );
    if (trimmed) filters.push(`"${trimmed}"`);
    headingEl.textContent =
      filters.length === 0
        ? "Most connected"
        : `Results: ${filters.join(", ")}`;
    const results = searchContributors(contributors, query, activeCategories);
    renderResults(resultsEl, results);
    // Reuses the same status live region the initial loading/error states
    // use -- Albums' and Connect's own search surfaces both announce a
    // "no results" message this way; this directory's grid used to just go
    // silently blank on zero matches.
    if (results.length === 0) {
      statusEl.hidden = false;
      statusEl.textContent = "No contributors match your search.";
    } else {
      statusEl.hidden = true;
      statusEl.textContent = "";
    }
  };

  searchInput.addEventListener("input", render);
  for (const button of chipButtons) {
    button.addEventListener("click", () => {
      const value = button.dataset.contributorsCategory;
      if (!value) return;
      if (activeCategories.has(value)) {
        activeCategories.delete(value);
        button.setAttribute("aria-pressed", "false");
      } else {
        activeCategories.add(value);
        button.setAttribute("aria-pressed", "true");
      }
      render();
    });
  }

  render();
}
