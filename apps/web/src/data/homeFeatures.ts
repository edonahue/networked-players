// Build-time picks for the homepage. Both rules are deterministic functions
// of the published credit-membership artifact and reuse the album page's own
// `leadsTo` helper, so "a connection" means exactly what it means there:
// two records by different primary artists that share documented performers
// (ADR 0068 -- producers and engineers never count). No names are hardcoded.

import type { AlbumV2 } from "./challenge";
import { leadsTo, type LeadsTo, type Membership } from "./albumRecord";

export interface HomeFeatures {
  /** The record Explore opens on: most "leads to" connections; ties by
   * total shared players, then title, then id. */
  landing: { album: AlbumV2; leadCount: number };
  /** The cross-artist record pair with the most shared performers; ties by
   * the two ids so the pick never depends on iteration order. */
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

    // leadsTo is sorted best-first, so [0] is this record's strongest link.
    const top = leads[0];
    const other = top ? byId.get(top.albumId) : undefined;
    if (!top || !other) continue;
    const [a, b] = album.id < other.id ? [album, other] : [other, album];
    const better =
      !pair ||
      top.shared.length > pair.shared.length ||
      (top.shared.length === pair.shared.length &&
        (a.id < pair.a.id || (a.id === pair.a.id && b.id < pair.b.id)));
    if (better) pair = { a, b, shared: top.shared };
  }

  if (!landing) throw new Error("homeFeatures: no record has any connection");
  return {
    landing: { album: landing.album, leadCount: landing.leadCount },
    pair,
  };
}
