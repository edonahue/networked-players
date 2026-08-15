// Connect Two Records (ADR 0051, record-to-record search per ADR 0058):
// wires ConnectStage.astro's markup to the pathfinding graph, the
// evidence-release registry, and the recommended-route engine (ADR 0059).
// The heavy pathfinding graph (~2.34MB gzip, ADR 0058) is fetched lazily on
// first search, not on page load -- the page itself stays light until a
// visitor actually searches. `loadPreparedGraph` (post-Phase-4 cleanup
// audit F11/F12) also keeps it loaded/parsed/indexed in memory for the
// rest of the page session, so only the first search pays that cost.
//
// The evidence registry is fetched ALONGSIDE the graph, not after a route
// is found: ADR 0059's ranking needs its caveat data to pick among
// equal-hop candidates, so it is no longer a purely presentational
// enhancement for the primary result. A failed or slow fetch still never
// blocks a route from being found -- `selectRecommendedRoute` degrades to
// ranking on degree and role substance alone when no caveat vocabulary is
// available.
//
// ADR 0059 Phase 5 PR 4 adds four things on top of that: shareable URL
// state (Connect is the first surface in this codebase to write URL state
// at all -- `flagship.ts`/`routes.ts` only ever READ `?round=`/`?seed=`/
// `?motion=off` once at init), a Swap Records control, a real WAI-ARIA
// combobox for each picker, and a generation-counter request lifecycle
// (the same pattern `explorerStage.ts` already proved) so a stale search
// can never overwrite a newer one's result.

import { fetchAlbumArt, type ResolvedArt } from "./albumArt";
import { filterAlbums, type PickableAlbum } from "./albumPicker";
import {
  buildConnectSearchParams,
  isSameConnectAlbumPair,
  parseConnectUrlParams,
  type ConnectUrlState,
} from "./connectUrlState";
import {
  buildEvidenceIndex,
  enhanceEndpointCover,
  enhanceHopRelease,
  renderEndpointCard,
  renderEvidenceHop,
  type EvidenceIndex,
  type EvidenceRelease,
} from "./connectEvidence";
import { escapeHtml, sessionStorageOrNull } from "./domUtils";
import {
  findAlbumRoute,
  loadPreparedGraph,
  reverseRoute,
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
// matches the checked radio's value, and the one value `connectUrlState.ts`
// never writes into the `mode` URL param.
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
const VALID_MODES = new Set(Object.keys(ROLE_FILTER_MODES));

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
  /** Applies a selection PROGRAMMATICALLY -- updates the input/selected
   * DOM exactly like a real pick would, but never invokes the `onSelect`
   * callback `wirePicker` was given. Used by Swap Records and URL-state
   * restoration, both of which already know the resulting `albumA`/
   * `albumB` state themselves and would otherwise re-trigger the same
   * "a genuinely new pick invalidates the reusable route" invalidation
   * `onSelect` performs for real, user-driven picks -- which is exactly
   * what Swap must NOT do to the route it's about to reuse. */
  setSelection(album: PickableAlbum | null): void;
}

function wirePicker(
  root: HTMLElement,
  // A getter, not a snapshot: the picker is wired before the catalog exists,
  // so it must read whatever is current at event time.
  getAlbums: () => PickableAlbum[],
  onSelect: (album: PickableAlbum | null) => void,
  onInput: () => void,
): PickerHandle | null {
  const side = root.dataset.picker ?? "x";
  const input = root.querySelector<HTMLInputElement>("[data-picker-input]");
  const results = root.querySelector<HTMLUListElement>("[data-picker-results]");
  const selected = root.querySelector<HTMLDivElement>("[data-picker-selected]");
  const countEl = root.querySelector<HTMLElement>("[data-picker-count]");
  if (!input || !results || !selected) return null;

  let currentMatches: PickableAlbum[] = [];
  let activeIndex = -1;

  const optionId = (index: number) => `connect-picker-${side}-option-${index}`;

  const setActiveIndex = (index: number): void => {
    const previous = results.querySelector(`#${optionId(activeIndex)}`);
    previous?.setAttribute("aria-selected", "false");
    activeIndex = index;
    if (activeIndex < 0) {
      input.removeAttribute("aria-activedescendant");
      return;
    }
    const next = results.querySelector(`#${optionId(activeIndex)}`);
    if (next) {
      next.setAttribute("aria-selected", "true");
      next.scrollIntoView({ block: "nearest" });
      input.setAttribute("aria-activedescendant", optionId(activeIndex));
    }
  };

  const closeListbox = (): void => {
    results.hidden = true;
    input.setAttribute("aria-expanded", "false");
    activeIndex = -1;
    input.removeAttribute("aria-activedescendant");
  };

  const applySelection = (
    album: PickableAlbum | null,
    options: { programmatic: boolean },
  ): void => {
    // Closing the listbox is unconditional -- a real review finding: the
    // popstate-cleanup path called `setSelection(null)` expecting it to
    // leave the picker fully closed, but only the `album` branch used to
    // call `closeListbox()`, so an open listbox from an uncommitted typed
    // query survived a visitor navigating away from this whole search
    // (still showing stale options with `aria-expanded="true"` for a
    // now-empty input). Harmless for the `input`-event caller too: it
    // calls `refresh()` immediately afterward, which reopens the listbox
    // from the new query if there's anything to show.
    closeListbox();
    if (album) {
      input.value = `${album.title} — ${album.artist}`;
      selected.hidden = false;
      selected.textContent = `Selected: ${album.title} — ${album.artist}`;
    } else {
      selected.hidden = true;
      selected.innerHTML = "";
    }
    if (!options.programmatic) onSelect(album);
  };

  const showResults = (matches: PickableAlbum[]): void => {
    currentMatches = matches;
    activeIndex = -1;
    input.removeAttribute("aria-activedescendant");
    results.innerHTML = matches
      .map(
        (album, i) =>
          `<li role="option" id="${optionId(i)}" aria-selected="false" data-album-id="${album.id}">${escapeHtml(album.title)} — ${escapeHtml(album.artist)}</li>`,
      )
      .join("");
    results.hidden = matches.length === 0;
    input.setAttribute("aria-expanded", String(matches.length > 0));
    if (countEl) {
      const query = input.value.trim();
      countEl.textContent = !query
        ? ""
        : matches.length === 0
          ? `No results for "${query}"`
          : `${matches.length} result${matches.length === 1 ? "" : "s"} available`;
    }
  };

  const refresh = () => showResults(filterAlbums(getAlbums(), input.value));

  input.addEventListener("input", () => {
    applySelection(null, { programmatic: false });
    refresh();
    onInput();
  });

  input.addEventListener("keydown", (event) => {
    if (results.hidden && event.key !== "ArrowDown") return;
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        if (results.hidden) {
          refresh();
        } else if (currentMatches.length > 0) {
          setActiveIndex(Math.min(activeIndex + 1, currentMatches.length - 1));
        }
        break;
      case "ArrowUp":
        event.preventDefault();
        setActiveIndex(Math.max(activeIndex - 1, -1));
        break;
      case "Enter":
        if (activeIndex >= 0 && currentMatches[activeIndex]) {
          event.preventDefault();
          applySelection(currentMatches[activeIndex], { programmatic: false });
        }
        break;
      case "Escape":
        event.preventDefault();
        closeListbox();
        break;
      default:
        break;
    }
  });

  // Keeps focus in the input when a result is clicked/tapped -- the
  // standard accessible-combobox trick. Without this, the `mousedown`
  // that precedes `click` blurs the input first, which would close the
  // listbox (via a focusout handler) before the click's own selection
  // logic ever runs.
  results.addEventListener("mousedown", (event) => event.preventDefault());

  results.addEventListener("click", (event) => {
    const option = (event.target as HTMLElement).closest<HTMLLIElement>(
      "[role='option']",
    );
    if (!option) return;
    const album = getAlbums().find((a) => a.id === option.dataset.albumId);
    if (!album) return;
    applySelection(album, { programmatic: false });
  });

  // Tabbing (or any focus move) away from the picker closes the listbox --
  // `relatedTarget` is the element GAINING focus, so this only fires when
  // focus is truly leaving the picker, never for the mousedown-preventDefault
  // dance above (which never moves focus at all).
  root.addEventListener("focusout", (event) => {
    if (!root.contains(event.relatedTarget as Node | null)) closeListbox();
  });

  return {
    refresh,
    setState(state: PickerState) {
      root.dataset.pickerState = state;
      input.setAttribute("aria-busy", String(state === "loading"));
    },
    setSelection(album: PickableAlbum | null) {
      applySelection(album, { programmatic: true });
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

type PrimaryRoute = {
  endpointA: AlbumEndpoint;
  hops: PathHop[];
  endpointB: AlbumEndpoint;
  usedEdgeKeys: Set<string>;
};

/** "1 hop documented" / "3 hops documented" -- always rendered, for every
 * outcome (ranked, degraded, role-filtered, alternate), unlike the "why
 * this route" disclosure which only exists for a genuinely ranked result. */
function routeLengthText(hopCount: number): string {
  return `${hopCount} hop${hopCount === 1 ? "" : "s"} documented`;
}

// Album art is presentation-only (ADR 0044/0045) and fetched at most once
// per page session, the same module-level-promise shape `loadEvidenceIndex`
// already uses -- a missing/failed registry resolves to an empty map (every
// endpoint falls back to the placeholder), never blocking a search.
let albumArtPromise: Promise<Map<string, ResolvedArt>> | null = null;
function loadAlbumArt(): Promise<Map<string, ResolvedArt>> {
  if (!albumArtPromise) albumArtPromise = fetchAlbumArt();
  return albumArtPromise;
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
  artByAlbumId: Map<string, ResolvedArt>,
): void {
  target.innerHTML =
    renderEndpointCard(
      route.endpointA,
      fromAlbum.title,
      nameById,
      artByAlbumId.get(fromAlbum.id),
    ) +
    route.hops
      .map((hop) => renderEvidenceHop(hop, nameById, evidenceIndex))
      .join("") +
    renderEndpointCard(
      route.endpointB,
      toAlbum.title,
      nameById,
      artByAlbumId.get(toAlbum.id),
    );
}

export async function initConnect(): Promise<void> {
  const stage = document.querySelector<HTMLElement>(
    "[data-testid='connect-stage']",
  );
  if (!stage) return;

  const searchButton = stage.querySelector<HTMLButtonElement>(
    "[data-connect-search]",
  );
  const swapButton = stage.querySelector<HTMLButtonElement>(
    "[data-connect-swap]",
  );
  const copyLinkButton = stage.querySelector<HTMLButtonElement>(
    "[data-connect-copy-link]",
  );
  const statusEl = stage.querySelector<HTMLElement>("[data-connect-status]");
  const announceEl = stage.querySelector<HTMLElement>(
    "[data-connect-announce]",
  );
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
  const whyPrimaryEl = stage.querySelector<HTMLDetailsElement>(
    "[data-connect-why-primary]",
  );
  const explainPrimaryEl = stage.querySelector<HTMLElement>(
    "[data-connect-explain-primary]",
  );
  const routeLengthEl = stage.querySelector<HTMLElement>(
    "[data-connect-route-length]",
  );
  const routeLengthAltEl = stage.querySelector<HTMLElement>(
    "[data-connect-route-length-alt]",
  );
  const emptyStateEl = stage.querySelector<HTMLElement>(
    "[data-connect-empty-state]",
  );
  if (!searchButton || !statusEl || !resultsEl || !hopsEl) return;

  // Derived, not threaded through every call site that toggles
  // `resultsEl.hidden`/`statusEl.hidden` (there are several, across
  // runSearch/restoreFromUrl/the picker's onSelect handler): a
  // MutationObserver keeps the pre-selection empty state in sync with
  // whatever those two elements' real visibility ends up being, without
  // adding a call at each site or risking one of them drifting out of
  // sync the way the pre-consolidation `last*` variables once did.
  if (emptyStateEl) {
    const updateEmptyState = () => {
      emptyStateEl.hidden = !resultsEl.hidden || !statusEl.hidden;
    };
    updateEmptyState();
    const emptyStateObserver = new MutationObserver(updateEmptyState);
    emptyStateObserver.observe(resultsEl, {
      attributes: true,
      attributeFilter: ["hidden"],
    });
    emptyStateObserver.observe(statusEl, {
      attributes: true,
      attributeFilter: ["hidden"],
    });
  }

  const setStatus = (message: string | null) => {
    if (!message) {
      statusEl.hidden = true;
      statusEl.textContent = "";
      return;
    }
    statusEl.hidden = false;
    statusEl.textContent = message;
  };

  const announce = (message: string) => {
    if (announceEl) announceEl.textContent = message;
  };

  let albumA: PickableAlbum | null = null;
  let albumB: PickableAlbum | null = null;

  // The currently-DISPLAYED search, as ONE unit -- kept so Swap Records can
  // redisplay it reversed without a second search (`reverseRoute`),
  // provably identical evidence, just read the other direction. Deliberately
  // a single object rather than five parallel variables: an earlier version
  // had exactly that shape and it was a real review finding -- three
  // different call sites each cleared a different SUBSET of the fields (a
  // failed search cleared none of them, letting Swap resurrect a route a
  // just-failed re-search had already disproven; the popstate-cleanup path
  // cleared only two of five, leaving stale evidence/mode behind), and
  // Swap read the role-filter radio's LIVE, possibly-since-changed DOM
  // value instead of the mode the cached route was actually computed
  // under. Grouped like this, there is exactly one place to set it, and
  // `clearLastSearch()` below is the only place that clears it -- nothing
  // can drift out of sync by construction.
  //
  // `mode` is the real value ("none" or a filter key) the route was
  // computed under, not a boolean -- Swap needs the EXACT mode to write an
  // honest URL, not merely whether one was active.
  interface LastSearch {
    primaryRoute: PrimaryRoute;
    alternateRoute: PrimaryRoute | null;
    nameById: Map<number, string>;
    evidenceReleases: Map<number, EvidenceRelease>;
    artByAlbumId: Map<string, ResolvedArt>;
    mode: string;
  }
  let lastSearch: LastSearch | null = null;
  const clearLastSearch = () => {
    lastSearch = null;
  };

  // Request lifecycle (ADR 0059 Phase 5 PR 4): the same generation-counter
  // pattern `explorerStage.ts` already proved for its evidence drawer. A
  // search can be superseded by a newer one (a second click, a Swap, a
  // popstate restore) before its own network calls resolve; every await
  // point below re-checks this before touching status/results, so a stale
  // response can never clobber a newer, still-in-flight or already-
  // rendered one.
  let searchGeneration = 0;

  const updateButton = () => {
    const bothPicked = Boolean(albumA && albumB && albumA.id !== albumB.id);
    searchButton.disabled = !bothPicked;
    if (swapButton) swapButton.disabled = !bothPicked;
    // Progressive rendering (ADR 0059 Phase 5 PR 5b): begin preparing the
    // graph on the real intent signal of a FIRST OR second valid pick
    // (the plan's own wording), not the search click -- `loadPreparedGraph`
    // is already a memoized, module-level promise, so warming it here
    // costs nothing extra and just lets `runSearch`'s own `await` resolve
    // immediately (or much sooner) once the visitor actually clicks
    // Search, overlapping fetch/parse/validate time with their own
    // think-time between picking and searching -- the single biggest
    // piece of the measured cold-search waterfall (ADR 0059's own
    // baseline: graph.v2.json wasn't even requested until the search
    // click). The graph doesn't depend on WHICH pair is eventually
    // searched, only that a search is likely coming, so the first pick is
    // just as valid a signal as the second -- there is no reason to wait
    // for both. Album art is warmed for the same reason -- also
    // mode-independent, always needed for the endpoint cards regardless
    // of which route is eventually found. Evidence is deliberately NOT
    // warmed here: unlike the graph, whether it's needed at all depends
    // on the role-filter mode, which isn't decided yet at pick time (it
    // defaults to unfiltered, but a visitor who picks both albums and
    // only afterward selects a role filter is a real, common order --
    // warming evidence unconditionally here would silently resurrect the
    // exact wasted-fetch cost the mode-conditional fetch in `runSearch`
    // was written to avoid). Evidence keeps loading exactly when it does
    // today: alongside the graph for an unfiltered search, or only after
    // a role-filtered route is confirmed.
    if (albumA || albumB) {
      void loadPreparedGraph(sessionStorageOrNull(), PATHFINDING_GRAPH_URL);
      void loadAlbumArt();
    }
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
  let pickerA: PickerHandle | null = null;
  let pickerB: PickerHandle | null = null;

  const setCatalogState = (state: PickerState) => {
    catalogState = state;
    for (const picker of pickers) picker.setState(state);
  };

  // Guards `restoreFromUrl` (declared below, but `function` declarations
  // are hoisted) against running more than once: it should fire exactly
  // once, on whichever catalog attempt first succeeds, never again on a
  // later reload triggered by an unrelated retry.
  let urlRestoreAttempted = false;

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
      // Attempted at most once, on whichever catalog load actually
      // succeeds first -- a real review finding: this used to be a
      // separate call after `await ensureCatalog()` at the bottom of
      // `initConnect`, which only ever ran once regardless of outcome.
      // If THAT first load failed, `restoreFromUrl` saw an empty
      // `albums` array, declined (correctly, per its own contract), and
      // was never invoked again -- so a shared link opened during a
      // transient catalog outage permanently lost its auto-populate/
      // auto-search for the rest of that page view, even after the
      // visitor's own retry-on-keystroke succeeded moments later.
      if (!urlRestoreAttempted) {
        urlRestoreAttempted = true;
        restoreFromUrl(window.location.search, false);
      }
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
        // A real, user-driven pick invalidates any reusable route: Swap
        // must never redisplay a route that no longer describes the two
        // records actually selected.
        clearLastSearch();
        // Two more real review findings, both about this same moment:
        //
        // 1) Bumping `searchGeneration` here (not just inside `runSearch`)
        // closes a gap the button-disabling alone didn't: only Search and
        // Swap were disabled while a request was pending, but the picker
        // inputs stayed live. Editing a selection mid-request without
        // clicking Search again never used to advance the generation, so
        // the original, now-stale request could still finish and render a
        // route/URL for albums that no longer match what's selected. A
        // genuinely new search (a real click) bumps the generation again
        // itself, so this doesn't change how overlapping searches behave --
        // it only stops an EDIT-WITHOUT-a-new-search from letting a
        // superseded request land.
        //
        // 2) Hiding the results panel and Copy Link here (not just
        // clearing `lastSearch`) closes the other half: previously, a pick
        // that discarded the cached route left the OLD pair's route and
        // Copy Link visibly on screen. Pressing Swap at that point (no
        // cached route, so the `lastSearch` block below is a no-op) would
        // then exchange the picker selections while leaving that stale
        // route and URL untouched -- two completely mismatched states
        // shown together. Hiding them here restores the same "swap before
        // a search" state Swap already handles correctly.
        searchGeneration++;
        resultsEl.hidden = true;
        if (copyLinkButton) copyLinkButton.hidden = true;
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
      if (which === "a") pickerA = picker;
      else if (which === "b") pickerB = picker;
    }
  }

  /** Writes `a`/`b`/`mode` to the URL for a just-completed search --
   * `pushState` for a genuinely new pair (a real, navigable history entry
   * a visitor can move back/forward through) or `replaceState` when the
   * same pair is merely being re-run under a different role filter (a
   * refinement, not a new destination). Never called for a search that
   * was itself triggered BY restoring from the URL (`popstate` or init) --
   * the URL is already correct in that case, and writing it again would
   * corrupt history. */
  function syncUrl(state: ConnectUrlState): void {
    const params = buildConnectSearchParams(state);
    const url = `${window.location.pathname}?${params.toString()}`;
    if (isSameConnectAlbumPair(window.location.search, state, VALID_MODES)) {
      window.history.replaceState(state, "", url);
    } else {
      window.history.pushState(state, "", url);
    }
  }

  /** Reveals Copy Link for the URL now current in the address bar.
   * Deliberately independent of `syncUrl`: a URL-restored search
   * (`skipUrlSync: true`, since the address bar is already correct) still
   * completed a real, documented search and still has a real link worth
   * copying -- gating this on the SAME flag that skips the history write
   * left Copy Link permanently hidden for anyone who opened a shared link
   * directly, a real review finding. */
  function showCopyLink(): void {
    if (copyLinkButton) {
      copyLinkButton.hidden = false;
      copyLinkButton.textContent = "Copy link";
    }
  }

  async function runSearch(
    fromAlbum: PickableAlbum,
    toAlbum: PickableAlbum,
    options: { skipUrlSync?: boolean } = {},
  ): Promise<void> {
    const myGeneration = ++searchGeneration;
    const stale = () => myGeneration !== searchGeneration;
    // Non-null aliases: the guards above (`if (!stage) return` /
    // `if (!searchButton || !resultsEl || ...) return`) already prove
    // these, but TS's narrowing from a guard doesn't extend into a named
    // `function` declaration's body the way it does into an arrow
    // function used immediately in the same synchronous flow.
    const stageEl = stage!;
    const resultsElNonNull = resultsEl!;
    const searchButtonNonNull = searchButton!;
    const hopsElNonNull = hopsEl!;

    resultsElNonNull.hidden = true;
    // Honest staged status (ADR 0059 Phase 5 PR 5b): each message names the
    // real operation actually in flight when it's set, never a fabricated
    // percentage. This first message stays true whether the graph is a
    // fresh fetch or already warmed from the second pick (`updateButton`) --
    // the await below still runs either way, it just settles fast when
    // warmed.
    setStatus("Loading the connection graph…");
    searchButtonNonNull.disabled = true;
    if (swapButton) swapButton.disabled = true;
    // Any new attempt invalidates the previous snapshot immediately, win
    // or lose -- a route only becomes reusable again once THIS search
    // actually succeeds and repopulates it below. Without this, a search
    // that fails (wrong filter, no connection) left the prior search's
    // route sitting in `lastSearch`, and Swap could silently resurrect and
    // republish a route the just-failed re-search had already disproven.
    clearLastSearch();

    const selectedModeValue =
      stageEl.querySelector<HTMLInputElement>(
        "[data-connect-mode-option]:checked",
      )?.value ?? "none";
    const roleFilterMode = ROLE_FILTER_MODES[selectedModeValue];

    // Prepared (loaded + indexed) once per page load and reused across
    // every search click via loadPreparedGraph's own module-level cache
    // (post-Phase-4 cleanup audit F11/F12) -- only the first search in a
    // session pays the fetch/parse/index cost; a sessionStorage failure no
    // longer causes a refetch on the 2nd/3rd/4th search within one page
    // load, only across page loads.
    //
    // The evidence registry starts fetching alongside the graph ONLY for
    // an unfiltered search: ADR 0059's ranking needs it before it can pick
    // a route at all. A role-filtered search never ranks (see below) and
    // only ever needs evidence for rendering an ALREADY-found route, so
    // its fetch isn't STARTED until a route is confirmed -- starting it
    // here too would pay a real, unconditional network cost for role-
    // filtered searches and for any search (filtered or not) that turns
    // out to find no route at all. `loadEvidenceIndex()` itself is a
    // memoized module-level promise either way, so a role-filtered search
    // still benefits once an unfiltered search has already paid the cost.
    const evidencePromise = roleFilterMode ? null : loadEvidenceIndex();
    // Kicked off alongside the graph/evidence fetches -- presentation-only
    // and never awaited until render time, so a slow or failed art
    // registry can never delay a route being found or shown.
    const artPromise = loadAlbumArt();
    const preparedResult = await loadPreparedGraph(
      sessionStorageOrNull(),
      PATHFINDING_GRAPH_URL,
    );
    if (stale()) return;
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

    // Second stage: the graph is ready, but rendering still needs either a
    // route search (role-filtered) or a search plus evidence-informed
    // ranking (unfiltered) -- name whichever is actually about to happen.
    setStatus(
      roleFilterMode
        ? "Searching for a documented connection…"
        : "Ranking documented routes…",
    );

    const failureMessages: Record<string, string> = {
      "unknown-album":
        "One of these records isn't in the documented connection graph yet.",
      inconclusive: "The search was inconclusive within the current bounds.",
    };

    // Role-filtered searches keep today's plain first-found BFS
    // unchanged: the edge filter already narrows every hop to one credit
    // type, which is a much stronger constraint than ranking adds value
    // against, and this keeps the existing role-mode behavior exactly as
    // tested. Ranking (ADR 0059) applies to the unfiltered search only.
    let primaryRoute: PrimaryRoute;
    // Shared by both branches below, but populated differently: the
    // unfiltered branch has a fully-resolved map by the time it's set
    // (ranking genuinely needs evidence to pick a route at all, so there
    // is no earlier honest moment to render). The role-filtered branch
    // finds its route with NO evidence dependency (plain BFS over an
    // already-role-narrowed edge set), so it renders structurally first
    // -- this starts empty and is enhanced in place once evidence
    // resolves, the exact `artByAlbumId` pattern below applied to
    // evidence too (ADR 0059 Phase 5 PR 5b: "render the structural route
    // as soon as it exists... and enhance... when registry metadata
    // lands").
    let evidenceReleasesMap: Map<number, EvidenceRelease>;
    // Set only for the role-filtered branch -- the still-in-flight
    // evidence fetch to enhance the already-rendered hops with, once it
    // resolves. `null` for the unfiltered branch, which has nothing left
    // to enhance (its evidence was already awaited before rendering).
    let evidencePromiseToEnhance: Promise<EvidenceIndex> | null = null;
    // Only ever set in the unfiltered branch below; used afterward by the
    // distinct-alternate-route block, which is only ever reached when
    // `roleFilterMode` is falsy -- the same branch that sets this. Kept
    // as a nullable outer variable rather than narrowed by TS (which
    // can't see that correlation across the if/else) for the same reason
    // this file's other non-null aliases exist.
    let unfilteredEvidenceIndex: EvidenceIndex | null = null;
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
      if (stale()) return;
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
      // Kicked off, never awaited here -- see the shared rendering block
      // below for the enhancement half of this split.
      evidenceReleasesMap = new Map();
      evidencePromiseToEnhance = loadEvidenceIndex();
      if (eyebrowEl) eyebrowEl.textContent = "Shortest documented route";
      if (whyPrimaryEl) whyPrimaryEl.hidden = true;
    } else {
      // Already fetching, started alongside the graph above. Genuinely
      // required before rendering: ranking needs evidence caveat data to
      // pick a route at all, so there is no honest "structural" route to
      // show before this resolves.
      unfilteredEvidenceIndex = await evidencePromise!;
      evidenceReleasesMap = unfilteredEvidenceIndex.releases;
      if (stale()) return;
      const result = selectRecommendedRoute(
        graph,
        artistIndex,
        albumIndex,
        fromAlbum.id,
        toAlbum.id,
        unfilteredEvidenceIndex,
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
      if (whyPrimaryEl && explainPrimaryEl) {
        if (result.rankingDegraded) {
          whyPrimaryEl.hidden = true;
        } else {
          whyPrimaryEl.hidden = false;
          explainPrimaryEl.textContent = explainRoute(
            result.recommended.facts,
            result.usedPlusOneHop,
          ).join(" · ");
        }
      }
    }

    // Never awaited here -- a real review finding: `fetchAlbumArt()` has
    // no fetch timeout, and album art is purely presentational, so a slow
    // or hung art registry must never delay showing a route that's already
    // been found. Rendered with whatever's in this map RIGHT NOW (empty on
    // a cold session, already populated if a prior search's art already
    // resolved -- `loadAlbumArt`'s own promise is memoized, so this is
    // instant from the second search on); `artByAlbumId` itself is
    // deliberately the SAME mutable Map stored on `lastSearch` and closed
    // over below, so once the registry resolves, both are updated in one
    // place and Swap's own re-render (which reads `lastSearch.artByAlbumId`)
    // sees the enhancement too, with no extra bookkeeping.
    const artByAlbumId = new Map<string, ResolvedArt>();

    setStatus(null);
    resultsElNonNull.hidden = false;
    if (roleFilterMode && alternateSection) alternateSection.hidden = true;
    if (routeLengthEl) {
      routeLengthEl.textContent = routeLengthText(primaryRoute.hops.length);
    }
    renderRoute(
      hopsElNonNull,
      primaryRoute,
      fromAlbum,
      toAlbum,
      nameById,
      evidenceReleasesMap,
      artByAlbumId,
    );
    lastSearch = {
      primaryRoute,
      alternateRoute: null,
      nameById,
      evidenceReleases: evidenceReleasesMap,
      artByAlbumId,
      mode: selectedModeValue,
    };

    // The enhancement half of the split above: once the (already in-
    // flight, never-awaited) art registry resolves, upgrade each
    // endpoint's placeholder to a real cover IN PLACE -- never a full
    // re-render of the route, which would be real layout thrash for a
    // purely cosmetic upgrade. Reads `hopsAlternateEl`'s CURRENT DOM state
    // at the time this callback actually runs (a later microtask), not at
    // registration time, so it correctly sees whatever the alternate-route
    // block below (entirely synchronous) has by then already rendered.
    const enhanceEndpoints = (container: HTMLElement | null) => {
      if (!container) return;
      const cards = container.querySelectorAll(".connect-endpoint");
      if (cards.length < 2) return;
      enhanceEndpointCover(
        cards[0],
        artByAlbumId.get(fromAlbum.id),
        fromAlbum.title,
      );
      enhanceEndpointCover(
        cards[cards.length - 1],
        artByAlbumId.get(toAlbum.id),
        toAlbum.title,
      );
    };
    void artPromise.then((resolvedArt) => {
      if (stale()) return;
      for (const [id, art] of resolvedArt) artByAlbumId.set(id, art);
      enhanceEndpoints(hopsElNonNull);
      enhanceEndpoints(hopsAlternateEl);
    });

    // The role-filtered branch's own enhancement half: its route was
    // rendered structurally (names, roles, release ids -- ADR 0059 Phase
    // 5 PR 5b's own wording) before evidence was ever awaited, exactly
    // because it doesn't need evidence to find a route at all. Once the
    // kicked-off-but-never-awaited fetch resolves, patch each hop's
    // release sub-card with its cover/title in place -- never a full
    // re-render, same reasoning as the endpoint-art enhancement above.
    if (evidencePromiseToEnhance) {
      void evidencePromiseToEnhance.then((resolved) => {
        if (stale()) return;
        for (const [id, release] of resolved.releases) {
          evidenceReleasesMap.set(id, release);
        }
        const hopEls = hopsElNonNull.querySelectorAll(".connect-hop");
        primaryRoute.hops.forEach((hop, i) => {
          const hopEl = hopEls[i];
          if (hopEl) enhanceHopRelease(hopEl, hop, evidenceReleasesMap);
        });
      });
    }

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
      if (stale()) return;
      alternateSection.hidden = false;
      if (!alternate.ok) {
        if (routeLengthAltEl) routeLengthAltEl.textContent = "";
        explainEl.textContent =
          "No distinct alternate route was found within the same hop budget.";
        hopsAlternateEl.innerHTML = "";
      } else {
        if (routeLengthAltEl) {
          routeLengthAltEl.textContent = routeLengthText(alternate.hops.length);
        }
        renderRoute(
          hopsAlternateEl,
          alternate,
          fromAlbum,
          toAlbum,
          nameById,
          evidenceReleasesMap,
          artByAlbumId,
        );
        if (lastSearch) lastSearch.alternateRoute = alternate;
        // Explained from the SAME facts the primary ranking uses --
        // degree, evidence caveat, role substance -- never a parallel
        // narrative computed some other way (ADR 0059). Non-null: this
        // whole block only runs when `!roleFilterMode`, the same
        // condition under which `unfilteredEvidenceIndex` is always set.
        const facts = computeRouteFacts(
          graph,
          artistIndex,
          alternate.hops,
          unfilteredEvidenceIndex!,
        );
        explainEl.textContent = explainRoute(facts, false).join(" · ");
      }
    }

    // Copy Link is revealed for every completed search, including one
    // restored from a URL -- the address bar is already correct there
    // (that's what `skipUrlSync` means), but the search still completed
    // and there is still a real link worth copying. Only the HISTORY
    // write is conditional on `skipUrlSync`.
    showCopyLink();
    if (!options.skipUrlSync) {
      syncUrl({
        albumAId: fromAlbum.id,
        albumBId: toAlbum.id,
        mode: selectedModeValue,
      });
    }
    updateButton();
  }

  searchButton.addEventListener("click", () => {
    if (!albumA || !albumB) return;
    void runSearch(albumA, albumB);
  });

  if (swapButton) {
    swapButton.addEventListener("click", () => {
      if (!albumA || !albumB) return;
      // Defensive: a search can only be in flight while both buttons are
      // disabled, so this should be unreachable, but bumping the
      // generation here too costs nothing and guarantees a late-arriving
      // response from some future refactor could never clobber a swap.
      searchGeneration++;

      const newA = albumB;
      const newB = albumA;
      albumA = newA;
      albumB = newB;
      pickerA?.setSelection(albumA);
      pickerB?.setSelection(albumB);
      updateButton();

      if (lastSearch) {
        lastSearch.primaryRoute = reverseRoute(lastSearch.primaryRoute);
        renderRoute(
          hopsEl,
          lastSearch.primaryRoute,
          albumA,
          albumB,
          lastSearch.nameById,
          lastSearch.evidenceReleases,
          lastSearch.artByAlbumId,
        );
        if (lastSearch.alternateRoute && hopsAlternateEl) {
          lastSearch.alternateRoute = reverseRoute(lastSearch.alternateRoute);
          renderRoute(
            hopsAlternateEl,
            lastSearch.alternateRoute,
            albumA,
            albumB,
            lastSearch.nameById,
            lastSearch.evidenceReleases,
            lastSearch.artByAlbumId,
          );
        }
        // The MODE STORED ON THE CACHED SEARCH, never a live re-read of
        // the mode radio group -- a real review finding: the checked
        // radio can legitimately differ from what the on-screen route was
        // actually computed under (the visitor can toggle a filter
        // without re-searching), and syncing the live DOM value there
        // would publish a URL claiming a search that was never run.
        syncUrl({
          albumAId: albumA.id,
          albumBId: albumB.id,
          mode: lastSearch.mode,
        });
        showCopyLink();
      }

      announce(
        `Swapped: ${albumA.title} is now first, ${albumB.title} is now second.`,
      );
      // Predictable focus: stays on the control that performed the
      // action, rather than jumping into either input where it could be
      // mistaken for an invitation to keep typing.
      swapButton.focus();
    });
  }

  // Same mid-request-edit gap as the picker `onSelect` above, for the
  // other editable control: changing the role filter while a request is
  // pending never used to advance the generation either, so a request
  // captured under the OLD filter could still land and render/URL-sync
  // for a mode the visitor had since changed away from.
  for (const modeInput of stage.querySelectorAll<HTMLInputElement>(
    "[data-connect-mode-option]",
  )) {
    modeInput.addEventListener("change", () => {
      searchGeneration++;
    });
  }

  if (copyLinkButton) {
    copyLinkButton.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(window.location.href);
        copyLinkButton.textContent = "Copied";
        announce("Link copied to clipboard.");
      } catch {
        announce("Copy failed — the link is in your address bar.");
      }
    });
  }

  /** Reads `a`/`b`/`mode` from `search` and, once the catalog is loaded,
   * either restores the matching picker/mode state and runs the search
   * (both ids resolve) or cleans an unresolvable link's params without
   * alarming the visitor (a dead/stale share link is not something they
   * did wrong). Never executes anything before the real catalog has
   * validated the ids -- the whole reason this function is a no-op until
   * `albums` is populated. */
  function restoreFromUrl(search: string, isPopstate: boolean): void {
    // See the identical non-null-alias note in `runSearch` above -- the
    // outer guards already prove these, TS just can't see it from inside
    // a named function declaration.
    const stageEl = stage!;
    const resultsElNonNull = resultsEl!;

    const parsed = parseConnectUrlParams(search, VALID_MODES);
    if (!parsed) {
      if (isPopstate) {
        // Explicit history navigation back to a state with no real
        // search encoded -- reflect that, don't leave a stale result on
        // screen for a URL that no longer names it.
        albumA = null;
        albumB = null;
        pickerA?.setSelection(null);
        pickerB?.setSelection(null);
        const pickerAInput = stageEl.querySelector<HTMLInputElement>(
          "[data-picker='a'] [data-picker-input]",
        );
        const pickerBInput = stageEl.querySelector<HTMLInputElement>(
          "[data-picker='b'] [data-picker-input]",
        );
        if (pickerAInput) pickerAInput.value = "";
        if (pickerBInput) pickerBInput.value = "";
        clearLastSearch();
        searchGeneration++;
        resultsElNonNull.hidden = true;
        if (copyLinkButton) copyLinkButton.hidden = true;
        setStatus(null);
        updateButton();
      }
      return;
    }
    // Catalog not ready. Unreachable from the init caller (which only
    // ever runs this from inside `ensureCatalog`'s own success path, so
    // `albums` is always populated there) but real for `popstate`, which
    // can fire before any catalog attempt has resolved at all -- declining
    // here is correct; there is nothing to validate against yet.
    if (albums.length === 0) return;
    const albumFromUrl = albums.find((a) => a.id === parsed.albumAId);
    const albumToUrl = albums.find((a) => a.id === parsed.albumBId);
    if (!albumFromUrl || !albumToUrl) {
      // A dead or stale link -- clean it up silently rather than looping
      // on an id that will never resolve.
      window.history.replaceState(null, "", window.location.pathname);
      return;
    }
    albumA = albumFromUrl;
    albumB = albumToUrl;
    pickerA?.setSelection(albumA);
    pickerB?.setSelection(albumB);
    const modeInput = Array.from(
      stageEl.querySelectorAll<HTMLInputElement>("[data-connect-mode-option]"),
    ).find((el) => el.value === parsed.mode);
    if (modeInput) modeInput.checked = true;
    updateButton();
    void runSearch(albumFromUrl, albumToUrl, { skipUrlSync: true });
  }

  window.addEventListener("popstate", () => {
    restoreFromUrl(window.location.search, true);
  });

  // Awaited last, deliberately: every listener above is attached before the
  // first network request, so nothing a visitor does during initialization
  // is dropped -- including a search click, which the old early-return on a
  // catalog failure used to skip wiring entirely. `restoreFromUrl` itself
  // now runs from inside `ensureCatalog`'s own success path (see
  // `urlRestoreAttempted` above), not from here -- that's what lets it
  // fire correctly on a LATER retry too, not just this first attempt.
  await ensureCatalog();
}
