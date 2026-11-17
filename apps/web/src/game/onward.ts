// "Keep going" row for a RESOLVED game round (Atlas P4). Every game mode
// reveals its evidence sheet and then stops; this adds one quiet row of links
// out of the round: the records, the connecting players, and (for two-record
// rounds) the same pair pre-filled in Connect.
//
// Spoiler rule: this is only ever called from a mode's resolve step, and the
// mount is empty and `hidden` until then. Nothing here is part of the share
// string or of any stored state.
//
// URL forms are the site's existing ones: /albums/<id>/, /contributors/<id>/,
// /explore/<album-id>/?center=<artist-id> (as the header search and player
// page use) and /play/connect/?a=<id>&b=<id> (connectUrlState.ts).

import { escapeHtml } from "./domUtils";

export interface OnwardRecord {
  id: string;
  title: string;
}

export interface OnwardPlayer {
  id: number;
  name: string;
  /** A catalog record to open Explore on, centred on this player. */
  exploreAlbumId: string;
}

export interface OnwardInput {
  records: OnwardRecord[];
  players: OnwardPlayer[];
  /** Two-record rounds only: the pair to pre-fill in Connect. */
  connect?: { a: string; b: string };
}

/** Players named inline; any others are in the evidence sheet already. */
export const MAX_ONWARD_PLAYERS = 3;

const PLAYER_INDEX_URL = "/data/contributors/index.v1.json";

let playerPageIdsPromise: Promise<Set<number>> | null = null;

/** Artist ids that have a /contributors/<id>/ page. A failed fetch resolves to
 * an empty set: the Explore link still works, no page link is offered. */
export function loadPlayerPageIds(): Promise<Set<number>> {
  playerPageIdsPromise ??= (async (): Promise<Set<number>> => {
    try {
      const response = await fetch(PLAYER_INDEX_URL);
      if (!response.ok) return new Set();
      const index = (await response.json()) as {
        contributors: { artist_id: number }[];
      };
      return new Set(index.contributors.map((c) => c.artist_id));
    } catch {
      return new Set();
    }
  })();
  return playerPageIdsPromise;
}

export function onwardHtml(input: OnwardInput): string {
  const items: string[] = [];
  if (input.records.length > 0) {
    const links = input.records
      .map(
        (r) =>
          `<a class="onward__link" data-onward="record" href="/albums/${encodeURIComponent(r.id)}/">${escapeHtml(r.title)}</a>`,
      )
      .join("");
    items.push(
      `<li class="onward__group"><span class="onward__label">Records</span>${links}</li>`,
    );
  }
  const shown = input.players.slice(0, MAX_ONWARD_PLAYERS);
  for (const p of shown) {
    items.push(
      `<li class="onward__group" data-onward-player="${p.id}"><span class="onward__label">Player</span>` +
        `<a class="onward__link" data-onward="explore" href="/explore/${encodeURIComponent(p.exploreAlbumId)}/?center=${p.id}">Explore around ${escapeHtml(p.name)}</a>` +
        `<span data-onward-page-slot></span></li>`,
    );
  }
  const hidden = input.players.length - shown.length;
  if (hidden > 0) {
    items.push(
      `<li class="onward__note">${hidden} more ${hidden === 1 ? "player is" : "players are"} named in the liner notes.</li>`,
    );
  }
  if (input.connect) {
    const { a, b } = input.connect;
    items.push(
      `<li class="onward__group"><a class="onward__link" data-onward="connect" href="/play/connect/?a=${encodeURIComponent(a)}&amp;b=${encodeURIComponent(b)}">See this connection in Connect</a></li>`,
    );
  }
  return items.join("");
}

/** Fills and reveals `mount` (an element with a `<ul>` inside). Does not move
 * focus and does not announce: the verdict already did. The player-page links
 * arrive once the index has loaded, only for players that have a page. */
export function showOnward(mount: HTMLElement, input: OnwardInput): void {
  const list = mount.querySelector("ul");
  if (!list) return;
  list.innerHTML = onwardHtml(input);
  mount.hidden = false;
  void loadPlayerPageIds().then((ids) => {
    for (const p of input.players.slice(0, MAX_ONWARD_PLAYERS)) {
      if (!ids.has(p.id)) continue;
      const slot = list.querySelector(
        `[data-onward-player="${p.id}"] [data-onward-page-slot]`,
      );
      if (!slot) continue;
      const link = document.createElement("a");
      link.className = "onward__link";
      link.dataset.onward = "player";
      link.href = `/contributors/${p.id}/`;
      link.textContent = `${p.name}'s page`;
      slot.replaceWith(link);
    }
  });
}
