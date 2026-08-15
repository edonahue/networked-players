// Real evidence rendering for Connect Two Records (ADR 0058 Slice 7):
// turns a found album route into endpoint cards ("X is credited on Album
// A's own release, as Producer") and per-hop evidence cards (release
// title/year/cover/source) using the evidence-release registry
// (apps/web/public/data/evidence/release-registry.v1.json, Slice 3) --
// replacing the pre-v2 bare "Release #12345 on Discogs" link.
//
// Deliberately not `evidence.ts`'s `PanelHop`/`buildHopViews` -- those
// need a full `Release` object (title, source_url, a complete per-credit
// `credits[]` array) that the registry's deliberately release-metadata-
// only shape doesn't carry (see data/contracts/evidence-release-registry-v1.md's
// own scoping note). This is a smaller, Connect-specific shape: two
// contributor names + roles and one release's presentational metadata per
// hop, not a full credit table.

import { escapeHtml } from "./domUtils";
import type { AlbumEndpoint, PathHop } from "./pathfindingGraph";

export interface EvidenceRelease {
  releaseId: number;
  title: string;
  year: number | null;
  country: string | null;
  coverUri: string | null;
  /** Format-descriptor caveat bitmask (schema_version 2 only, ADR 0059) --
   * 0 means "nothing tagged warrants a caveat", never "confirmed clean",
   * and also what a v1 registry or an id absent from the registry
   * produces. Bit meaning depends on `caveatFlagNames`; never interpret
   * this field without it, since bit order is data, not a hardcoded
   * constant here. */
  caveatFlags: number;
}

interface EvidenceRegistryPayload {
  schema_version?: number;
  release_ids: number[];
  titles: string[];
  years: (number | null)[];
  countries: (string | null)[];
  cover_uri150s: (string | null)[];
  /** Present only when schema_version === 2. */
  caveat_flags?: number[];
  /** Present only when schema_version === 2 -- the bit order `caveat_flags`
   * integers are meaningless without. */
  caveat_flag_names?: string[];
}

export interface EvidenceIndex {
  releases: Map<number, EvidenceRelease>;
  /** Empty for a v1 registry or a registry that fails to carry the legend
   * -- callers that read `caveatFlags` must treat that as "no caveat
   * vocabulary available" and degrade accordingly, never as "definitely
   * no caveats" for released whose flags are simply 0 through absence. */
  caveatFlagNames: string[];
}

/** Built once per fetched registry, reused across a session's searches. */
export function buildEvidenceIndex(
  registry: EvidenceRegistryPayload,
): EvidenceIndex {
  const caveatFlagNames =
    registry.schema_version === 2 && Array.isArray(registry.caveat_flag_names)
      ? registry.caveat_flag_names
      : [];
  const flags =
    registry.schema_version === 2 && Array.isArray(registry.caveat_flags)
      ? registry.caveat_flags
      : [];
  const releases = new Map<number, EvidenceRelease>();
  registry.release_ids.forEach((releaseId, i) => {
    releases.set(releaseId, {
      releaseId,
      title: registry.titles[i],
      year: registry.years[i],
      country: registry.countries[i],
      coverUri: registry.cover_uri150s[i],
      caveatFlags: flags[i] ?? 0,
    });
  });
  return { releases, caveatFlagNames };
}

/** The registry's own `source_urls` field is the *dataset's* provenance
 * (the Discogs monthly dump download URL, identical for every release),
 * never a per-release page link -- see the contract doc. A clickable
 * release page is this one-line construction from the id alone, the same
 * pattern the pre-v2 renderHop already used. */
export function discogsReleaseUrl(releaseId: number): string {
  return `https://www.discogs.com/release/${releaseId}`;
}

function releaseMetaLine(release: EvidenceRelease | undefined): string {
  if (!release) return "";
  const yearCountry =
    release.year && release.country
      ? ` (${release.year}, ${escapeHtml(release.country)})`
      : release.year
        ? ` (${release.year})`
        : "";
  return `<strong>${escapeHtml(release.title)}</strong>${yearCountry}`;
}

/** One documented co-credit hop: both names/roles plus a real evidence
 * card for the bridging release (title/year/country/cover when known,
 * always a source link). */
export function renderEvidenceHop(
  hop: PathHop,
  nameById: Map<number, string>,
  evidenceIndex: Map<number, EvidenceRelease>,
): string {
  const nameA = nameById.get(hop.artist_a_id) ?? `Artist ${hop.artist_a_id}`;
  const nameB = nameById.get(hop.artist_b_id) ?? `Artist ${hop.artist_b_id}`;
  const release = evidenceIndex.get(hop.release_id);
  const cover =
    release?.coverUri &&
    `<img class="connect-hop__cover" src="${escapeHtml(release.coverUri)}" width="48" height="48" loading="lazy" alt="" data-art-fallback="hide" />`;
  const meta = releaseMetaLine(release);
  return (
    `<div class="connect-hop">` +
    (cover ? `<div class="connect-hop__head">${cover}<div>` : "") +
    `<p>${escapeHtml(nameA)} <span class="connect-hop__role">(${escapeHtml(hop.role_a)})</span>` +
    ` and ${escapeHtml(nameB)} <span class="connect-hop__role">(${escapeHtml(hop.role_b)})</span>` +
    ` are co-credited on the same documented release${meta ? `, ${meta}` : ""}.</p>` +
    `<p class="connect-hop__source">Release <a href="${discogsReleaseUrl(hop.release_id)}" rel="nofollow noopener">#${hop.release_id} on Discogs</a></p>` +
    (cover ? `</div></div>` : "") +
    `</div>`
  );
}

/** One album endpoint card: "X is credited on Album A's own release, as
 * Producer" -- the north-star claim's literal starting/ending point, not
 * an ordinary co-credit hop. */
export function renderEndpointCard(
  endpoint: AlbumEndpoint,
  albumTitle: string,
  nameById: Map<number, string>,
): string {
  const name = nameById.get(endpoint.artistId) ?? `Artist ${endpoint.artistId}`;
  return (
    `<div class="connect-endpoint">` +
    `<p><strong>${escapeHtml(name)}</strong> is credited on <strong>${escapeHtml(albumTitle)}</strong>'s own release,` +
    ` as <span class="connect-hop__role">${escapeHtml(endpoint.roleText)}</span>.</p>` +
    `</div>`
  );
}
