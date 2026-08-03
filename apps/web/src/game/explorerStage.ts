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
import type { Contributor, ContributorIndex } from "../data/contributors";
import { ROLE_CATEGORY_LABEL } from "../data/contributors";

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
  if (
    !svg ||
    !nodesLayer ||
    !edgesLayer ||
    !roleFilterEl ||
    !statusEl ||
    !truncatedEl
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

    edgesLayer!.innerHTML = view.edges
      .map((edge) => {
        const from = nodePositions.get(view.center.artistId)!;
        const to = nodePositions.get(edge.neighborArtistId)!;
        return `<line x1="${from.x}" y1="${from.y}" x2="${to.x}" y2="${to.y}" class="explorer-edge" data-neighbor-id="${edge.neighborArtistId}" />`;
      })
      .join("");

    const renderNode = (node: ExplorerNode) => {
      const pos = nodePositions.get(node.artistId)!;
      const dimmed = isDimmed(node, activeCategories);
      const r = node.isCenter ? CENTER_NODE_RADIUS : NODE_RADIUS;
      return (
        `<g class="explorer-node${dimmed ? " explorer-node--dimmed" : ""}" ` +
        `data-artist-id="${node.artistId}" data-is-center="${node.isCenter}" tabindex="0" role="button" ` +
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

  function centerOn(artistId: number, label?: string) {
    const view = buildView(graph, artistIndex, contributorByArtistId, artistId);
    if (!view) {
      setStatus(
        `${label ?? "This artist"} isn't in the documented network graph yet.`,
      );
      return;
    }
    setStatus(null);
    activeCategories = new Set();
    currentView = view;
    renderRoleFilter(view);
    renderView(view);
  }

  nodesLayer.addEventListener("click", (event) => {
    const target = (event.target as Element).closest<SVGGElement>(
      "[data-artist-id]",
    );
    if (!target || target.dataset.artistId === undefined) return;
    centerOn(Number(target.dataset.artistId));
  });
  nodesLayer.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const target = (event.target as Element).closest<SVGGElement>(
      "[data-artist-id]",
    );
    if (!target) return;
    event.preventDefault();
    centerOn(Number(target.dataset.artistId));
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
