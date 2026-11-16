// Build-time picks for the homepage. Both rules are deterministic functions
// of the published credit-membership artifact and reuse the album page's own
// `leadsTo` helper, so "a connection" means exactly what it means there:
// two records by different primary artists that share documented performers
// (ADR 0068 -- producers and engineers never count). No names are hardcoded.

import type { AlbumV2 } from "./challenge";
import { leadsTo, type LeadsTo, type Membership } from "./albumRecord";
import { performanceCategory } from "../game/roleTaxonomy";

/** Per album: the performers credited there with at least one performance
 * role outside the string section. Orchestral string players are documented
 * performers like anyone else and stay on every record page, but two records
 * that merely hired the same string section would otherwise always win the
 * homepage example, and that is the least telling kind of link to lead with. */
function nonSectionPerformers(
  membership: Membership,
): Map<string, Set<number>> {
  const byAlbum = new Map<string, Set<number>>();
  for (const { album_id, credits } of membership.albums) {
    const ids = new Set<number>();
    for (const credit of credits) {
      const category = performanceCategory(credit.role_text);
      if (category && category !== "strings") ids.add(credit.artist_id);
    }
    byAlbum.set(album_id, ids);
  }
  return byAlbum;
}

export interface HomeFeatures {
  /** The record Explore opens on: most "leads to" connections; ties by
   * total shared players, then title, then id. */
  landing: { album: AlbumV2; leadCount: number };
  /** The cross-artist record pair sharing the most performers credited
   * outside the string section on both records; ties by the two ids so the
   * pick never depends on iteration order. */
  pair: { a: AlbumV2; b: AlbumV2; shared: LeadsTo["shared"] } | null;
}

export function homeFeatures(
  membership: Membership,
  albums: AlbumV2[],
): HomeFeatures {
  let landing: {
    album: AlbumV2;
    leadCount: number;
    sharedTotal: number;
  } | null = null;
  let pair: {
    a: AlbumV2;
    b: AlbumV2;
    shared: LeadsTo["shared"];
  } | null = null;
  const byId = new Map(albums.map((a) => [a.id, a]));
  const nonSection = nonSectionPerformers(membership);

  for (const album of albums) {
    const leads = leadsTo(membership, album, albums);
    const sharedTotal = leads.reduce((n, l) => n + l.shared.length, 0);
    if (
      leads.length > 0 &&
      (!landing ||
        leads.length > landing.leadCount ||
        (leads.length === landing.leadCount &&
          (sharedTotal > landing.sharedTotal ||
            (sharedTotal === landing.sharedTotal &&
              (album.title.localeCompare(landing.album.title) < 0 ||
                (album.title === landing.album.title &&
                  album.id < landing.album.id))))))
    ) {
      landing = { album, leadCount: leads.length, sharedTotal };
    }

    const mine = nonSection.get(album.id);
    for (const lead of leads) {
      const other = byId.get(lead.albumId);
      const theirs = nonSection.get(lead.albumId);
      if (!other || !mine || !theirs) continue;
      const shared = lead.shared.filter(
        (p) => mine.has(p.artistId) && theirs.has(p.artistId),
      );
      if (shared.length === 0) continue;
      const [a, b] = album.id < other.id ? [album, other] : [other, album];
      const better =
        !pair ||
        shared.length > pair.shared.length ||
        (shared.length === pair.shared.length &&
          (a.id < pair.a.id || (a.id === pair.a.id && b.id < pair.b.id)));
      if (better) pair = { a, b, shared };
    }
  }

  if (!landing) throw new Error("homeFeatures: no record has any connection");
  return {
    landing: { album: landing.album, leadCount: landing.leadCount },
    pair,
  };
}
