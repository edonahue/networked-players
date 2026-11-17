// Record-centred Explore prototype (Campaign Atlas G2 / experiment E3):
// record -> its performers -> those players' other catalog records.
//
// Everything is derived from the published album-credit-membership artifact
// (ADR 0058) through albumRecord.ts's own index, so "performer" is decided by
// the one shared rule (roleTaxonomy.isPerformerRole, parity-tested against the
// Python rule). Producers, engineers, writers and a bare release-artist
// billing never connect two records (ADR 0068). Every ring-2 record is
// reachable only through a ring-1 player who has a performance credit on BOTH
// records, and each such credit is returned as evidence so the UI can show it
// verbatim in one click.
//
// Pure and DOM-free: the same builder runs at build time (the <noscript>
// fallback) and in the browser.

import {
  displayName,
  indexFor,
  type Membership,
  type MembershipCredit,
} from "./albumRecord";
import { isPerformerRole } from "../game/roleTaxonomy";

export interface RecordAlbum {
  id: string;
  title: string;
  artist: string;
  artist_id: number;
  year: number | null;
}

/** Hard ceiling on labelled nodes (centre + players + records). */
export const MAX_LABELLED_NODES = 24;
/** Ring-1 cap; ring 2 takes whatever the 24-node ceiling leaves. */
export const MAX_PLAYERS = 10;

export interface PlayerCredit {
  /** Verbatim Discogs role text. */
  role: string;
  track: string | null;
}

export interface RecordEvidence {
  albumId: string;
  title: string;
  artist: string;
  year: number | null;
  releaseId: number | null;
  credits: PlayerCredit[];
}

export interface PlayerNode {
  artistId: number;
  name: string;
  /** Number of catalog records this player has a performance credit on. */
  recordCount: number;
  /** Their credits on the centre record. */
  onCentre: PlayerCredit[];
}

export interface RecordNode {
  albumId: string;
  title: string;
  artist: string;
  year: number | null;
  /** Shown ring-1 players with a performance credit on this record. */
  sharedPlayerIds: number[];
}

export interface RecordView {
  centre: RecordAlbum & { releaseId: number | null };
  players: PlayerNode[];
  records: RecordNode[];
  /** Performers on the centre record not shown (cap). */
  morePlayers: number;
  /** Candidate records reached through the shown players but not shown. */
  moreRecords: number;
  totalPlayers: number;
}

function performerCredits(credits: MembershipCredit[]): PlayerCredit[] {
  const out: PlayerCredit[] = [];
  for (const c of credits) {
    if (c.credit_scope === "release_artist") continue;
    if (!isPerformerRole(c.role_text ?? "")) continue;
    out.push({ role: c.role_text ?? "", track: c.track_title ?? null });
  }
  return out;
}

function releaseIdsOf(membership: Membership): Map<string, number | null> {
  return new Map(
    membership.albums.map((a) => [
      a.album_id,
      (a as { main_release_id?: number }).main_release_id ?? null,
    ]),
  );
}

export function buildRecordView(
  membership: Membership,
  albums: RecordAlbum[],
  rankByArtistId: ReadonlyMap<number, number> | null,
  centreId: string,
): RecordView | null {
  const centre = albums.find((a) => a.id === centreId);
  if (!centre) return null;
  const { creditsByAlbum, performersByAlbum, albumsPerPerformer } =
    indexFor(membership);
  const releaseIds = releaseIdsOf(membership);
  const mine = performersByAlbum.get(centre.id) ?? new Map<number, string>();

  const ranked = [...mine.entries()].sort(
    ([ia, na], [ib, nb]) =>
      (rankByArtistId?.get(ib) ?? 0) - (rankByArtistId?.get(ia) ?? 0) ||
      (albumsPerPerformer.get(ib) ?? 0) - (albumsPerPerformer.get(ia) ?? 0) ||
      na.localeCompare(nb) ||
      ia - ib,
  );
  const shown = ranked.slice(0, MAX_PLAYERS);
  const centreCredits = creditsByAlbum.get(centre.id) ?? [];
  const players: PlayerNode[] = shown.map(([id, name]) => ({
    artistId: id,
    name,
    recordCount: albumsPerPerformer.get(id) ?? 0,
    onCentre: performerCredits(centreCredits.filter((c) => c.artist_id === id)),
  }));
  const shownIds = players.map((p) => p.artistId);

  // Ring 2: other records (not the centre; not the centre's own primary
  // artist, whose lineup is shared by construction -- the same exclusion as
  // the record page's "where these players lead") reached through SHOWN
  // players only, so every drawn link has a visible player behind it.
  const candidates: (RecordNode & { rarity: number })[] = [];
  for (const other of albums) {
    if (other.id === centre.id || other.artist_id === centre.artist_id) {
      continue;
    }
    const theirs = performersByAlbum.get(other.id);
    if (!theirs) continue;
    const shared = shownIds.filter((id) => theirs.has(id));
    if (shared.length === 0) continue;
    candidates.push({
      albumId: other.id,
      title: other.title,
      artist: other.artist,
      year: other.year,
      sharedPlayerIds: shared,
      rarity: shared.reduce(
        (n, id) => n + 1 / (albumsPerPerformer.get(id) ?? 1),
        0,
      ),
    });
  }
  candidates.sort(
    (a, b) =>
      b.sharedPlayerIds.length - a.sharedPlayerIds.length ||
      b.rarity - a.rarity ||
      a.title.localeCompare(b.title) ||
      a.albumId.localeCompare(b.albumId),
  );
  const recordCap = Math.max(0, MAX_LABELLED_NODES - 1 - players.length);
  const records: RecordNode[] = candidates
    .slice(0, recordCap)
    .map((c) => ({
      albumId: c.albumId,
      title: c.title,
      artist: c.artist,
      year: c.year,
      sharedPlayerIds: c.sharedPlayerIds,
    }));

  return {
    centre: { ...centre, releaseId: releaseIds.get(centre.id) ?? null },
    players,
    records,
    morePlayers: ranked.length - players.length,
    moreRecords: candidates.length - records.length,
    totalPlayers: ranked.length,
  };
}

/** Every performance credit `artistId` has on any catalog record, verbatim:
 * the evidence behind any player -> record link. Centre record first. */
export function playerEvidence(
  membership: Membership,
  albums: RecordAlbum[],
  artistId: number,
  centreId: string,
): RecordEvidence[] {
  const { creditsByAlbum } = indexFor(membership);
  const releaseIds = releaseIdsOf(membership);
  const out: RecordEvidence[] = [];
  for (const album of albums) {
    const credits = performerCredits(
      (creditsByAlbum.get(album.id) ?? []).filter(
        (c) => c.artist_id === artistId,
      ),
    );
    if (credits.length === 0) continue;
    out.push({
      albumId: album.id,
      title: album.title,
      artist: album.artist,
      year: album.year,
      releaseId: releaseIds.get(album.id) ?? null,
      credits,
    });
  }
  out.sort(
    (a, b) =>
      Number(b.albumId === centreId) - Number(a.albumId === centreId) ||
      a.title.localeCompare(b.title),
  );
  return out;
}

const esc = (s: string) =>
  s
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");

export function recordLabel(r: {
  title: string;
  artist: string;
  year: number | null;
}): string {
  return `${displayName(r.title)} — ${displayName(r.artist)}${r.year ? ` (${r.year})` : ""}`;
}

/** The same data as the graph, as plain HTML: used for the <noscript>
 * fallback (rendered at build time) and as the screen-reader/mobile list
 * beside the graph (rendered in the browser). */
export function renderRecordList(view: RecordView): string {
  const names = new Map(view.players.map((p) => [p.artistId, p.name]));
  const players = view.players
    .map((p) => {
      const roles = [...new Set(p.onCentre.map((c) => c.role))];
      return `<li>${esc(p.name)}${roles.length ? ` — ${esc(roles.join("; "))}` : ""}</li>`;
    })
    .join("");
  const records = view.records
    .map(
      (r) =>
        `<li><a href="/explore/${esc(r.albumId)}/?mode=record">${esc(recordLabel(r))}</a> — shared with ${esc(
          r.sharedPlayerIds.map((id) => names.get(id) ?? "").join(", "),
        )} · <a href="/albums/${esc(r.albumId)}/">record page</a></li>`,
    )
    .join("");
  const morePlayers =
    view.morePlayers > 0
      ? `<p>+${view.morePlayers} more documented performer${view.morePlayers === 1 ? "" : "s"} not shown.</p>`
      : "";
  const moreRecords =
    view.moreRecords > 0
      ? `<p>+${view.moreRecords} more record${view.moreRecords === 1 ? "" : "s"} share these players, not shown.</p>`
      : "";
  return (
    `<h3>Players documented performing on ${esc(recordLabel(view.centre))}</h3>` +
    (players
      ? `<ul>${players}</ul>`
      : "<p>No performance credits are documented for this record.</p>") +
    morePlayers +
    `<h3>Other records these players are documented on</h3>` +
    (records ? `<ul>${records}</ul>` : "<p>None in the catalog.</p>") +
    moreRecords +
    `<p>Each link is a documented performance credit, shown with its role text on the <a href="/albums/${esc(view.centre.id)}/">record page</a>. Credits are the evidence; a shared credit says nothing about influence.</p>`
  );
}
