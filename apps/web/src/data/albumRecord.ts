// Build-time derivations for the album page ("the album page as a record"):
// the performer roster and the "where these players lead" list. Both come
// from the published album-credit-membership artifact
// (public/data/albums/credit-membership.v1.json, ADR 0058) -- no new
// artifact, no runtime fetch. Everything is memoized at module level because
// Astro evaluates the page frontmatter once per album.
//
// Honesty rules (ADR 0068): only performance credits (isPerformerRole) make
// a player "shared" between records. Producers, engineers, writers and a
// bare release-artist billing are shown as evidence but never counted.

import type { AlbumV2 } from "./challenge";
import {
  isPerformerRole,
  performanceCategory,
  PERFORMANCE_CATEGORY_LABEL as LABELS,
  PERFORMANCE_CATEGORY_ORDER,
} from "../game/roleTaxonomy";

export interface MembershipCredit {
  artist_id: number;
  name: string;
  anv: string | null;
  role_text: string | null;
  credit_scope:
    "release_artist" | "release_credit" | "track_artist" | "track_credit";
  track_position: string | null;
  track_title: string | null;
}

export interface Membership {
  albums: { album_id: string; credits: MembershipCredit[] }[];
}

export interface RosterPerson {
  artistId: number;
  /** Canonical PAN name with Discogs' "(N)" disambiguator removed. */
  name: string;
  /** As-credited text, only when it differs from the name. */
  anv: string | null;
  /** Distinct original role texts, verbatim. */
  roles: string[];
  /** Number of distinct tracks the credits are scoped to (0 = whole record). */
  trackCount: number;
}

export interface RosterGroup {
  key: string;
  label: string;
  people: RosterPerson[];
}

export interface AlbumRoster {
  performerCount: number;
  groups: RosterGroup[];
  /** Non-performance credits, one entry per person. */
  alsoCredited: RosterPerson[];
}

export interface LeadsTo {
  albumId: string;
  /** All shared performers, rarest-on-this-catalog first. */
  shared: { artistId: number; name: string }[];
}

export function displayName(name: string): string {
  return name.replace(/\s+\(\d+\)$/, "");
}

const BILLED_KEY = "billed";

function collect(
  rows: MembershipCredit[],
): Map<number, RosterPerson & { tracks: Set<string> }> {
  const byId = new Map<number, RosterPerson & { tracks: Set<string> }>();
  for (const row of rows) {
    let person = byId.get(row.artist_id);
    if (!person) {
      person = {
        artistId: row.artist_id,
        name: displayName(row.name),
        anv: null,
        roles: [],
        trackCount: 0,
        tracks: new Set(),
      };
      byId.set(row.artist_id, person);
    }
    if (row.anv && row.anv !== row.name && !person.anv) person.anv = row.anv;
    if (row.role_text && !person.roles.includes(row.role_text)) {
      person.roles.push(row.role_text);
    }
    if (row.track_position) person.tracks.add(row.track_position);
  }
  for (const person of byId.values()) person.trackCount = person.tracks.size;
  return byId;
}

const byName = (a: RosterPerson, b: RosterPerson) =>
  a.name.localeCompare(b.name) || a.artistId - b.artistId;

export function buildRoster(credits: MembershipCredit[]): AlbumRoster {
  const performerRows = credits.filter(
    (c) =>
      c.credit_scope !== "release_artist" && isPerformerRole(c.role_text ?? ""),
  );
  const performerIds = new Set(performerRows.map((c) => c.artist_id));

  const groups: RosterGroup[] = [];

  // Billed artists with no instrument credited anywhere on the record.
  const billedRows = credits.filter(
    (c) =>
      c.credit_scope === "release_artist" && !performerIds.has(c.artist_id),
  );
  const billed = [...collect(billedRows).values()].sort(byName);
  if (billed.length > 0) {
    groups.push({ key: BILLED_KEY, label: "Billed artist", people: billed });
  }

  for (const category of PERFORMANCE_CATEGORY_ORDER) {
    const rows = performerRows.filter(
      (c) => performanceCategory(c.role_text) === category,
    );
    if (rows.length === 0) continue;
    const people = [...collect(rows).values()].sort(byName);
    groups.push({ key: category, label: LABELS[category], people });
  }

  const alsoRows = credits.filter(
    (c) =>
      c.credit_scope !== "release_artist" &&
      c.role_text !== null &&
      !isPerformerRole(c.role_text),
  );
  const alsoCredited = [...collect(alsoRows).values()].sort(byName);

  return { performerCount: performerIds.size, groups, alsoCredited };
}

export interface Index {
  creditsByAlbum: Map<string, MembershipCredit[]>;
  performersByAlbum: Map<string, Map<number, string>>;
  albumsPerPerformer: Map<number, number>;
}

let cached: { source: Membership; index: Index } | null = null;

export function indexFor(membership: Membership): Index {
  if (cached && cached.source === membership) return cached.index;
  const creditsByAlbum = new Map<string, MembershipCredit[]>();
  const performersByAlbum = new Map<string, Map<number, string>>();
  const albumsPerPerformer = new Map<number, number>();
  for (const entry of membership.albums) {
    creditsByAlbum.set(entry.album_id, entry.credits);
    const performers = new Map<number, string>();
    for (const c of entry.credits) {
      if (c.credit_scope === "release_artist") continue;
      if (isPerformerRole(c.role_text ?? "")) {
        performers.set(c.artist_id, displayName(c.name));
      }
    }
    performersByAlbum.set(entry.album_id, performers);
    for (const id of performers.keys()) {
      albumsPerPerformer.set(id, (albumsPerPerformer.get(id) ?? 0) + 1);
    }
  }
  const index = { creditsByAlbum, performersByAlbum, albumsPerPerformer };
  cached = { source: membership, index };
  return index;
}

export function rosterFor(
  membership: Membership,
  albumId: string,
): AlbumRoster {
  return buildRoster(indexFor(membership).creditsByAlbum.get(albumId) ?? []);
}

/** Other catalog records that share documented performers with `album`.
 * Records by the same primary artist are excluded: a band's own albums share
 * their lineup by construction, which says nothing about where the players
 * lead. Ranked by shared-performer count, then by how rare the shared players
 * are across the catalog (a player on 2 records is a stronger lead than one on
 * 30), then by title for stability. */
export function leadsTo(
  membership: Membership,
  album: AlbumV2,
  allAlbums: AlbumV2[],
): LeadsTo[] {
  const { performersByAlbum, albumsPerPerformer } = indexFor(membership);
  const mine = performersByAlbum.get(album.id);
  if (!mine || mine.size === 0) return [];
  const scored: { lead: LeadsTo; score: number; title: string }[] = [];
  for (const other of allAlbums) {
    if (other.id === album.id || other.artist_id === album.artist_id) continue;
    const theirs = performersByAlbum.get(other.id);
    if (!theirs) continue;
    const shared: { artistId: number; name: string; rarity: number }[] = [];
    for (const [id, name] of mine) {
      if (theirs.has(id)) {
        shared.push({
          artistId: id,
          name,
          rarity: 1 / (albumsPerPerformer.get(id) ?? 1),
        });
      }
    }
    if (shared.length === 0) continue;
    shared.sort((a, b) => b.rarity - a.rarity || a.name.localeCompare(b.name));
    scored.push({
      lead: {
        albumId: other.id,
        shared: shared.map(({ artistId, name }) => ({ artistId, name })),
      },
      score: shared.reduce((n, s) => n + s.rarity, 0),
      title: other.title,
    });
  }
  scored.sort(
    (a, b) =>
      b.lead.shared.length - a.lead.shared.length ||
      b.score - a.score ||
      a.title.localeCompare(b.title),
  );
  return scored.map((s) => s.lead);
}
