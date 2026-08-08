// Connect Two Records (ADR 0051, record-to-record search per ADR 0058):
// wires ConnectStage.astro's markup to the pathfinding graph, the
// evidence-release registry, the contributor index, and route-quality
// scoring. The heavy pathfinding graph (~2.34MB gzip, ADR 0058) is
// fetched lazily on first search, not on page load -- the page itself
// stays light until a visitor actually searches.

import { filterAlbums, type PickableAlbum } from "./albumPicker";
import {
  buildEvidenceIndex,
  renderEndpointCard,
  renderEvidenceHop,
  type EvidenceRelease,
} from "./connectEvidence";
import {
  buildAlbumIndex,
  buildArtistIndex,
  findAlbumRoute,
  loadPathfindingGraph,
  type AlbumRouteResult,
  type PathfindingGraph,
} from "./pathfindingGraph";
import { explainScore } from "./routeQuality";
import {
  behindTheGlassEdgeFilter,
  guitarPathsEdgeFilter,
  rhythmSectionEdgeFilter,
} from "./roleTaxonomy";
import type { Contributor, ContributorIndex } from "../data/contributors";

const PATHFINDING_GRAPH_URL = "/data/pathfinding/graph.v2.json";
const EVIDENCE_REGISTRY_URL = "/data/evidence/release-registry.v1.json";

interface CatalogAlbum {
  id: string;
  title: string;
  artist: string;
  artist_id: number;
  year: number | null;
}

// One entry per role-filtered search mode (ADR 0053, extended for Rhythm
// Section/Guitar Paths). "none" -- the unfiltered default -- is
// deliberately absent from this table; it's the fallback when no entry
// matches the checked radio's value.
interface RoleFilterMode {
  edgeFilter: (roleA: string, roleB: string) => boolean;
  noPathMessage: string;
}

const ROLE_FILTER_MODES: Record<string, RoleFilterMode> = {
  "behind-the-glass": {
    edgeFilter: behindTheGlassEdgeFilter,
    noPathMessage:
      "No producer/engineer-only connection was found between these two records within 4 hops.",
  },
  "rhythm-section": {
    edgeFilter: rhythmSectionEdgeFilter,
    noPathMessage:
      "No drums/bass-only connection was found between these two records within 4 hops.",
  },
  "guitar-paths": {
    edgeFilter: guitarPathsEdgeFilter,
    noPathMessage:
      "No guitar-only connection was found between these two records within 4 hops.",
  },
};

function sessionStorageOrNull(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
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

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

/** Renders one full route (both endpoint cards + the documented hops
 * between them) into `target`. */
function renderRoute(
  target: HTMLElement,
  route: Extract<AlbumRouteResult, { ok: true }>,
  fromAlbum: PickableAlbum,
  toAlbum: PickableAlbum,
  nameById: Map<number, string>,
  evidenceIndex: Map<number, EvidenceRelease>,
): void {
  target.innerHTML =
    renderEndpointCard(route.endpointA, fromAlbum.title, nameById) +
    route.hops
      .map((hop) => renderEvidenceHop(hop, nameById, evidenceIndex))
      .join("") +
    renderEndpointCard(route.endpointB, toAlbum.title, nameById);
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

    const graphResult = await loadPathfindingGraph(
      sessionStorageOrNull(),
      PATHFINDING_GRAPH_URL,
    );
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
    const albumIndex = buildAlbumIndex(graph);
    const nameById = new Map<number, string>(
      graph.node_ids.map((id, i) => [id, graph.names[i]]),
    );

    const selectedModeValue =
      stage.querySelector<HTMLInputElement>(
        "[data-connect-mode-option]:checked",
      )?.value ?? "none";
    const roleFilterMode = ROLE_FILTER_MODES[selectedModeValue];
    const route = findAlbumRoute(
      graph,
      artistIndex,
      albumIndex,
      fromAlbum.id,
      toAlbum.id,
      4,
      roleFilterMode?.edgeFilter,
    );
    if (!route.ok) {
      const messages: Record<string, string> = {
        "unknown-album":
          "One of these records isn't in the documented connection graph yet.",
        inconclusive: "The search was inconclusive within the current bounds.",
        "no-path":
          roleFilterMode?.noPathMessage ??
          "No documented connection was found between these two records within 4 hops.",
      };
      setStatus(messages[route.reason] ?? "No connection found.");
      updateButton();
      return;
    }

    // Real evidence (title/year/country/cover) is a presentational
    // enhancement over the always-available names/roles/Discogs-id --
    // fetched only now, lazily, and its absence never blocks rendering
    // the documented route itself.
    let evidenceIndex = new Map<number, EvidenceRelease>();
    try {
      const evidenceResponse = await fetch(EVIDENCE_REGISTRY_URL);
      if (evidenceResponse.ok) {
        evidenceIndex = buildEvidenceIndex(await evidenceResponse.json());
      }
    } catch {
      // Falls back to names/roles/source-link-only rendering.
    }

    setStatus(null);
    resultsEl.hidden = false;
    if (roleFilterMode && musicalSection) musicalSection.hidden = true;
    renderRoute(hopsEl, route, fromAlbum, toAlbum, nameById, evidenceIndex);

    // "More musical route" (ADR 0058 Slice 7): a real second search that
    // hard-excludes every edge the first route walked (including its two
    // anchor edges), so a found result is genuinely distinct -- never a
    // second rendering of the same route under a different heading (the
    // bug this fix replaces). Skipped in any role-filtered mode: every
    // hop already matches that mode's credit type by construction, so a
    // role-signal re-ranking has nothing to add.
    if (!roleFilterMode && musicalSection && hopsMusicalEl && explainEl) {
      const alternate = findAlbumRoute(
        graph,
        artistIndex,
        albumIndex,
        fromAlbum.id,
        toAlbum.id,
        4,
        undefined,
        route.usedEdgeKeys,
      );
      musicalSection.hidden = false;
      if (!alternate.ok) {
        explainEl.textContent =
          "No distinct alternate route was found within the same hop budget.";
        hopsMusicalEl.innerHTML = "";
      } else {
        renderRoute(
          hopsMusicalEl,
          alternate,
          fromAlbum,
          toAlbum,
          nameById,
          evidenceIndex,
        );
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
            explainEl.textContent = explainScore(alternate.hops, byId).join(
              " · ",
            );
          } else {
            explainEl.textContent = "A distinct alternate documented route.";
          }
        } catch {
          // Role-signal explanation is a presentational enhancement --
          // the distinct alternate route above already rendered.
          explainEl.textContent = "A distinct alternate documented route.";
        }
      }
    }

    updateButton();
  });
}
