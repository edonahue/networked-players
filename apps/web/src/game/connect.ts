// Connect Two Records (ADR 0051, record-to-record search per ADR 0058):
// wires ConnectStage.astro's markup to the pathfinding graph, the
// evidence-release registry, and the recommended-route engine (ADR 0059).
// The heavy pathfinding graph (~2.34MB gzip, ADR 0058) is fetched lazily on
// first search, not on page load -- the page itself stays light until a
// visitor actually searches. `loadPreparedGraph` (post-Phase-4 cleanup
// audit F11/F12) also keeps it loaded/parsed/indexed in memory for the
// rest of the page session, so only the first search pays that cost.
//
// The evidence registry is now fetched ALONGSIDE the graph, not after a
// route is found: ADR 0059's ranking needs its caveat data to pick among
// equal-hop candidates, so it is no longer a purely presentational
// enhancement for the primary result. A failed or slow fetch still never
// blocks a route from being found -- `selectRecommendedRoute` degrades to
// ranking on degree and role substance alone when no caveat vocabulary is
// available, the documented fallback (see recommendedRoute.ts).

import { filterAlbums, type PickableAlbum } from "./albumPicker";
import {
  buildEvidenceIndex,
  renderEndpointCard,
  renderEvidenceHop,
  type EvidenceIndex,
  type EvidenceRelease,
} from "./connectEvidence";
import { escapeHtml, sessionStorageOrNull } from "./domUtils";
import {
  findAlbumRoute,
  loadPreparedGraph,
  type AlbumEndpoint,
  type PathHop,
} from "./pathfindingGraph";
import {
  computeRouteFacts,
  explainRoute,
  selectRecommendedRoute,
} from "./recommendedRoute";
import {
  behindTheGlassEdgeFilter,
  guitarPathsEdgeFilter,
  rhythmSectionEdgeFilter,
} from "./roleTaxonomy";

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

// Module-level, like `loadPreparedGraph`'s own cache: fetched and parsed at
// most once per page load no matter how many searches run. A resolved
// EMPTY index (fetch/parse failure) still caches -- it is itself a valid,
// permanent fallback (ranking degrades to degree+role, never blocks a
// search), matching explorerStage.ts's identical no-retry convention for
// its own evidence-index cache.
let evidenceIndexPromise: Promise<EvidenceIndex> | null = null;
function loadEvidenceIndex(): Promise<EvidenceIndex> {
  if (!evidenceIndexPromise) {
    evidenceIndexPromise = (async (): Promise<EvidenceIndex> => {
      try {
        const response = await fetch(EVIDENCE_REGISTRY_URL);
        if (!response.ok) return { releases: new Map(), caveatFlagNames: [] };
        return buildEvidenceIndex(await response.json());
      } catch {
        return { releases: new Map(), caveatFlagNames: [] };
      }
    })();
  }
  return evidenceIndexPromise;
}

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
 * between them) into `target`. Structural, not `AlbumRouteResult`-typed --
 * both a plain `findAlbumRoute` result and a `RankedRoute` from
 * `selectRecommendedRoute` satisfy this shape. */
function renderRoute(
  target: HTMLElement,
  route: {
    endpointA: AlbumEndpoint;
    hops: PathHop[];
    endpointB: AlbumEndpoint;
  },
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
  const eyebrowEl = stage.querySelector<HTMLElement>("[data-connect-eyebrow]");
  const explainPrimaryEl = stage.querySelector<HTMLElement>(
    "[data-connect-explain-primary]",
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
    // load, only across page loads. The evidence registry is fetched in
    // parallel, not chained after: ADR 0059's ranking needs it, so it can
    // no longer wait until after a route is already found the way the
    // purely-presentational pre-ranking version did.
    const [preparedResult, evidenceIndex] = await Promise.all([
      loadPreparedGraph(sessionStorageOrNull(), PATHFINDING_GRAPH_URL),
      loadEvidenceIndex(),
    ]);
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

    const failureMessages: Record<string, string> = {
      "unknown-album":
        "One of these records isn't in the documented connection graph yet.",
      inconclusive: "The search was inconclusive within the current bounds.",
    };

    const selectedModeValue =
      stage.querySelector<HTMLInputElement>(
        "[data-connect-mode-option]:checked",
      )?.value ?? "none";
    const roleFilterMode = ROLE_FILTER_MODES[selectedModeValue];

    // Role-filtered searches keep today's plain first-found BFS
    // unchanged: the edge filter already narrows every hop to one credit
    // type, which is a much stronger constraint than ranking adds value
    // against, and this keeps the existing role-mode behavior exactly as
    // tested. Ranking (ADR 0059) applies to the unfiltered search only.
    let primaryRoute: {
      endpointA: AlbumEndpoint;
      hops: PathHop[];
      endpointB: AlbumEndpoint;
      usedEdgeKeys: Set<string>;
    };
    if (roleFilterMode) {
      const route = findAlbumRoute(
        graph,
        artistIndex,
        albumIndex,
        fromAlbum.id,
        toAlbum.id,
        4,
        roleFilterMode.edgeFilter,
      );
      if (!route.ok) {
        setStatus(
          failureMessages[route.reason] ??
            roleFilterMode.noPathMessage ??
            "No connection found.",
        );
        updateButton();
        return;
      }
      primaryRoute = route;
      if (eyebrowEl) eyebrowEl.textContent = "Shortest documented route";
      if (explainPrimaryEl) explainPrimaryEl.hidden = true;
    } else {
      const result = selectRecommendedRoute(
        graph,
        artistIndex,
        albumIndex,
        fromAlbum.id,
        toAlbum.id,
        evidenceIndex,
        4,
      );
      if (!result.ok) {
        setStatus(
          failureMessages[result.reason] ??
            "No documented connection was found between these two records within 4 hops.",
        );
        updateButton();
        return;
      }
      primaryRoute = result.recommended;
      // Honest labels (ADR 0059): "Recommended" only when real ranking
      // ran. A degraded result (bounded enumeration couldn't produce a
      // real candidate set, so the engine fell back to the plain
      // first-found route) is still a correct, real route -- it just
      // wasn't genuinely compared against alternatives, so it keeps the
      // literal label instead of claiming a ranking that didn't happen.
      if (eyebrowEl) {
        eyebrowEl.textContent = result.rankingDegraded
          ? "Shortest documented route"
          : "Recommended documented route";
      }
      if (explainPrimaryEl) {
        if (result.rankingDegraded) {
          explainPrimaryEl.hidden = true;
        } else {
          explainPrimaryEl.hidden = false;
          explainPrimaryEl.textContent = explainRoute(
            result.recommended.facts,
            result.usedPlusOneHop,
          ).join(" · ");
        }
      }
    }

    setStatus(null);
    resultsEl.hidden = false;
    if (roleFilterMode && alternateSection) alternateSection.hidden = true;
    renderRoute(
      hopsEl,
      primaryRoute,
      fromAlbum,
      toAlbum,
      nameById,
      evidenceIndex.releases,
    );

    // Distinct alternate route (ADR 0058 Slice 7, renamed post-Phase-4
    // cleanup audit): a real second search that hard-excludes every edge
    // the first route walked (including its two anchor edges), so a found
    // result is genuinely distinct -- never a second rendering of the same
    // route under a different heading (the bug the original Slice-7 fix
    // replaced). This is plain BFS-with-exclusion, not a second ranked
    // pick -- the label matches what it actually does. Skipped in any
    // role-filtered mode: every hop already matches that mode's credit
    // type by construction, so a distinct-route search has nothing to add
    // there.
    if (!roleFilterMode && alternateSection && hopsAlternateEl && explainEl) {
      const alternate = findAlbumRoute(
        graph,
        artistIndex,
        albumIndex,
        fromAlbum.id,
        toAlbum.id,
        4,
        undefined,
        primaryRoute.usedEdgeKeys,
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
          evidenceIndex.releases,
        );
        // Explained from the SAME facts the primary ranking uses --
        // degree, evidence caveat, role substance -- never a parallel
        // narrative computed some other way (ADR 0059).
        const facts = computeRouteFacts(
          graph,
          artistIndex,
          alternate.hops,
          evidenceIndex,
        );
        explainEl.textContent = explainRoute(facts, false).join(" · ");
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
