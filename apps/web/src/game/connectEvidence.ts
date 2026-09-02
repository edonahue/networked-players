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

import type { ResolvedArt } from "./albumArt";
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

/** One documented performance hop: the two contributors' names/roles as
 * plain prose, plus a visually distinct evidence-release sub-card (cover
 * when known, title/year/country, always a source link) -- kept as two
 * separate blocks rather than one run-on sentence so a reader can tell
 * "who's connected" from "what document proves it" at a glance. */
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
  // `data-hop-artist-id` marks each name for the Phase 6 PR 6-06
  // enhance-in-place pass (`enhanceHopContributorLinks`) that upgrades it
  // to a link to that person's own contributor page, when one exists --
  // the contributor index isn't awaited here, matching the same
  // structural-render-first split `enhanceHopRelease`/`enhanceEndpointCover`
  // already use for evidence/art.
  const nameASpan = `<span data-hop-artist-id="${hop.artist_a_id}">${escapeHtml(nameA)}</span>`;
  const nameBSpan = `<span data-hop-artist-id="${hop.artist_b_id}">${escapeHtml(nameB)}</span>`;
  return (
    `<div class="connect-hop">` +
    `<p class="connect-hop__contributors">${nameASpan} <span class="connect-hop__role">(${escapeHtml(hop.role_a)})</span>` +
    ` and ${nameBSpan} <span class="connect-hop__role">(${escapeHtml(hop.role_b)})</span>` +
    ` are documented performing on the same release.</p>` +
    `<div class="connect-hop__release">` +
    (cover || "") +
    `<div class="connect-hop__release-text">` +
    (meta ? `<p class="connect-hop__release-title">${meta}</p>` : "") +
    `<p class="connect-hop__source">Release <a href="${discogsReleaseUrl(hop.release_id)}" rel="nofollow noopener">#${hop.release_id} on Discogs</a></p>` +
    `</div>` +
    `</div>` +
    `</div>`
  );
}

/** Upgrades an already-rendered hop's release sub-card with cover/title
 * metadata, in place -- never a full re-render of the hop or its
 * container. The structural render (`renderEvidenceHop` called with an
 * empty evidence map, ADR 0059 Phase 5 PR 5b) already has the source
 * link and contributor prose; this fills in exactly what evidence adds:
 * a cover image and the release title/year/country line, each inserted
 * only if not already present (so calling this twice, or on an already-
 * fully-rendered hop, is a safe no-op). A no-op entirely if `evidenceIndex`
 * still has no entry for this hop's release. */
export function enhanceHopRelease(
  hopEl: Element,
  hop: PathHop,
  evidenceIndex: Map<number, EvidenceRelease>,
): void {
  const release = evidenceIndex.get(hop.release_id);
  if (!release) return;
  const releaseEl = hopEl.querySelector(".connect-hop__release");
  if (!releaseEl) return;
  if (release.coverUri && !releaseEl.querySelector(".connect-hop__cover")) {
    const img = document.createElement("img");
    img.className = "connect-hop__cover";
    img.src = release.coverUri;
    img.width = 48;
    img.height = 48;
    img.loading = "lazy";
    img.alt = "";
    img.dataset.artFallback = "hide";
    releaseEl.insertBefore(img, releaseEl.firstChild);
  }
  const meta = releaseMetaLine(release);
  const textEl = releaseEl.querySelector(".connect-hop__release-text");
  if (meta && textEl && !textEl.querySelector(".connect-hop__release-title")) {
    const title = document.createElement("p");
    title.className = "connect-hop__release-title";
    title.innerHTML = meta;
    textEl.insertBefore(title, textEl.firstChild);
  }
}

/** Upgrades every already-rendered hop name inside `container` that has its
 * own contributor page into a link there, in place -- never a full
 * re-render of the hop. Shared by Connect and the Network Explorer's
 * evidence drawer (both render hops through `renderEvidenceHop`), so a
 * contributor's page is reachable from every place their name appears as
 * documented evidence, not just the two dedicated center/album-page links
 * (PR 6-04/6-05). Idempotent and safe to call more than once (e.g. Connect's
 * Swap control re-rendering the same hops): an already-linked name is
 * skipped, and a name whose id isn't in `contributorIds` is left as plain
 * text, never a dangling href. */
export function enhanceHopContributorLinks(
  container: Element,
  contributorIds: ReadonlySet<number>,
): void {
  for (const nameEl of container.querySelectorAll<HTMLElement>(
    "[data-hop-artist-id]",
  )) {
    const artistId = Number(nameEl.dataset.hopArtistId);
    if (!contributorIds.has(artistId)) continue;
    if (nameEl.querySelector("a")) continue;
    const link = document.createElement("a");
    link.href = `/contributors/${artistId}/`;
    link.textContent = nameEl.textContent ?? "";
    nameEl.replaceChildren(link);
  }
}

/** One album endpoint card: "X is credited on Album A's own release, as
 * Producer" -- the north-star claim's literal starting/ending point, not
 * an ordinary co-credit hop, so it gets a cover (or the site's own
 * established polished placeholder, `AlbumCard.astro`'s pattern -- ADR
 * 0044/0045) rather than the bare text every other hop card uses. Cover
 * art is presentation-only and can never block or fail a search: a missing
 * `art` entry (registry not yet loaded, fetch failed, or no entry for this
 * album) renders the placeholder, never a broken image or an error. */
export function renderEndpointCard(
  endpoint: AlbumEndpoint,
  albumId: string,
  albumTitle: string,
  nameById: Map<number, string>,
  art: ResolvedArt | undefined,
): string {
  const name = nameById.get(endpoint.artistId) ?? `Artist ${endpoint.artistId}`;
  const cover = art
    ? `<img class="connect-endpoint__cover" src="${escapeHtml(art.uri150)}" width="72" height="72" loading="lazy" alt="Cover art for ${escapeHtml(albumTitle)}" data-art-fallback="disc" />`
    : `<span class="connect-endpoint__cover connect-endpoint__cover--placeholder album-card__placeholder" aria-hidden="true"><span class="album-card__placeholder-disc"></span></span>`;
  // Phase 6 PR 6-07: the album title links to its own /albums/<id>/ page --
  // the mirror of PR 6-01's album-page-to-Connect link, completing the
  // round trip between the two surfaces.
  const albumLink = `<a href="/albums/${escapeHtml(albumId)}/">${escapeHtml(albumTitle)}</a>`;
  return (
    `<div class="connect-endpoint">` +
    cover +
    `<p><strong>${escapeHtml(name)}</strong> is credited on <strong>${albumLink}</strong>'s own release,` +
    ` as <span class="connect-hop__role">${escapeHtml(endpoint.roleText)}</span>.</p>` +
    `</div>`
  );
}

/** Upgrades an already-rendered endpoint card's placeholder to a real
 * cover, in place -- never a full re-render of the card or its container.
 * `renderRoute` never awaits the art registry before rendering a route (a
 * real review finding: the registry has no fetch timeout, so a slow or
 * hung request would otherwise leave an already-found route stuck behind
 * "Searching…" indefinitely); this is the enhancement half of that split,
 * called once the art registry resolves. A no-op if the card already shows
 * a real image (nothing to upgrade) or `art` is still unavailable. */
export function enhanceEndpointCover(
  cardEl: Element,
  art: ResolvedArt | undefined,
  albumTitle: string,
): void {
  if (!art) return;
  const existing = cardEl.querySelector(".connect-endpoint__cover");
  if (!existing || existing.tagName === "IMG") return;
  const img = document.createElement("img");
  img.className = "connect-endpoint__cover";
  img.src = art.uri150;
  img.width = 72;
  img.height = 72;
  img.loading = "lazy";
  img.alt = `Cover art for ${albumTitle}`;
  img.dataset.artFallback = "disc";
  existing.replaceWith(img);
}
