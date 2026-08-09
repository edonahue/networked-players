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
  renderEvidenceHop,
  type EvidenceRelease,
} from "./connectEvidence";
import type { Contributor, ContributorIndex } from "../data/contributors";
import { ROLE_CATEGORY_LABEL } from "../data/contributors";

const EVIDENCE_REGISTRY_URL = "/data/evidence/release-registry.v1.json";

const VIEW_SIZE = 320;
const CENTER = VIEW_SIZE / 2;
const RADIUS = 120;
const NODE_RADIUS = 8;
const CENTER_NODE_RADIUS = 14;

function sessionStorageOrNull(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

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
  if (
    !svg ||
    !nodesLayer ||
    !edgesLayer ||
    !roleFilterEl ||
    !statusEl ||
    !truncatedEl ||
    !evidenceDrawer ||
    !evidenceContent ||
    !evidenceClose
  )
    return;

  const setStatus = (message: string | null) => {
    statusEl.hidden = !message;
    statusEl.textContent = message ?? "";
  };

  setStatus("Loading the network…");

  const graphResult = await loadPathfindingGraph(sessionStorageOrNull());
  if (!("graph" in graphResult)) {
    setStatus("Couldn't load the network graph. Try reloading the page.");
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

  // The evidence-release registry (~57 KB gzipped, ADR 0058 Slice 3) is
  // fetched lazily on first edge interaction, not on page load -- most
  // visits to Explore never open the drawer at all. Cached as a promise
  // (not just the resolved map) so a second interaction while the first
  // fetch is still in flight doesn't trigger a duplicate request.
  let evidenceIndexPromise: Promise<Map<number, EvidenceRelease>> | null = null;
  async function fetchEvidenceIndex(): Promise<Map<number, EvidenceRelease>> {
    try {
      const response = await fetch(EVIDENCE_REGISTRY_URL);
      if (!response.ok) return new Map();
      return buildEvidenceIndex(await response.json());
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

    edgesLayer!.innerHTML = view.edges
      .map((edge) => {
        const from = nodePositions.get(view.center.artistId)!;
        const to = nodePositions.get(edge.neighborArtistId)!;
        const neighborName =
          nodeNameById.get(edge.neighborArtistId) ?? "this contributor";
        return (
          `<line x1="${from.x}" y1="${from.y}" x2="${to.x}" y2="${to.y}" class="explorer-edge" ` +
          `data-neighbor-id="${edge.neighborArtistId}" data-release-id="${edge.releaseId}" ` +
          `data-role-center="${escapeHtml(edge.roleCenter)}" data-role-neighbor="${escapeHtml(edge.roleNeighbor)}" ` +
          `tabindex="0" role="button" ` +
          `aria-label="Evidence for the documented credit between ${escapeHtml(view.center.name)} and ${escapeHtml(neighborName)}" />`
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
      return (
        `<g class="explorer-node${dimmed ? " explorer-node--dimmed" : ""}" ` +
        `data-artist-id="${node.artistId}" data-is-center="${node.isCenter}" tabindex="${node.isCenter ? "0" : "-1"}" role="button" ` +
        `aria-label="${escapeHtml(node.name)}${node.isCenter ? " (center)" : ""}">` +
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
    hideEvidenceDrawer();
    renderRoleFilter(view);
    renderView(view);
    // Announce the new center -- rebuilding the SVG destroys whatever was
    // previously focused, so without this a screen reader gets no signal
    // the view changed at all.
    setStatus(`Centered on ${view.center.name}.`);
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

  function hideEvidenceDrawer() {
    evidenceDrawer!.hidden = true;
    evidenceContent!.innerHTML = "";
  }

  async function showEdgeEvidence(edgeEl: SVGLineElement) {
    const neighborId = Number(edgeEl.dataset.neighborId);
    const releaseId = Number(edgeEl.dataset.releaseId);
    const roleCenter = edgeEl.dataset.roleCenter ?? "";
    const roleNeighbor = edgeEl.dataset.roleNeighbor ?? "";
    if (!currentView || Number.isNaN(neighborId) || Number.isNaN(releaseId))
      return;

    const requestId = ++openEdgeRequestId;
    evidenceDrawer!.hidden = false;
    evidenceContent!.innerHTML = "<p>Loading evidence…</p>";

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
  }

  edgesLayer.addEventListener("click", (event) => {
    const target = (event.target as Element).closest<SVGLineElement>(
      "[data-release-id]",
    );
    if (!target) return;
    void showEdgeEvidence(target);
  });
  edgesLayer.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const target = (event.target as Element).closest<SVGLineElement>(
      "[data-release-id]",
    );
    if (!target) return;
    event.preventDefault();
    void showEdgeEvidence(target);
  });
  // "mouseover"/"focusin" (not "mouseenter"/"focus") because both bubble,
  // letting one delegated listener on the layer cover every edge without
  // attaching a handler per `<line>` on every render.
  edgesLayer.addEventListener("mouseover", (event) => {
    const target = (event.target as Element).closest<SVGLineElement>(
      "[data-release-id]",
    );
    if (!target) return;
    void showEdgeEvidence(target);
  });
  edgesLayer.addEventListener("focusin", (event) => {
    const target = (event.target as Element).closest<SVGLineElement>(
      "[data-release-id]",
    );
    if (!target) return;
    void showEdgeEvidence(target);
  });
  evidenceClose.addEventListener("click", () => hideEvidenceDrawer());
  // Document-level, not scoped to the drawer's own focus: a hover-opened
  // drawer never moves real DOM focus at all, so a listener attached only
  // to the drawer element would never see the Escape keydown a visitor
  // presses right after hovering (as opposed to clicking) an edge.
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !evidenceDrawer!.hidden) hideEvidenceDrawer();
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
    if (nodes.length === 0) return;
    const current = document.activeElement as SVGGElement | null;
    const index = Math.max(0, nodes.indexOf(current as SVGGElement));
    const delta =
      event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : -1;
    const next = nodes[(index + delta + nodes.length) % nodes.length];
    for (const node of nodes) node.tabIndex = -1;
    next.tabIndex = 0;
    next.focus();
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

  centerOn(initialArtistId, stage.dataset.initialLabel);
}
