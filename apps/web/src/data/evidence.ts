// Normalized hop-evidence views for EvidencePanel.astro (plan §12.7): the
// challenge.v1 demo, the challenge.v2 album pages, and the playable-cohort
// pages all reduce to this one shape, so a documented connection renders the
// same way everywhere it appears.

import type { Credit } from "./challenge";

export const SCOPE_LABEL: Record<Credit["credit_scope"], string> = {
  release_artist: "release artist",
  release_credit: "release credit",
  track_artist: "track artist",
  track_credit: "track credit",
};

/** One credit row that places an endpoint on the hop's release. */
export interface PanelRow {
  name: string;
  anv: string | null;
  trackPosition: string | null;
  scope: string;
  role: string | null;
  artistId: number;
}

/** One hop, ready to render: names, release line, optional rows and cover. */
export interface PanelHop {
  index: number;
  aName: string;
  bName: string;
  release: {
    ref: string;
    title: string;
    released: string | null;
    country: string | null;
    sourceUrl: string | null;
  };
  coverUri: string | null;
  rows: PanelRow[];
  nonLinked: { name: string; role: string | null }[];
  /** Cohort hops carry quality flags instead of per-credit rows. */
  flagsLine: string | null;
}

/** The release fields both challenge shapes share. */
interface CreditRelease {
  release_id: number;
  title: string;
  released: string | null;
  country: string | null;
  source_url: string;
  credits: Credit[];
  images?: { uri150: string }[];
}

/** Build hop views from credit-bearing releases (challenge.v1 and .v2). */
export function buildHopViews(
  hops: { release_id: number; artist_a_id: number; artist_b_id: number }[],
  releases: CreditRelease[],
  artists: { artist_id: number; name: string }[],
  options: { covers?: boolean } = {},
): PanelHop[] {
  const releaseById = new Map(releases.map((r) => [r.release_id, r]));
  const nameById = new Map(artists.map((a) => [a.artist_id, a.name]));
  const displayName = (id: number) => nameById.get(id) ?? `Artist ${id}`;
  const views: PanelHop[] = [];
  hops.forEach((hop, i) => {
    const release = releaseById.get(hop.release_id);
    if (!release) return;
    const endpoints = [hop.artist_a_id, hop.artist_b_id];
    const rows: PanelRow[] = release.credits
      .filter((c) => c.artist_id !== null && endpoints.includes(c.artist_id))
      .map((c) => ({
        name: c.name,
        anv: c.anv,
        trackPosition: c.track_position,
        scope: SCOPE_LABEL[c.credit_scope],
        role: c.role_text,
        artistId: c.artist_id as number,
      }));
    views.push({
      index: i + 1,
      aName: displayName(hop.artist_a_id),
      bName: displayName(hop.artist_b_id),
      release: {
        ref: String(release.release_id),
        title: release.title,
        released: release.released,
        country: release.country,
        sourceUrl: release.source_url,
      },
      coverUri: options.covers ? (release.images?.[0]?.uri150 ?? null) : null,
      rows,
      nonLinked: release.credits
        .filter((c) => !c.is_linked)
        .map((c) => ({ name: c.name, role: c.role_text })),
      flagsLine: null,
    });
  });
  return views;
}
