// Record-centred Explore prototype stage (Campaign Atlas G2 / experiment E3),
// reached only through /explore/<album>/?mode=record. Draws a centre record,
// ring 1 (its performers) and ring 2 (those players' other catalog records)
// from the same artifacts the record page uses. Not linked from anywhere.
//
// Reuses already-published artifacts only (no new data): credit-membership
// (ADR 0058), the catalog album list, and the prominence sidecar the default
// Explore also fetches. Clicking a player opens their credits (verbatim role
// text, link to the Discogs release); clicking a record recenters.
//
// Layout is deterministic and avoids label collisions by construction:
// labelled nodes sit on left/right arcs only (never stacked along the top or
// bottom where wide labels would meet), labels are side-anchored and
// ellipsized, and the Playwright gate test asserts no label boxes overlap.

import type { Membership } from "../data/albumRecord";
import {
  buildRecordView,
  playerEvidence,
  recordLabel,
  renderRecordList,
  type PlayerNode,
  type RecordAlbum,
  type RecordNode,
  type RecordView,
} from "../data/recordExplorer";
import { displayName } from "../data/albumRecord";
import { escapeHtml, fetchFailureMessage } from "./domUtils";
import { moveRovingFocus } from "./explorerStage";

const MEMBERSHIP_URL = "/data/albums/credit-membership.v1.json";
const ALBUMS_URL = "/data/catalog/albums.v1.json";
const PROMINENCE_URL = "/data/pathfinding/prominence.v1.json";
const MOBILE_QUERY = "(max-width: 640px)";
const MAX_EVIDENCE_RECORDS = 12;

interface Pt {
  x: number;
  y: number;
}

/** Wraps text into at most two lines of `max` characters so the visible
 * label is the real name (an ellipsis would break the visible-text-in-name
 * accessibility rule). Only a name too long even for two lines is cut. */
function wrapLabel(text: string, max: number): string[] {
  if (text.length <= max) return [text];
  const words = text.split(/\s+/);
  let first = "";
  let i = 0;
  while (i < words.length && (first + " " + words[i]).trim().length <= max) {
    first = (first + " " + words[i]).trim();
    i++;
  }
  if (first === "") {
    first = words[0].slice(0, max);
    words[0] = words[0].slice(max);
  }
  let rest = words.slice(i).join(" ");
  if (rest.length > max) rest = `${rest.slice(0, max - 1).trimEnd()}…`;
  return rest ? [first, rest] : [first];
}

/** n angles (radians) spread over [-spread, +spread], centred on 0. */
function spreadAngles(n: number, spreadDeg: number): number[] {
  if (n <= 0) return [];
  if (n === 1) return [0];
  return Array.from(
    { length: n },
    (_, i) => ((-spreadDeg + (2 * spreadDeg * i) / (n - 1)) * Math.PI) / 180,
  );
}

interface Placed<T> {
  item: T;
  pos: Pt;
  side: "left" | "right";
}

/** Items alternate right/left by rank; each side is spread top to bottom. */
function placeOnArcs<T>(
  items: T[],
  centre: Pt,
  rx: number,
  ry: number,
  spreadDeg: number,
): Placed<T>[] {
  const right = items.filter((_, i) => i % 2 === 0);
  const left = items.filter((_, i) => i % 2 === 1);
  const out: Placed<T>[] = [];
  for (const [side, group] of [
    ["right", right],
    ["left", left],
  ] as const) {
    const sign = side === "right" ? 1 : -1;
    spreadAngles(group.length, spreadDeg).forEach((a, i) => {
      out.push({
        item: group[i],
        side,
        pos: {
          x: centre.x + sign * rx * Math.cos(a),
          y: centre.y + ry * Math.sin(a),
        },
      });
    });
  }
  return out;
}

export async function initRecordExplorer(): Promise<void> {
  const root = document.querySelector<HTMLElement>("[data-record-explorer]");
  if (!root) return;
  const q = <T extends Element>(sel: string) => root.querySelector<T>(sel);
  const svg = q<SVGSVGElement>("[data-record-svg]");
  const nodesLayer = q<SVGGElement>("[data-record-nodes]");
  const edgesLayer = q<SVGGElement>("[data-record-edges]");
  const statusEl = q<HTMLElement>("[data-record-status]");
  const alertEl = q<HTMLElement>("[data-record-alert]");
  const moreEl = q<HTMLElement>("[data-record-more]");
  const listEl = q<HTMLElement>("[data-record-list]");
  const drawer = q<HTMLElement>("[data-record-drawer]");
  const drawerContent = q<HTMLElement>("[data-record-drawer-content]");
  const drawerClose = q<HTMLButtonElement>("[data-record-drawer-close]");
  if (
    !svg ||
    !nodesLayer ||
    !edgesLayer ||
    !statusEl ||
    !alertEl ||
    !moreEl ||
    !listEl ||
    !drawer ||
    !drawerContent ||
    !drawerClose
  )
    return;

  const pageAlbumId = root.dataset.albumId ?? "";
  const isMobile =
    typeof window.matchMedia === "function" &&
    window.matchMedia(MOBILE_QUERY).matches;
  const h1 = document.querySelector<HTMLElement>(".h1-intro");
  const baseTitle = document.title;

  const setStatus = (msg: string | null) => {
    statusEl.hidden = !msg;
    statusEl.textContent = msg ?? "";
  };
  setStatus("Loading the record's players…");

  let membership: Membership;
  let albums: RecordAlbum[];
  let rank: Map<number, number> | null = null;
  try {
    const [mRes, aRes, pRes] = await Promise.all([
      fetch(MEMBERSHIP_URL),
      fetch(ALBUMS_URL),
      fetch(PROMINENCE_URL).catch(() => null),
    ]);
    if (!mRes.ok || !aRes.ok) throw new Error("fetch failed");
    membership = (await mRes.json()) as Membership;
    albums = ((await aRes.json()) as { albums: RecordAlbum[] }).albums;
    if (pRes && pRes.ok) {
      const p = (await pRes.json()) as { node_ids: number[]; rank: number[] };
      rank = new Map(p.node_ids.map((id, i) => [id, p.rank[i]]));
    }
  } catch {
    const msg = fetchFailureMessage("the record credits");
    root.dataset.phase = "error";
    setStatus(msg);
    alertEl.textContent = msg;
    svg.setAttribute("hidden", "");
    svg.style.display = "none";
    return;
  }

  const albumIds = new Set(albums.map((a) => a.id));
  let view: RecordView | null = null;
  let triggerEl: Element | null = null;
  let drawerRequest = 0;

  function closeDrawer(restoreFocus: boolean) {
    drawerRequest++;
    drawer!.hidden = true;
    drawerContent!.innerHTML = "";
    if (restoreFocus && triggerEl instanceof SVGElement) triggerEl.focus();
    triggerEl = null;
  }

  function draw(v: RecordView) {
    const W = isMobile ? 360 : 900;
    const maxPlayer = isMobile ? 18 : 16;
    const maxRecord = isMobile ? 20 : 16;
    const maxCentre = isMobile ? 30 : 28;
    const nodeR = isMobile ? 11 : 9;
    const centreR = isMobile ? 14 : 16;

    const positions = new Map<string, Pt>();
    const players: Placed<PlayerNode>[] = [];
    const records: Placed<RecordNode>[] = [];
    let centrePos: Pt;
    let height: number;
    const headers: string[] = [];

    if (isMobile) {
      centrePos = { x: 180, y: 26 };
      const rowH = 36;
      const top = 96;
      v.players.forEach((p, i) =>
        players.push({
          item: p,
          pos: { x: 22, y: top + i * rowH },
          side: "right",
        }),
      );
      v.records.forEach((r, i) =>
        records.push({
          item: r,
          pos: { x: 196, y: top + i * rowH },
          side: "right",
        }),
      );
      const rows = Math.max(v.players.length, v.records.length, 1);
      height = top + rows * rowH;
      headers.push(
        `<text class="record-ring-title" x="14" y="74">Players</text>`,
        `<text class="record-ring-title" x="188" y="74">Their other records</text>`,
      );
    } else {
      centrePos = { x: 450, y: 300 };
      height = 600;
      players.push(...placeOnArcs(v.players, centrePos, 120, 190, 50));
      records.push(...placeOnArcs(v.records, centrePos, 300, 270, 40));
    }
    for (const p of players) positions.set(`p${p.item.artistId}`, p.pos);
    positions.set("c", centrePos);

    svg!.setAttribute("viewBox", `0 0 ${W} ${height}`);
    svg!.style.aspectRatio = `${W} / ${height}`;

    const edges: string[] = [];
    if (!isMobile) {
      for (const p of players) {
        edges.push(
          `<line class="record-edge record-edge--centre" x1="${centrePos.x}" y1="${centrePos.y}" x2="${p.pos.x}" y2="${p.pos.y}" />`,
        );
      }
    }
    for (const r of records) {
      for (const id of r.item.sharedPlayerIds) {
        const from = positions.get(`p${id}`);
        if (!from) continue;
        edges.push(
          `<line class="record-edge" x1="${from.x}" y1="${from.y}" x2="${r.pos.x}" y2="${r.pos.y}" />`,
        );
      }
    }
    edgesLayer!.innerHTML = edges.join("");

    const label = (
      text: string,
      max: number,
      pos: Pt,
      r: number,
      side: "left" | "right",
      anchorBelow = false,
    ) => {
      const lines = wrapLabel(text, max);
      const x = anchorBelow
        ? pos.x
        : pos.x + (side === "right" ? r + 6 : -(r + 6));
      const y0 = anchorBelow
        ? pos.y + r + 16
        : pos.y + 4 - ((lines.length - 1) * 13) / 2;
      const anchor = anchorBelow
        ? "middle"
        : side === "right"
          ? "start"
          : "end";
      const spans = lines
        .map(
          (l, i) =>
            `<tspan x="${x}" dy="${i === 0 ? 0 : 13}">${escapeHtml(l)}${i < lines.length - 1 ? " " : ""}</tspan>`,
        )
        .join("");
      return `<text class="record-label" x="${x}" y="${y0}" text-anchor="${anchor}">${spans}</text>`;
    };

    const centreName = recordLabelShort(v.centre.title);
    const centreNode =
      `<g class="explorer-node record-node" data-kind="centre" data-is-center="true" role="img" aria-label="${escapeHtml(`Centre record: ${recordLabel(v.centre)}`)}">` +
      `<circle cx="${centrePos.x}" cy="${centrePos.y}" r="${centreR}" />` +
      label(centreName, maxCentre, centrePos, centreR, "right", true) +
      `</g>`;

    const playerNodes = players.map(({ item, pos, side }, i) => {
      const credits = item.onCentre.length;
      return (
        `<g class="explorer-node record-node record-node--player" data-kind="player" data-artist-id="${item.artistId}" ` +
        `tabindex="${i === 0 ? 0 : -1}" role="button" ` +
        `aria-label="${escapeHtml(`${item.name}: show credits and records (${credits} credit${credits === 1 ? "" : "s"} on this record, ${item.recordCount} record${item.recordCount === 1 ? "" : "s"} in the catalog)`)}">` +
        `<circle cx="${pos.x}" cy="${pos.y}" r="${nodeR}" />` +
        label(item.name, maxPlayer, pos, nodeR, side) +
        `</g>`
      );
    });
    const recordNodes = records.map(({ item, pos, side }) => {
      const names = item.sharedPlayerIds
        .map((id) => v.players.find((p) => p.artistId === id)?.name ?? "")
        .join(", ");
      return (
        `<g class="explorer-node record-node record-node--record" data-kind="record" data-album-id="${escapeHtml(item.albumId)}" ` +
        `tabindex="-1" role="button" ` +
        `aria-label="${escapeHtml(`Recenter on ${recordLabel(item)}. Shares ${item.sharedPlayerIds.length} player${item.sharedPlayerIds.length === 1 ? "" : "s"}: ${names}`)}">` +
        `<circle cx="${pos.x}" cy="${pos.y}" r="${nodeR}" />` +
        label(displayName(item.title), maxRecord, pos, nodeR, side) +
        `</g>`
      );
    });
    nodesLayer!.innerHTML =
      headers.join("") +
      centreNode +
      playerNodes.join("") +
      recordNodes.join("");

    const notes: string[] = [];
    if (v.morePlayers > 0) {
      notes.push(
        `Showing the ${v.players.length} most prominent of ${v.totalPlayers} documented performers (+${v.morePlayers} more).`,
      );
    }
    if (v.moreRecords > 0) {
      notes.push(
        `+${v.moreRecords} more record${v.moreRecords === 1 ? "" : "s"} share these players.`,
      );
    }
    if (v.players.length === 0) {
      notes.push("No performance credits are documented for this record.");
    }
    moreEl!.hidden = notes.length === 0;
    moreEl!.textContent = notes.join(" ");
    listEl!.innerHTML = renderRecordList(v);
  }

  function recordLabelShort(title: string): string {
    return displayName(title);
  }

  function setUrl(albumId: string, mode: "push" | "replace" | "skip") {
    if (mode === "skip") return;
    const url = new URL(window.location.href);
    url.searchParams.set("mode", "record");
    url.searchParams.set("record", albumId);
    const state = { record: albumId };
    if (mode === "replace") history.replaceState(state, "", url);
    else history.pushState(state, "", url);
  }

  function centerOn(
    albumId: string,
    opts: { history: "push" | "replace" | "skip"; moveFocus?: boolean },
  ) {
    const next = buildRecordView(membership, albums, rank, albumId);
    if (!next) return;
    closeDrawer(false);
    view = next;
    draw(next);
    root!.dataset.phase = "ready";
    root!.dataset.centreAlbumId = albumId;
    const label = recordLabel(next.centre);
    setStatus(
      `Centred on ${label}: ${next.players.length} player${next.players.length === 1 ? "" : "s"}, ${next.records.length} other record${next.records.length === 1 ? "" : "s"}.`,
    );
    if (h1) h1.textContent = displayName(next.centre.title);
    document.title = `Explore: ${displayName(next.centre.title)}`;
    if (!document.title) document.title = baseTitle;
    setUrl(albumId, opts.history);
    if (opts.moveFocus) {
      (
        nodesLayer!.querySelector<SVGGElement>("[data-kind='player']") ?? null
      )?.focus();
    }
  }

  function showPlayer(el: SVGGElement) {
    if (!view) return;
    const artistId = Number(el.dataset.artistId);
    const player = view.players.find((p) => p.artistId === artistId);
    if (!player) return;
    triggerEl = el;
    const ev = playerEvidence(membership, albums, artistId, view.centre.id);
    const shown = ev.slice(0, MAX_EVIDENCE_RECORDS);
    const items = shown
      .map((r) => {
        const roles = r.credits
          .map(
            (c) =>
              `<li>${escapeHtml(c.role)}${c.track ? ` <span class="record-credit-track">— ${escapeHtml(c.track)}</span>` : ""}</li>`,
          )
          .join("");
        const discogs =
          r.releaseId !== null
            ? ` · <a href="https://www.discogs.com/release/${r.releaseId}" rel="noopener noreferrer">Discogs release</a>`
            : "";
        const recenter =
          r.albumId !== view!.centre.id && albumIds.has(r.albumId)
            ? ` · <button type="button" class="chip" data-record-recenter="${escapeHtml(r.albumId)}">Explore from this record</button>`
            : " · (centre record)";
        return (
          `<li class="record-evidence-record"><a href="/albums/${escapeHtml(r.albumId)}/">${escapeHtml(recordLabel(r))}</a>${discogs}${recenter}` +
          `<ul>${roles}</ul></li>`
        );
      })
      .join("");
    const more =
      ev.length > shown.length
        ? `<p>+${ev.length - shown.length} more record${ev.length - shown.length === 1 ? "" : "s"} with a documented performance credit.</p>`
        : "";
    drawerContent!.innerHTML =
      `<h2 class="record-drawer-title">${escapeHtml(player.name)}</h2>` +
      `<p>Documented performance credits, with the original role text. A shared credit connects records; it does not say anything about influence. ` +
      `<a href="https://www.discogs.com/artist/${player.artistId}" rel="noopener noreferrer">Discogs artist page</a></p>` +
      `<ul class="record-evidence-list">${items}</ul>${more}`;
    drawer!.hidden = false;
    drawer!.focus();
  }

  nodesLayer.addEventListener("click", (event) => {
    const node = (event.target as Element).closest<SVGGElement>("[data-kind]");
    if (!node) return;
    activate(node);
  });
  nodesLayer.addEventListener("keydown", (event) => {
    const node = (event.target as Element).closest<SVGGElement>("[data-kind]");
    if (!node) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      activate(node);
    } else if (
      ["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp"].includes(event.key)
    ) {
      event.preventDefault();
      moveRovingFocus(
        [
          ...nodesLayer.querySelectorAll<SVGGElement>(
            "[data-kind='player'], [data-kind='record']",
          ),
        ],
        event.key,
      );
    }
  });
  function activate(node: SVGGElement) {
    if (node.dataset.kind === "player") showPlayer(node);
    else if (node.dataset.kind === "record" && node.dataset.albumId) {
      centerOn(node.dataset.albumId, { history: "push", moveFocus: true });
    }
  }
  drawerContent.addEventListener("click", (event) => {
    const btn = (event.target as Element).closest<HTMLElement>(
      "[data-record-recenter]",
    );
    if (btn?.dataset.recordRecenter) {
      centerOn(btn.dataset.recordRecenter, {
        history: "push",
        moveFocus: true,
      });
    }
  });
  drawerClose.addEventListener("click", () => closeDrawer(true));
  root.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !drawer.hidden) closeDrawer(true);
  });

  window.addEventListener("popstate", () => {
    const requested = new URLSearchParams(window.location.search).get("record");
    const id = requested && albumIds.has(requested) ? requested : pageAlbumId;
    if (albumIds.has(id)) centerOn(id, { history: "skip" });
  });

  const requested = new URLSearchParams(window.location.search).get("record");
  const start =
    requested && albumIds.has(requested)
      ? requested
      : albumIds.has(pageAlbumId)
        ? pageAlbumId
        : (albums[0]?.id ?? "");
  centerOn(start, { history: "replace" });
}
