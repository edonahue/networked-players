// Wires NetworkExplorer.astro's SVG shell to the pathfinding graph and
// contributor index (Phase 2 Slice G, ADR 0052). Layout is deterministic
// (center + neighbors evenly spaced on a circle), not force-directed --
// the same bounded-radius data every render works from means a fixed
// layout is enough, and avoids any physics-simulation dependency.

import {
  buildArtistIndex,
  loadPathfindingGraph,
  type PathfindingGraph,
} from "./pathfindingGraph";
import {
  buildView,
  isDimmed,
  type ExplorerNode,
  type ExplorerView,
} from "./networkExplorer";
import {
  buildEvidenceIndex,
  enhanceHopContributorLinks,
  renderEvidenceHop,
  type EvidenceRelease,
} from "./connectEvidence";
import { escapeHtml, sessionStorageOrNull } from "./domUtils";
import type { Contributor, ContributorIndex } from "../data/contributors";
import { ROLE_CATEGORY_LABEL } from "../data/contributors";

const EVIDENCE_REGISTRY_URL = "/data/evidence/release-registry.v1.json";
const PATHFINDING_GRAPH_URL = "/data/pathfinding/graph.v2.json";

const VIEW_SIZE = 320;
const CENTER = VIEW_SIZE / 2;
const RADIUS = 120;
const NODE_RADIUS = 8;
const CENTER_NODE_RADIUS = 14;

/** Width (SVG user units) of each edge's invisible hit-area, post-Phase-4
 * cleanup audit F15. A real, deliberate improvement over the visible
 * line's own 1.5px stroke (8x wider), bounded by how tightly edges pack
 * when a hub shows the full MAX_NEIGHBORS=24 -- wider risks adjacent
 * edges' hit-areas overlapping at typical radii. Applied via a rotated
 * `<rect>`, not a wide `stroke-width` on a `<line>`: a real browser's
 * pointer-event hit-testing already accounts for stroke width on a
 * `<line>`, but `getBoundingClientRect` (what Playwright's actionability
 * checks use before dispatching a synthetic click/hover) reflects only
 * the line's zero-width/zero-height geometric path, ignoring stroke -- so
 * a perfectly vertical or horizontal edge (the circular layout's first
 * neighbor always is) measured as zero-area and failed Playwright's
 * visibility check even though genuinely clickable in a real browser
 * (confirmed by a real test run against a wide-stroke `<line>` version of
 * this fix). A `<rect>`'s own geometry always has real width/height
 * before rotation, so both real hit-testing and Playwright's own checks
 * agree the edge occupies real space. */
const EDGE_HIT_AREA_WIDTH = 12;

function neighborPosition(
  index: number,
  total: number,
): { x: number; y: number } {
  if (total === 0) return { x: CENTER, y: CENTER };
  const angle = (2 * Math.PI * index) / total - Math.PI / 2;
  return {
    x: CENTER + RADIUS * Math.cos(angle),
    y: CENTER + RADIUS * Math.sin(angle),
  };
}

/** Roving-tabindex arrow-key move shared by the node and edge layers
 * (post-Phase-4 cleanup audit F16 -- edges used to be up to 24 independent
 * `tabindex="0"` stops instead of this same one-roving-position pattern
 * nodes already used). `items` is the current tab-stop set in DOM order;
 * moves both the roving `tabIndex` and real focus to the next/previous
 * item, wrapping around either end. */
function moveRovingFocus(items: SVGGElement[], key: string): void {
  if (items.length === 0) return;
  const current = document.activeElement as SVGGElement | null;
  const index = Math.max(0, items.indexOf(current as SVGGElement));
  const delta = key === "ArrowRight" || key === "ArrowDown" ? 1 : -1;
  const next = items[(index + delta + items.length) % items.length];
  for (const item of items) item.tabIndex = -1;
  next.tabIndex = 0;
  next.focus();
}

export async function initExplorerStage(): Promise<void> {
  const stage = document.querySelector<HTMLElement>(
    "[data-testid='explorer-stage']",
  );
  if (!stage) return;

  const svg = stage.querySelector<SVGSVGElement>("[data-explorer-svg]");
  const nodesLayer = stage.querySelector<SVGGElement>("[data-explorer-nodes]");
  const edgesLayer = stage.querySelector<SVGGElement>("[data-explorer-edges]");
  const roleFilterEl = stage.querySelector<HTMLElement>(
    "[data-explorer-role-filter]",
  );
  const statusEl = stage.querySelector<HTMLElement>("[data-explorer-status]");
  const statusAssertiveEl = stage.querySelector<HTMLElement>(
    "[data-explorer-status-assertive]",
  );
  const truncatedEl = stage.querySelector<HTMLElement>(
    "[data-explorer-truncated]",
  );
  const evidenceDrawer = stage.querySelector<HTMLElement>(
    "[data-explorer-evidence-drawer]",
  );
  const evidenceContent = stage.querySelector<HTMLElement>(
    "[data-explorer-evidence-content]",
  );
  const evidenceClose = stage.querySelector<HTMLButtonElement>(
    "[data-explorer-evidence-close]",
  );
  const centerLinkEl = stage.querySelector<HTMLElement>(
    "[data-explorer-center-link]",
  );
  const infoPanelEl = stage.querySelector<HTMLElement>(
    "[data-explorer-info-panel]",
  );
  const infoSummaryEl = stage.querySelector<HTMLElement>(
    "[data-explorer-info-summary]",
  );
  const infoWorthALookEl = stage.querySelector<HTMLElement>(
    "[data-explorer-info-worth-a-look]",
  );
  const infoEmptyEl = stage.querySelector<HTMLElement>(
    "[data-explorer-info-empty]",
  );
  const infoLinksEl = stage.querySelector<HTMLElement>(
    "[data-explorer-info-links]",
  );
  const trailEl = stage.querySelector<HTMLElement>("[data-explorer-trail]");
  if (
    !svg ||
    !nodesLayer ||
    !edgesLayer ||
    !roleFilterEl ||
    !statusEl ||
    !statusAssertiveEl ||
    !truncatedEl ||
    !evidenceDrawer ||
    !evidenceContent ||
    !evidenceClose ||
    !centerLinkEl ||
    !infoPanelEl ||
    !infoSummaryEl ||
    !infoWorthALookEl ||
    !infoEmptyEl ||
    !infoLinksEl ||
    !trailEl
  )
    return;

  const setStatus = (message: string | null) => {
    statusEl.hidden = !message;
    statusEl.textContent = message ?? "";
  };

  setStatus("Loading the network…");

  const graphResult = await loadPathfindingGraph(
    sessionStorageOrNull(),
    PATHFINDING_GRAPH_URL,
  );
  if (!("graph" in graphResult)) {
    // A genuine, terminal integrity failure -- this function returns
    // before wiring up the role filter, the SVG's edges/nodes, or the
    // evidence drawer, exactly like Guesser's/Routes' own showStageError
    // path (nothing playable is ever half-wired). Previously this was
    // announced identically to the ordinary "Loading the network…"
    // message that preceded it, on the one polite region -- added the
    // same `data-phase="error"` + assertive-alert pairing GameStage.astro/
    // RoutesStage.astro already use for their own fetch/integrity
    // failures. The role filter and SVG stay empty regardless (nothing
    // below this point ever populates them), but hidden explicitly too --
    // `.explorer-role-filter` sets `display:flex` unconditionally in
    // game.css, which outranks the bare `[hidden]` UA rule the same way
    // `.chip-tray` does for Routes, so the inline style is set as well.
    // The SVG needs its OWN inline style for a different reason, confirmed
    // by a real fail-then-pass run: the `[hidden] { display: none }` UA
    // rule that makes the bare attribute normally sufficient does not
    // reliably apply across the SVG namespace the way it does for HTML
    // elements -- `svg.setAttribute("hidden", "")` alone left it rendered
    // and visible despite carrying the attribute.
    const message = "Couldn't load the network graph. Try reloading the page.";
    stage.dataset.phase = "error";
    setStatus(message);
    statusAssertiveEl.textContent = message;
    roleFilterEl.hidden = true;
    roleFilterEl.style.display = "none";
    svg.setAttribute("hidden", "");
    svg.style.display = "none";
    return;
  }
  const graph: PathfindingGraph = graphResult.graph;
  const artistIndex = buildArtistIndex(graph);

  let contributorByArtistId = new Map<number, Contributor>();
  try {
    const response = await fetch("/data/contributors/index.v1.json");
    if (response.ok) {
      const contributorIndex = (await response.json()) as ContributorIndex;
      contributorByArtistId = new Map(
        contributorIndex.contributors.map((c) => [c.artist_id, c]),
      );
    }
  } catch {
    // Contributor data enriches role filtering/labels; the graph itself
    // still renders without it.
  }

  // The evidence-release registry (~355 KB gzipped, ADR 0058 Slice 3 --
  // ~57 KB is the *contributor index*'s real size, fetched separately
  // above; this comment named the wrong artifact until the post-Phase-4
  // cleanup audit caught it) is fetched lazily on first edge interaction,
  // not on page load -- most visits to Explore never open the drawer at
  // all. Cached as a promise (not just the resolved map) so a second
  // interaction while the first fetch is still in flight doesn't trigger
  // a duplicate request.
  let evidenceIndexPromise: Promise<Map<number, EvidenceRelease>> | null = null;
  async function fetchEvidenceIndex(): Promise<Map<number, EvidenceRelease>> {
    try {
      const response = await fetch(EVIDENCE_REGISTRY_URL);
      if (!response.ok) return new Map();
      return buildEvidenceIndex(await response.json()).releases;
    } catch {
      return new Map();
    }
  }
  function loadEvidenceIndex(): Promise<Map<number, EvidenceRelease>> {
    if (!evidenceIndexPromise) evidenceIndexPromise = fetchEvidenceIndex();
    return evidenceIndexPromise;
  }

  const initialArtistId = Number(stage.dataset.initialArtistId);
  let activeCategories = new Set<string>();

  // Phase 6 PR 6-03: an optional, READ-ONLY `?center=<artist_id>` deep link
  // overrides which node the view opens on -- used by contributor pages to
  // land on an arbitrary contributor, not just an album's own primary
  // artist. Read once at init, matching flagship.ts/routes.ts's existing
  // read-once convention (this page never calls pushState/replaceState of
  // its own). Validated against the real loaded graph before use: an
  // unknown, malformed, or stale id is silently ignored and the page's own
  // default album-artist center renders instead, never a blank/error state
  // from a bad deep link.
  let initialCenterArtistId = initialArtistId;
  let initialCenterLabel: string | undefined = stage.dataset.initialLabel;
  const requestedCenter = new URLSearchParams(window.location.search).get(
    "center",
  );
  if (requestedCenter !== null) {
    const parsed = Number(requestedCenter);
    if (Number.isInteger(parsed) && artistIndex.has(parsed)) {
      initialCenterArtistId = parsed;
      initialCenterLabel = undefined; // resolved from the graph itself
    }
  }

  function renderRoleFilter(view: ExplorerView) {
    const categories = new Set<string>();
    for (const node of [view.center, ...view.neighbors]) {
      for (const category of node.roleCategories) categories.add(category);
    }
    if (categories.size === 0) {
      roleFilterEl!.innerHTML = "";
      return;
    }
    roleFilterEl!.innerHTML = [...categories]
      .sort()
      .map(
        (category) =>
          `<button type="button" class="chip" data-role-filter-chip="${category}" aria-pressed="${activeCategories.has(category)}">${escapeHtml(ROLE_CATEGORY_LABEL[category] ?? category)}</button>`,
      )
      .join("");
  }

  function renderView(view: ExplorerView) {
    truncatedEl!.hidden = !view.truncated;

    const nodePositions = new Map<number, { x: number; y: number }>();
    nodePositions.set(view.center.artistId, { x: CENTER, y: CENTER });
    view.neighbors.forEach((node, i) => {
      nodePositions.set(
        node.artistId,
        neighborPosition(i, view.neighbors.length),
      );
    });

    const nodeNameById = new Map<number, string>(
      [view.center, ...view.neighbors].map((n) => [n.artistId, n.name]),
    );

    // ADR 0060: highlight the center's own interesting_next_step neighbor,
    // when currently rendered -- a small, additive marker, never hiding or
    // reordering any other neighbor. `undefined` (no signal, the signaled
    // artist isn't in this bounded view, or -- measured, real, ~27% of the
    // time -- the contributor index's own small curated graph and this
    // pathfinding graph simply don't share that edge, since they're built
    // from different published artifacts) simply highlights nothing,
    // matching the source field's own null-is-valid contract.
    const interestingNextStepArtistId = contributorByArtistId.get(
      view.center.artistId,
    )?.interesting_next_step?.artist_id;

    // Each edge is a <g> wrapping a wide, invisible hit-area rect (see
    // EDGE_HIT_AREA_WIDTH -- post-Phase-4 cleanup audit F15, the visible
    // line alone was a bare 1.5px stroke, ~15-25x under a real
    // touch-target size on any realistic viewport) plus the real thin
    // styled line. The <g>, not either child, carries the interactive
    // attributes (tabindex/role/aria-label/data-*) --
    // `.closest("[data-release-id]")` in the delegated handlers below
    // finds it regardless of which child the event actually originated
    // on, and CSS hover/focus-visible states on the group drive the
    // visible line's style via a descendant selector. Only the first edge
    // is a tab stop on a fresh render (F16 -- roving tabindex, matching
    // the node pattern below, replacing up to 24 independent
    // tabindex="0" stops with one roving position).
    edgesLayer!.innerHTML = view.edges
      .map((edge, i) => {
        const from = nodePositions.get(view.center.artistId)!;
        const to = nodePositions.get(edge.neighborArtistId)!;
        const neighborName =
          nodeNameById.get(edge.neighborArtistId) ?? "this contributor";
        const coords = `x1="${from.x}" y1="${from.y}" x2="${to.x}" y2="${to.y}"`;
        const dx = to.x - from.x;
        const dy = to.y - from.y;
        const length = Math.hypot(dx, dy);
        const angleDeg = (Math.atan2(dy, dx) * 180) / Math.PI;
        const hitArea =
          `<rect x="${from.x}" y="${from.y - EDGE_HIT_AREA_WIDTH / 2}" ` +
          `width="${length}" height="${EDGE_HIT_AREA_WIDTH}" ` +
          `transform="rotate(${angleDeg} ${from.x} ${from.y})" ` +
          `class="explorer-edge-hitarea" />`;
        return (
          `<g class="explorer-edge-group" ` +
          `data-neighbor-id="${edge.neighborArtistId}" data-release-id="${edge.releaseId}" ` +
          `data-role-center="${escapeHtml(edge.roleCenter)}" data-role-neighbor="${escapeHtml(edge.roleNeighbor)}" ` +
          `tabindex="${i === 0 ? "0" : "-1"}" role="button" ` +
          `aria-label="Evidence for the documented credit between ${escapeHtml(view.center.name)} and ${escapeHtml(neighborName)}">` +
          hitArea +
          `<line ${coords} class="explorer-edge" />` +
          `</g>`
        );
      })
      .join("");

    // Roving tabindex (matching flagship.ts's chip-tray pattern): only the
    // center node is a tab stop on a fresh render -- arrow keys move both
    // the roving position and real DOM focus among neighbors from there,
    // instead of every node being its own independent tab stop.
    const renderNode = (node: ExplorerNode) => {
      const pos = nodePositions.get(node.artistId)!;
      const dimmed = isDimmed(node, activeCategories);
      const r = node.isCenter ? CENTER_NODE_RADIUS : NODE_RADIUS;
      const isInterestingNextStep =
        !node.isCenter && node.artistId === interestingNextStepArtistId;
      const label = isInterestingNextStep
        ? `${escapeHtml(node.name)} (credited in a different kind of role — worth a look)`
        : `${escapeHtml(node.name)}${node.isCenter ? " (center)" : ""}`;
      return (
        `<g class="explorer-node${dimmed ? " explorer-node--dimmed" : ""}${isInterestingNextStep ? " explorer-node--interesting" : ""}" ` +
        `data-artist-id="${node.artistId}" data-is-center="${node.isCenter}" ` +
        `data-is-interesting-next-step="${isInterestingNextStep}" ` +
        `tabindex="${node.isCenter ? "0" : "-1"}" role="button" aria-label="${label}">` +
        `<circle cx="${pos.x}" cy="${pos.y}" r="${r}" />` +
        `<text x="${pos.x}" y="${pos.y + r + 12}" text-anchor="middle">${escapeHtml(node.name)}</text>` +
        `</g>`
      );
    };

    nodesLayer!.innerHTML =
      renderNode(view.center) +
      view.neighbors.map((n) => renderNode(n)).join("");
  }

  let currentView: ExplorerView | null = null;

  // Session-only "recently centered on" trail (plan §12.7's continuity
  // pass): a capped, in-memory list, never persisted and never touching
  // history/URL state -- recentering elsewhere in the app (a fresh page
  // load) starts a fresh trail, matching this page's existing
  // never-calls-pushState convention. Consecutive re-centers on the same
  // node don't grow it. Each entry re-invokes centerOn() directly (a real
  // in-page state change), not a navigation.
  const MAX_TRAIL_LENGTH = 5;
  const recentCenters: { artistId: number; name: string }[] = [];

  function pushTrail(artistId: number, name: string) {
    if (recentCenters[recentCenters.length - 1]?.artistId === artistId) return;
    recentCenters.push({ artistId, name });
    while (recentCenters.length > MAX_TRAIL_LENGTH) recentCenters.shift();
  }

  function renderTrail() {
    if (recentCenters.length < 2) {
      trailEl!.hidden = true;
      trailEl!.innerHTML = "";
      return;
    }
    trailEl!.hidden = false;
    trailEl!.innerHTML =
      `<span class="explorer-trail__label">Recently: </span>` +
      recentCenters
        .map((entry, i) => {
          const isCurrent = i === recentCenters.length - 1;
          const sep = i > 0 ? '<span aria-hidden="true"> → </span>' : "";
          return isCurrent
            ? `${sep}<span class="explorer-trail__current" aria-current="true">${escapeHtml(entry.name)}</span>`
            : `${sep}<button type="button" class="explorer-trail__step" data-trail-artist-id="${entry.artistId}">${escapeHtml(entry.name)}</button>`;
        })
        .join("");
  }

  function centerOn(
    artistId: number,
    label?: string,
    options: { moveFocus?: boolean } = {},
  ) {
    const view = buildView(graph, artistIndex, contributorByArtistId, artistId);
    if (!view) {
      setStatus(
        `${label ?? "This artist"} isn't in the documented network graph yet.`,
      );
      return;
    }
    activeCategories = new Set();
    currentView = view;
    openEdgeRequestId++; // invalidate any evidence fetch still in flight for the old view
    evidenceDismissed = false; // a fresh view is a natural reset point regardless of the old one's state
    hideEvidenceDrawer();
    renderRoleFilter(view);
    // Set BEFORE the rebuild: the synthetic mouseover this render can
    // trigger fires as part of/immediately after this same call, and must
    // never reopen the drawer this line just closed. Cleared at the next
    // macrotask boundary -- see the flag's own declaration comment below.
    suppressPassiveTriggersUntilRealMouseMove = true;
    setTimeout(() => {
      suppressPassiveTriggersUntilRealMouseMove = false;
    }, 0);
    renderView(view);
    // Announce the new center -- rebuilding the SVG destroys whatever was
    // previously focused, so without this a screen reader gets no signal
    // the view changed at all.
    setStatus(`Centered on ${view.center.name}.`);

    // Phase 6 PR 6-05: link back to the center's own contributor page, when
    // one exists -- not every graph node clears the contributor index's own
    // inclusion rule (and a virtual album-anchor node, negative artistId,
    // never has one), so this hides rather than rendering a dangling href.
    const centerContributor = contributorByArtistId.get(view.center.artistId);
    if (centerContributor) {
      centerLinkEl!.hidden = false;
      centerLinkEl!.innerHTML =
        `<a href="/contributors/${centerContributor.artist_id}/" data-explorer-center-contributor-link>` +
        `View ${escapeHtml(view.center.name)}'s full contributor page →</a>`;
    } else {
      centerLinkEl!.hidden = true;
      centerLinkEl!.innerHTML = "";
    }

    // The info panel: a sighted-user-visible parity fix for what the
    // SR-only status region above already announces, plus real "continue
    // wandering" affordances the center previously had no way to offer
    // beyond a single conditional contributor-page link.
    infoPanelEl!.hidden = false;
    const roleSummary = view.center.roleCategories
      .map((c) => ROLE_CATEGORY_LABEL[c] ?? c)
      .join(", ");
    infoSummaryEl!.textContent = roleSummary
      ? `Centered on ${view.center.name} — credited for ${roleSummary}.`
      : `Centered on ${view.center.name}.`;

    // Same guard renderView uses for the node highlight -- only mention a
    // "worth a look" neighbor when it's actually one of the rendered
    // nodes. ~27% of the time (measured, Phase 6 PR 6-10) the signal's
    // target isn't a real edge in this published graph at all; silence is
    // the honest behavior there, matching the field's own null-is-valid
    // contract, not a forced or misleading mention.
    const nextStep = centerContributor?.interesting_next_step;
    const worthALookNeighbor = nextStep
      ? view.neighbors.find((n) => n.artistId === nextStep.artist_id)
      : undefined;
    if (nextStep && worthALookNeighbor) {
      infoWorthALookEl!.hidden = false;
      infoWorthALookEl!.innerHTML = `Worth a look: <a href="/contributors/${nextStep.artist_id}/">${escapeHtml(worthALookNeighbor.name)}</a> — ${escapeHtml(nextStep.reason)}.`;
    } else {
      infoWorthALookEl!.hidden = true;
      infoWorthALookEl!.innerHTML = "";
    }

    infoEmptyEl!.hidden = view.neighbors.length > 0;

    const centerAlbumId = centerContributor?.albums[0];
    infoLinksEl!.innerHTML = centerAlbumId
      ? `<a href="/albums/${centerAlbumId}/">View ${escapeHtml(view.center.name)}'s record →</a>` +
        ` · <a href="/play/connect/?a=${centerAlbumId}">Continue in Connect Two Records →</a>`
      : "";

    pushTrail(view.center.artistId, view.center.name);
    renderTrail();

    if (options.moveFocus) {
      nodesLayer!
        .querySelector<SVGGElement>(
          `[data-artist-id="${view.center.artistId}"]`,
        )
        ?.focus();
    }
  }

  // Evidence drawer (ADR 0058 Slice 9): an edge's release/role data is
  // already carried on the DOM element itself (set in renderView above),
  // so opening the drawer never needs to re-walk `currentView.edges` --
  // robust against `currentView` having moved on mid-interaction. `openId`
  // guards against a stale, slower-resolving fetch (e.g. a quick hover
  // that already moved to a different edge) overwriting newer content.
  let openEdgeRequestId = 0;

  // The element focus should return to when the drawer closes (post-Phase-4
  // cleanup audit F17) -- only set when the drawer was opened by an
  // explicit activation (click or Enter/Space), never by hover/focusin, so
  // closing after a plain hover doesn't yank focus somewhere the visitor
  // never asked to go.
  let drawerTriggerEl: SVGGElement | null = null;
  // True once the visitor has explicitly dismissed the drawer (Escape or
  // the close button) -- while true, passive triggers (mouseover/focusin)
  // never reopen it; only a genuinely new explicit activation (click or
  // Enter/Space) or recentering the graph does. Real testing found the
  // DOM mutation from closing the drawer (hiding it, moving focus back to
  // the edge) makes Chromium redeliver a synthetic mouseout/mouseover pair
  // for whatever's now under the OS cursor's last known position -- with
  // no real pointer movement at all, this could otherwise silently reopen
  // what the visitor just explicitly closed. A per-edge suppression that
  // clears on the paired mouseout is not robust against this, since the
  // synthetic mouseout is exactly what clears it right before the
  // synthetic mouseover that follows; suppressing all passive triggers
  // until the next genuinely new explicit action sidesteps the problem
  // entirely, regardless of how many synthetic events Chromium generates
  // or in what order.
  let evidenceDismissed = false;

  // A SECOND, narrower suppression than `evidenceDismissed` above, for a
  // DIFFERENT synthetic-event scenario: `centerOn()` rebuilds the whole SVG
  // (`renderView`), and that DOM mutation makes Chromium redeliver a
  // synthetic `mouseover` for whatever new edge element now sits under the
  // cursor's last known position -- with no real pointer movement at all.
  // Unlike the close-button case, recentering must NOT leave hover
  // permanently suppressed afterward (a visitor who genuinely moves the
  // mouse over the new graph should see hover-to-preview work immediately),
  // so `evidenceDismissed` is the wrong tool here: it only clears on the
  // next explicit click/Enter, which would break real hovering after every
  // recenter.
  //
  // Tried clearing this on the next real `mousemove` first -- reverted: a
  // genuine hover onto a NEW element fires `mouseover` on it BEFORE any
  // `mousemove` (confirmed instrumenting real event order in a browser),
  // the same as the synthetic replay does, so that signal can't tell them
  // apart. What actually distinguishes them is timing relative to THIS
  // call: the synthetic replay is a direct, synchronous-ish consequence of
  // the DOM mutation `renderView` just performed, while any genuinely new
  // interaction requires a fresh native input event, which cannot arrive
  // until the current task finishes. A one-shot `setTimeout(0)` clears the
  // flag at the next macrotask boundary -- after the synthetic replay (part
  // of this task), before anything a subsequent real interaction dispatches
  // (necessarily a later task). Root-caused 2026-08-29 from a real,
  // reproducible CI flake (network-explorer-evidence.spec.ts's "recentering
  // the graph closes the drawer"); the fix verified against a genuine
  // hover-after-recenter regression test, not just the original flake.
  let suppressPassiveTriggersUntilRealMouseMove = false;

  // The drawer opens synchronously but its evidence arrives over the network,
  // so "visible" and "showing real evidence" are two different things. These
  // states make that difference observable instead of implicit:
  //   loading      -- open, registry request in flight, placeholder content
  //   ready        -- open, release metadata found and rendered
  //   unavailable  -- open, credit rendered but release metadata is missing
  //                   (release absent from the registry, or the registry
  //                   fetch failed -- both degrade to the same card)
  // Closed needs no value: `hidden` already says so, and the attribute is
  // removed. `aria-busy` rides along because it is the real ARIA contract
  // for a region whose content is mid-update -- without it a screen reader
  // gets no signal at all that "Loading evidence…" is about to be replaced.
  type DrawerState = "loading" | "ready" | "unavailable";

  function setDrawerState(state: DrawerState | null) {
    if (state === null) {
      delete evidenceDrawer!.dataset.evidenceState;
      evidenceDrawer!.removeAttribute("aria-busy");
      return;
    }
    evidenceDrawer!.dataset.evidenceState = state;
    evidenceDrawer!.setAttribute("aria-busy", String(state === "loading"));
  }

  function hideEvidenceDrawer(options: { restoreFocus?: boolean } = {}) {
    openEdgeRequestId++; // invalidate any evidence fetch still in flight for
    // the edge this drawer was showing -- otherwise a slow registry response
    // that resolves after the drawer is closed still passes showEdgeEvidence's
    // requestId guard and resurrects data-evidence-state/aria-busy/content on
    // a drawer the visitor already dismissed.
    evidenceDrawer!.hidden = true;
    evidenceContent!.innerHTML = "";
    setDrawerState(null);
    if (options.restoreFocus) {
      evidenceDismissed = true;
      drawerTriggerEl?.focus();
    }
    drawerTriggerEl = null;
  }

  async function showEdgeEvidence(
    edgeEl: SVGGElement,
    options: { moveFocus?: boolean } = {},
  ) {
    const neighborId = Number(edgeEl.dataset.neighborId);
    const releaseId = Number(edgeEl.dataset.releaseId);
    const roleCenter = edgeEl.dataset.roleCenter ?? "";
    const roleNeighbor = edgeEl.dataset.roleNeighbor ?? "";
    if (!currentView || Number.isNaN(neighborId) || Number.isNaN(releaseId))
      return;

    const requestId = ++openEdgeRequestId;
    evidenceDrawer!.hidden = false;
    setDrawerState("loading");
    evidenceContent!.innerHTML = "<p>Loading evidence…</p>";
    // Move focus immediately (not after the evidence fetch resolves) --
    // the drawer already has a real accessible name (role="region",
    // aria-label) and "Loading evidence…" content, so a screen reader has
    // something meaningful to announce right away.
    if (options.moveFocus) {
      evidenceDismissed = false;
      drawerTriggerEl = edgeEl;
      evidenceDrawer!.focus();
    }

    const evidenceIndex = await loadEvidenceIndex();
    if (requestId !== openEdgeRequestId) return; // a newer edge opened meanwhile

    const nameById = new Map<number, string>(
      [currentView.center, ...currentView.neighbors].map((n) => [
        n.artistId,
        n.name,
      ]),
    );
    evidenceContent!.innerHTML = renderEvidenceHop(
      {
        release_id: releaseId,
        artist_a_id: currentView.center.artistId,
        artist_b_id: neighborId,
        role_a: roleCenter,
        role_b: roleNeighbor,
      },
      nameById,
      evidenceIndex,
    );
    // Phase 6 PR 6-06: the contributor index is already fully resolved by
    // this point (awaited during init, before any edge is clickable), so
    // this is a synchronous enhancement, not a deferred one like Connect's.
    enhanceHopContributorLinks(
      evidenceContent!,
      new Set(contributorByArtistId.keys()),
    );
    // Set only after the content swap, so the state never advertises evidence
    // that isn't in the DOM yet.
    setDrawerState(evidenceIndex.has(releaseId) ? "ready" : "unavailable");
  }

  edgesLayer.addEventListener("click", (event) => {
    const target = (event.target as Element).closest<SVGGElement>(
      "[data-release-id]",
    );
    if (!target) return;
    void showEdgeEvidence(target, { moveFocus: true });
  });
  edgesLayer.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      const target = (event.target as Element).closest<SVGGElement>(
        "[data-release-id]",
      );
      if (!target) return;
      event.preventDefault();
      void showEdgeEvidence(target, { moveFocus: true });
      return;
    }

    const arrowKeys = ["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp"];
    if (!arrowKeys.includes(event.key)) return;
    event.preventDefault();
    const groups = [
      ...edgesLayer!.querySelectorAll<SVGGElement>(".explorer-edge-group"),
    ];
    moveRovingFocus(groups, event.key);
  });
  // "mouseover"/"focusin" (not "mouseenter"/"focus") because both bubble,
  // letting one delegated listener on the layer cover every edge without
  // attaching a handler per `<g>` on every render. Neither moves focus
  // (F17) -- a hover shouldn't steal keyboard focus, and focusin means the
  // edge already has focus (from Tab or the roving-focus move above),
  // which already gives a screen reader the right announcement on its own.
  edgesLayer.addEventListener("mouseover", (event) => {
    if (evidenceDismissed || suppressPassiveTriggersUntilRealMouseMove) return;
    const target = (event.target as Element).closest<SVGGElement>(
      "[data-release-id]",
    );
    if (!target) return;
    void showEdgeEvidence(target);
  });
  edgesLayer.addEventListener("focusin", (event) => {
    if (evidenceDismissed) return;
    const target = (event.target as Element).closest<SVGGElement>(
      "[data-release-id]",
    );
    if (!target) return;
    void showEdgeEvidence(target);
  });
  evidenceClose.addEventListener("click", () =>
    hideEvidenceDrawer({ restoreFocus: true }),
  );
  // Document-level, not scoped to the drawer's own focus: a hover-opened
  // drawer never moves real DOM focus at all, so a listener attached only
  // to the drawer element would never see the Escape keydown a visitor
  // presses right after hovering (as opposed to clicking) an edge.
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !evidenceDrawer!.hidden)
      hideEvidenceDrawer({ restoreFocus: true });
  });
  nodesLayer.addEventListener("click", (event) => {
    const target = (event.target as Element).closest<SVGGElement>(
      "[data-artist-id]",
    );
    if (!target || target.dataset.artistId === undefined) return;
    centerOn(Number(target.dataset.artistId), undefined, { moveFocus: true });
  });
  nodesLayer.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      const target = (event.target as Element).closest<SVGGElement>(
        "[data-artist-id]",
      );
      if (!target) return;
      event.preventDefault();
      centerOn(Number(target.dataset.artistId), undefined, {
        moveFocus: true,
      });
      return;
    }

    const arrowKeys = ["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp"];
    if (!arrowKeys.includes(event.key)) return;
    event.preventDefault();
    const nodes = [
      ...nodesLayer!.querySelectorAll<SVGGElement>("[data-artist-id]"),
    ];
    moveRovingFocus(nodes, event.key);
  });

  roleFilterEl.addEventListener("click", (event) => {
    const button = (event.target as HTMLElement).closest<HTMLButtonElement>(
      "[data-role-filter-chip]",
    );
    if (!button || !currentView) return;
    const category = button.dataset.roleFilterChip!;
    if (activeCategories.has(category)) activeCategories.delete(category);
    else activeCategories.add(category);
    renderRoleFilterButtons();
    renderView(currentView);
  });

  function renderRoleFilterButtons() {
    for (const button of roleFilterEl!.querySelectorAll<HTMLButtonElement>(
      "[data-role-filter-chip]",
    )) {
      const category = button.dataset.roleFilterChip!;
      button.setAttribute(
        "aria-pressed",
        String(activeCategories.has(category)),
      );
    }
  }

  trailEl.addEventListener("click", (event) => {
    const button = (event.target as HTMLElement).closest<HTMLButtonElement>(
      "[data-trail-artist-id]",
    );
    if (!button) return;
    const artistId = Number(button.dataset.trailArtistId);
    if (Number.isNaN(artistId)) return;
    centerOn(artistId, undefined, { moveFocus: true });
  });

  centerOn(initialCenterArtistId, initialCenterLabel);
}
