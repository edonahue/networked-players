// Connect Two Records (ADR 0051, record-to-record search per ADR 0058):
// wires ConnectStage.astro's markup to the pathfinding graph, the
// evidence-release registry, the contributor index, and route-quality
// scoring. The heavy pathfinding graph (~2.34MB gzip, ADR 0058) is
// fetched lazily on first search, not on page load -- the page itself
// stays light until a visitor actually searches. `loadPreparedGraph`
// (post-Phase-4 cleanup audit F11/F12) also keeps it loaded/parsed/indexed
// in memory for the rest of the page session, so only the first search
// pays that cost.

import { filterAlbums, type PickableAlbum } from "./albumPicker";
import {
  buildEvidenceIndex,
  renderEndpointCard,
  renderEvidenceHop,
  type EvidenceRelease,
} from "./connectEvidence";
import { escapeHtml, sessionStorageOrNull } from "./domUtils";
import {
  findAlbumRoute,
  loadPreparedGraph,
  type AlbumRouteResult,
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
const ALBUM_CATALOG_URL = "/data/catalog/albums.v1.json";

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

// The album catalog is fetched asynchronously, so a picker exists in one of
// three honest states, published on the picker root as `data-picker-state`
// (plus `aria-busy` on the input itself, the real ARIA contract for "this
// control's data isn't ready yet"). This matters because the input is live
// from first paint: a visitor can type before the catalog lands, and both
// they and a screen reader deserve to know the difference between "no
// matches" and "not loaded yet".
type PickerState = "loading" | "ready" | "unavailable";

interface PickerHandle {
  /**
   * Re-evaluate the input's CURRENT value against the catalog without
   * requiring a new `input` event. This is what closes the initialization
   * race: text typed while the catalog was still in flight fired its
   * `input` event against an empty catalog, and nothing would otherwise
   * ever re-run the filter for it.
   */
  refresh(): void;
  setState(state: PickerState): void;
}

function wirePicker(
  root: HTMLElement,
  // A getter, not a snapshot: the picker is wired before the catalog exists,
  // so it must read whatever is current at event time.
  getAlbums: () => PickableAlbum[],
  onSelect: (album: PickableAlbum | null) => void,
  onInput: () => void,
): PickerHandle | null {
  const input = root.querySelector<HTMLInputElement>("[data-picker-input]");
  const results = root.querySelector<HTMLUListElement>("[data-picker-results]");
  const selected = root.querySelector<HTMLDivElement>("[data-picker-selected]");
  if (!input || !results || !selected) return null;

  const showResults = (matches: PickableAlbum[]) => {
    results.innerHTML = matches
      .map(
        (album) =>
          `<li><button type="button" data-album-id="${album.id}">${escapeHtml(album.title)} — ${escapeHtml(album.artist)}</button></li>`,
      )
      .join("");
    results.hidden = matches.length === 0;
  };

  const refresh = () => showResults(filterAlbums(getAlbums(), input.value));

  input.addEventListener("input", () => {
    onSelect(null);
    selected.hidden = true;
    selected.innerHTML = "";
    refresh();
    onInput();
  });

  results.addEventListener("click", (event) => {
    const button = (event.target as HTMLElement).closest<HTMLButtonElement>(
      "[data-album-id]",
    );
    if (!button) return;
    const album = getAlbums().find((a) => a.id === button.dataset.albumId);
    if (!album) return;
    input.value = `${album.title} — ${album.artist}`;
    results.hidden = true;
    selected.hidden = false;
    selected.textContent = `Selected: ${album.title} — ${album.artist}`;
    onSelect(album);
  });

  return {
    refresh,
    setState(state: PickerState) {
      root.dataset.pickerState = state;
      input.setAttribute("aria-busy", String(state === "loading"));
    },
  };
}

// Typed failure union matching loadPathfindingGraph/loadDirectoryContributors,
// so a non-`ok` response is a real, reportable failure rather than silently
// yielding an empty catalog that looks identical to "nothing matched".
type CatalogFailure = "fetch-failed" | "parse-failed";

async function loadAlbumCatalog(): Promise<
  { albums: PickableAlbum[] } | { error: CatalogFailure }
> {
  let response: Response;
  try {
    response = await fetch(ALBUM_CATALOG_URL);
  } catch {
    return { error: "fetch-failed" };
  }
  if (!response.ok) return { error: "fetch-failed" };
  try {
    const catalog = (await response.json()) as { albums?: CatalogAlbum[] };
    if (!Array.isArray(catalog?.albums)) return { error: "parse-failed" };
    return { albums: catalog.albums };
  } catch {
    return { error: "parse-failed" };
  }
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
  const hopsAlternateEl = stage.querySelector<HTMLElement>(
    "[data-connect-hops-alternate]",
  );
  const alternateSection = stage.querySelector<HTMLElement>(
    "[data-connect-result='alternate']",
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

  // Initialization lifecycle (post-#108 P1): the pickers are wired FIRST and
  // the catalog is awaited last. The inputs are interactive from first paint
  // whatever this module does -- Astro defers the bundle, so the browser has
  // already parsed and painted them -- so the old fetch-then-wire order meant
  // a visitor who typed during initialization fired their `input` event at no
  // listener at all: the text stayed in the box but suggestions never
  // appeared until they typed again. Wiring first and calling refresh() when
  // the catalog lands re-evaluates whatever is already in the box, with no
  // synthetic event, no duplicate listener, and no discarded input.
  let albums: PickableAlbum[] = [];
  let catalogState: PickerState = "loading";
  let catalogPending = false;
  const pickers: PickerHandle[] = [];

  const setCatalogState = (state: PickerState) => {
    catalogState = state;
    for (const picker of pickers) picker.setState(state);
  };

  const ensureCatalog = async (): Promise<void> => {
    if (catalogPending) return;
    catalogPending = true;
    setCatalogState("loading");
    try {
      const result = await loadAlbumCatalog();
      if ("error" in result) {
        setCatalogState("unavailable");
        setStatus(
          result.error === "fetch-failed"
            ? "Couldn't load the album list. Check your connection — keep typing to retry."
            : "The album list looked corrupted. Keep typing to retry, or reload the page.",
        );
        return;
      }
      albums = result.albums;
      setCatalogState("ready");
      setStatus(null);
      for (const picker of pickers) picker.refresh();
    } finally {
      catalogPending = false;
    }
  };

  for (const pickerRoot of stage.querySelectorAll<HTMLElement>(
    "[data-picker]",
  )) {
    const which = pickerRoot.dataset.picker;
    const picker = wirePicker(
      pickerRoot,
      () => albums,
      (album) => {
        if (which === "a") albumA = album;
        else albumB = album;
        updateButton();
      },
      // A failed catalog load leaves a recoverable control, not a dead one:
      // the next keystroke re-attempts the fetch (guarded against piling up
      // concurrent attempts), and a success refreshes both pickers.
      () => {
        if (catalogState === "unavailable") void ensureCatalog();
      },
    );
    if (picker) {
      picker.setState("loading");
      pickers.push(picker);
    }
  }

  searchButton.addEventListener("click", async () => {
    if (!albumA || !albumB) return;
    const fromAlbum = albumA;
    const toAlbum = albumB;
    resultsEl.hidden = true;
    setStatus("Searching…");
    searchButton.disabled = true;

    // Prepared (loaded + indexed) once per page load and reused across
    // every search click via loadPreparedGraph's own module-level cache
    // (post-Phase-4 cleanup audit F11/F12) -- only the first search in a
    // session pays the fetch/parse/index cost; a sessionStorage failure no
    // longer causes a refetch on the 2nd/3rd/4th search within one page
    // load, only across page loads.
    const preparedResult = await loadPreparedGraph(
      sessionStorageOrNull(),
      PATHFINDING_GRAPH_URL,
    );
    if (!("prepared" in preparedResult)) {
      const messages: Record<string, string> = {
        "fetch-failed":
          "Couldn't fetch the connection graph. Check your connection and try again.",
        "parse-failed":
          "The connection graph looked corrupted. Try reloading the page.",
        "invalid-graph":
          "The connection graph failed validation. Try reloading the page.",
      };
      setStatus(
        messages[preparedResult.error] ?? "Something went wrong. Try again.",
      );
      updateButton();
      return;
    }
    const { graph, artistIndex, albumIndex, nameById } =
      preparedResult.prepared;

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
    if (roleFilterMode && alternateSection) alternateSection.hidden = true;
    renderRoute(hopsEl, route, fromAlbum, toAlbum, nameById, evidenceIndex);

    // Distinct alternate route (ADR 0058 Slice 7, renamed post-Phase-4
    // cleanup audit): a real second search that hard-excludes every edge
    // the first route walked (including its two anchor edges), so a found
    // result is genuinely distinct -- never a second rendering of the same
    // route under a different heading (the bug the original Slice-7 fix
    // replaced). This is plain BFS-with-exclusion, not a ranked "musical"
    // alternative -- the label was corrected to match what it actually
    // does (F9/F10 in the audit). Skipped in any role-filtered mode: every
    // hop already matches that mode's credit type by construction, so a
    // distinct-route search has nothing to add there.
    if (!roleFilterMode && alternateSection && hopsAlternateEl && explainEl) {
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
      alternateSection.hidden = false;
      if (!alternate.ok) {
        explainEl.textContent =
          "No distinct alternate route was found within the same hop budget.";
        hopsAlternateEl.innerHTML = "";
      } else {
        renderRoute(
          hopsAlternateEl,
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

  // Awaited last, deliberately: every listener above is attached before the
  // first network request, so nothing a visitor does during initialization
  // is dropped -- including a search click, which the old early-return on a
  // catalog failure used to skip wiring entirely.
  await ensureCatalog();
}
