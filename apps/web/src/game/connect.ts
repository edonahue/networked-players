// Connect Two Records (ADR 0051): wires ConnectStage.astro's markup to the
// pathfinding graph, contributor index, and route-quality scoring. The
// heavy pathfinding graph (~1.8MB gzip) is fetched lazily on first search,
// not on page load -- the page itself stays light until a visitor actually
// searches.

import { filterAlbums, type PickableAlbum } from "./albumPicker";
import {
  buildArtistIndex,
  findPath,
  loadPathfindingGraph,
  type PathfindingGraph,
  type PathHop,
} from "./pathfindingGraph";
import { explainScore, scorePath } from "./routeQuality";
import { behindTheGlassEdgeFilter } from "./roleTaxonomy";
import type { Contributor, ContributorIndex } from "../data/contributors";

interface CatalogAlbum {
  id: string;
  title: string;
  artist: string;
  artist_id: number;
  year: number | null;
}

function sessionStorageOrNull(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function renderHop(hop: PathHop, nameById: Map<number, string>): string {
  const nameA = nameById.get(hop.artist_a_id) ?? `Artist ${hop.artist_a_id}`;
  const nameB = nameById.get(hop.artist_b_id) ?? `Artist ${hop.artist_b_id}`;
  const releaseUrl = `https://www.discogs.com/release/${hop.release_id}`;
  return (
    `<div class="connect-hop">` +
    `<p>${escapeHtml(nameA)} <span class="connect-hop__role">(${escapeHtml(hop.role_a)})</span>` +
    ` and ${escapeHtml(nameB)} <span class="connect-hop__role">(${escapeHtml(hop.role_b)})</span>` +
    ` are co-credited on the same documented release.</p>` +
    `<p class="connect-hop__source">Release <a href="${releaseUrl}" rel="nofollow noopener">#${hop.release_id} on Discogs</a></p>` +
    `</div>`
  );
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function wirePicker(
  root: HTMLElement,
  albums: PickableAlbum[],
  onSelect: (album: PickableAlbum | null) => void,
): void {
  const input = root.querySelector<HTMLInputElement>("[data-picker-input]");
  const results = root.querySelector<HTMLUListElement>("[data-picker-results]");
  const selected = root.querySelector<HTMLDivElement>("[data-picker-selected]");
  if (!input || !results || !selected) return;

  const showResults = (matches: PickableAlbum[]) => {
    results.innerHTML = matches
      .map(
        (album) =>
          `<li><button type="button" data-album-id="${album.id}">${escapeHtml(album.title)} — ${escapeHtml(album.artist)}</button></li>`,
      )
      .join("");
    results.hidden = matches.length === 0;
  };

  input.addEventListener("input", () => {
    onSelect(null);
    selected.hidden = true;
    selected.innerHTML = "";
    showResults(filterAlbums(albums, input.value));
  });

  results.addEventListener("click", (event) => {
    const button = (event.target as HTMLElement).closest<HTMLButtonElement>(
      "[data-album-id]",
    );
    if (!button) return;
    const album = albums.find((a) => a.id === button.dataset.albumId);
    if (!album) return;
    input.value = `${album.title} — ${album.artist}`;
    results.hidden = true;
    selected.hidden = false;
    selected.textContent = `Selected: ${album.title} — ${album.artist}`;
    onSelect(album);
  });
}

export async function initConnect(): Promise<void> {
  const stage = document.querySelector<HTMLElement>(
    "[data-testid='connect-stage']",
  );
  if (!stage) return;

  const searchButton = stage.querySelector<HTMLButtonElement>(
    "[data-connect-search]",
  );
  const statusEl = stage.querySelector<HTMLElement>("[data-connect-status]");
  const resultsEl = stage.querySelector<HTMLElement>("[data-connect-results]");
  const hopsEl = stage.querySelector<HTMLElement>("[data-connect-hops]");
  const hopsMusicalEl = stage.querySelector<HTMLElement>(
    "[data-connect-hops-musical]",
  );
  const musicalSection = stage.querySelector<HTMLElement>(
    "[data-connect-result='musical']",
  );
  const explainEl = stage.querySelector<HTMLElement>("[data-connect-explain]");
  const behindTheGlassToggle = stage.querySelector<HTMLInputElement>(
    "[data-connect-behind-the-glass]",
  );
  if (!searchButton || !statusEl || !resultsEl || !hopsEl) return;

  const setStatus = (message: string | null) => {
    if (!message) {
      statusEl.hidden = true;
      statusEl.textContent = "";
      return;
    }
    statusEl.hidden = false;
    statusEl.textContent = message;
  };

  let albumA: PickableAlbum | null = null;
  let albumB: PickableAlbum | null = null;
  const updateButton = () => {
    searchButton.disabled = !(albumA && albumB && albumA.id !== albumB.id);
  };

  let albums: PickableAlbum[] = [];
  try {
    const response = await fetch("/data/catalog/albums.v1.json");
    if (response.ok) {
      const catalog = (await response.json()) as { albums: CatalogAlbum[] };
      albums = catalog.albums;
    }
  } catch {
    setStatus("Couldn't load the album list. Try reloading the page.");
    return;
  }

  for (const pickerRoot of stage.querySelectorAll<HTMLElement>(
    "[data-picker]",
  )) {
    const which = pickerRoot.dataset.picker;
    wirePicker(pickerRoot, albums, (album) => {
      if (which === "a") albumA = album;
      else albumB = album;
      updateButton();
    });
  }

  searchButton.addEventListener("click", async () => {
    if (!albumA || !albumB) return;
    const fromAlbum = albumA;
    const toAlbum = albumB;
    resultsEl.hidden = true;
    setStatus("Searching…");
    searchButton.disabled = true;

    const graphResult = await loadPathfindingGraph(sessionStorageOrNull());
    if (!("graph" in graphResult)) {
      const messages: Record<string, string> = {
        "fetch-failed":
          "Couldn't fetch the connection graph. Check your connection and try again.",
        "parse-failed":
          "The connection graph looked corrupted. Try reloading the page.",
        "invalid-graph":
          "The connection graph failed validation. Try reloading the page.",
      };
      setStatus(
        messages[graphResult.error] ?? "Something went wrong. Try again.",
      );
      updateButton();
      return;
    }
    const graph: PathfindingGraph = graphResult.graph;
    const artistIndex = buildArtistIndex(graph);
    const nameById = new Map<number, string>(
      graph.node_ids.map((id, i) => [id, graph.names[i]]),
    );

    const behindTheGlass = behindTheGlassToggle?.checked ?? false;
    const pathResult = findPath(
      graph,
      artistIndex,
      fromAlbum.artist_id,
      toAlbum.artist_id,
      4,
      behindTheGlass ? behindTheGlassEdgeFilter : undefined,
    );
    if (!pathResult.ok) {
      const messages: Record<string, string> = {
        "unknown-album":
          "One of these records isn't in the documented connection graph yet.",
        inconclusive: "The search was inconclusive within the current bounds.",
        "no-path": behindTheGlass
          ? "No producer/engineer-only connection was found between these two records within 4 hops."
          : "No documented connection was found between these two records within 4 hops.",
      };
      setStatus(messages[pathResult.reason] ?? "No connection found.");
      updateButton();
      return;
    }

    setStatus(null);
    resultsEl.hidden = false;
    if (behindTheGlass && musicalSection) musicalSection.hidden = true;
    hopsEl.innerHTML = pathResult.hops
      .map((hop) => renderHop(hop, nameById))
      .join("");

    // "More musical route" needs contributor role/degree data -- fetched
    // only now, so a plain shortest-path result never pays for it. Skipped
    // in Behind the Glass mode: every hop is already producer/engineer-only
    // by construction, so a role-signal re-ranking has nothing to add.
    if (
      !behindTheGlass &&
      musicalHopsAvailable(hopsMusicalEl, musicalSection)
    ) {
      try {
        const contributorResponse = await fetch(
          "/data/contributors/index.v1.json",
        );
        if (contributorResponse.ok) {
          const contributorIndex =
            (await contributorResponse.json()) as ContributorIndex;
          const byId = new Map<number, Contributor>(
            contributorIndex.contributors.map((c) => [c.artist_id, c]),
          );
          const explanation = explainScore(pathResult.hops, byId);
          if (musicalSection && hopsMusicalEl && explainEl) {
            explainEl.textContent = explanation.join(" · ");
            hopsMusicalEl.innerHTML = pathResult.hops
              .slice()
              .map((hop) => renderHop(hop, nameById))
              .join("");
            // Only show the "more musical route" section when it's
            // meaningfully explainable -- the shortest route is already
            // shown above either way.
            void scorePath(pathResult.hops, byId);
            musicalSection.hidden = false;
          }
        }
      } catch {
        // Contributor data is a presentational enhancement here -- the
        // shortest documented route above already rendered successfully.
      }
    }

    updateButton();
  });
}

function musicalHopsAvailable(
  hopsMusicalEl: Element | null,
  musicalSection: Element | null,
): boolean {
  return Boolean(hopsMusicalEl && musicalSection);
}
