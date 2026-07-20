// Client-side rendering for the flagship game (/guess/) and Connection of the
// Day (/daily/). rounds.v1.json is fetched at runtime, not bundled -- at real
// launch scale it is well over Astro's reasonable per-page budget, per
// ADR 0002's static-first posture (no live API required, but a large
// optional artifact may still be fetched lazily). universe.v1.json is small
// enough to import at build time in each page; this module only needs it
// passed in for album lookups.

import type { Round, RoundsV1, UniverseV1 } from "../data/rounds";

export async function fetchRounds(): Promise<RoundsV1> {
  const response = await fetch("/data/game/rounds.v1.json");
  if (!response.ok) {
    throw new Error(`failed to load rounds.v1.json: ${response.status}`);
  }
  return (await response.json()) as RoundsV1;
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

const SCOPE_LABEL: Record<string, string> = {
  release_artist: "release artist",
  release_credit: "release credit",
  track_artist: "track artist",
  track_credit: "track credit",
};

function albumCardHtml(albumId: string, universe: UniverseV1): string {
  const album = universe.albums.find((a) => a.id === albumId);
  if (!album) {
    return `<div class="evidence-card__endpoint"><span>${escapeHtml(albumId)}</span></div>`;
  }
  const cover = album.cover_image
    ? `<img class="cover-thumb" src="${escapeHtml(album.cover_image.uri150)}" width="56" height="56" loading="lazy" alt="" />`
    : "";
  return `<div class="evidence-card__endpoint">${cover}<span>${escapeHtml(album.title)}<br /><small>${escapeHtml(album.artist)}${album.year ? ` &middot; ${album.year}` : ""}</small></span></div>`;
}

function hopHtml(round: Round, rounds: RoundsV1, hopIndex: number): string {
  const hop = round.hops[hopIndex];
  const release = rounds.releases.find((r) => r.release_id === hop.release_id);
  const nameFor = (artistId: number) =>
    rounds.artists.find((a) => a.artist_id === artistId)?.name ??
    `Artist ${artistId}`;

  if (!release) return "";

  const endpoints = new Set([hop.artist_a_id, hop.artist_b_id]);
  const evidenceRows = release.credits.filter(
    (c) => c.artist_id !== null && endpoints.has(c.artist_id),
  );
  const rows = evidenceRows
    .map((c) => {
      const scope = SCOPE_LABEL[c.credit_scope] ?? c.credit_scope;
      return `<tr><td>${escapeHtml(c.name)}${c.anv ? ` (as <em>${escapeHtml(c.anv)}</em>)` : ""}</td><td>${escapeHtml(scope)}</td><td>${escapeHtml(c.role_text ?? "—")}</td></tr>`;
    })
    .join("");

  return `
    <div class="hop">
      <p class="hop__title">Hop ${hopIndex + 1}: ${escapeHtml(nameFor(hop.artist_a_id))} (${escapeHtml(hop.role_a)}) and ${escapeHtml(nameFor(hop.artist_b_id))} (${escapeHtml(hop.role_b)})</p>
      <p class="hop__release">both credited on <strong>${escapeHtml(release.title)}</strong>${release.released ? ` (${escapeHtml(release.released)})` : ""} &middot; <a href="${escapeHtml(release.source_url)}" rel="nofollow noopener">source</a></p>
      <div class="evidence">
        <table>
          <caption>Release ${hop.release_id} &middot; evidence</caption>
          <thead><tr><th scope="col">Credited as</th><th scope="col">Scope</th><th scope="col">Role</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>`;
}

export function renderRound(
  round: Round,
  universe: UniverseV1,
  rounds: RoundsV1,
  container: HTMLElement,
): void {
  const revealId = `round-evidence-${round.id}`;
  const hopsHtml = round.hops.map((_, i) => hopHtml(round, rounds, i)).join("");
  const kindLabel = round.kind === "one_hop" ? "1 hop" : "2 hops";

  container.innerHTML = `
    <article class="evidence-card" data-round-id="${escapeHtml(round.id)}">
      <div class="evidence-card__summary">
        ${albumCardHtml(round.from_album_id, universe)}
        <span class="arrow" aria-hidden="true">&rarr;</span>
        ${albumCardHtml(round.to_album_id, universe)}
      </div>
      <p class="path-card__sub">
        <span class="tag tag--difficulty">${escapeHtml(round.difficulty)}</span>
        <span class="tag">${kindLabel}</span>
      </p>
      <button
        type="button"
        class="cohort-pair__reveal"
        data-round-reveal-button
        aria-expanded="false"
        aria-controls="${revealId}"
      >Reveal the connection</button>
      <div id="${revealId}" class="round-evidence" hidden>${hopsHtml}</div>
    </article>`;

  const button = container.querySelector<HTMLButtonElement>(
    "[data-round-reveal-button]",
  );
  const evidence = container.querySelector<HTMLElement>(
    `#${CSS.escape(revealId)}`,
  );
  button?.addEventListener("click", () => {
    const revealed = button.getAttribute("aria-expanded") === "true";
    button.setAttribute("aria-expanded", String(!revealed));
    button.textContent = revealed
      ? "Reveal the connection"
      : "Hide the connection";
    evidence?.toggleAttribute("hidden", revealed);
  });
}

export function pickRandomRound(rounds: RoundsV1, excludeId?: string): Round {
  const pool = excludeId
    ? rounds.rounds.filter((r) => r.id !== excludeId)
    : rounds.rounds;
  const source = pool.length > 0 ? pool : rounds.rounds;
  const index = Math.floor(Math.random() * source.length);
  return source[index];
}

export function todayUtcDate(): string {
  return new Date().toISOString().slice(0, 10);
}
