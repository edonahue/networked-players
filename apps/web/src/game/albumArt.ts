// Presentation-only album-art resolution (ADR 0044/0045). Cover art lives in
// a separately versioned public registry keyed by canonical album id
// (apps/web/public/data/catalog/album-art.v1.json), NOT embedded in any frozen
// game content — so enriching or refreshing art never changes a round
// fingerprint or the daily manifest.
//
// Every failure mode (registry missing/404, malformed, catalog-version
// mismatch, unknown album id, missing entry, malformed URL, upstream image
// 403/404, slow/expired) resolves to `null` → the caller renders the polished
// placeholder. Art can NEVER block gameplay.

export interface AlbumArtEntry {
  album_id: string;
  uri150: string;
  uri: string;
}

export interface AlbumArtRegistry {
  schema_version: number;
  catalog_version: string;
  art_version: string;
  albums: AlbumArtEntry[];
}

export interface ResolvedArt {
  uri150: string;
  uri: string;
}

const APPROVED_HOSTS = new Set(["i.discogs.com"]);

function isApprovedHttpsUrl(value: unknown): value is string {
  if (typeof value !== "string") return false;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && APPROVED_HOSTS.has(url.hostname);
  } catch {
    return false;
  }
}

/** Build an album_id → {uri150,uri} map from an untrusted registry value,
 * keeping only well-formed entries (approved https host, both URLs). A
 * malformed registry yields an empty map, never a throw. */
export function buildArtMap(registry: unknown): Map<string, ResolvedArt> {
  const map = new Map<string, ResolvedArt>();
  if (typeof registry !== "object" || registry === null) return map;
  const albums = (registry as { albums?: unknown }).albums;
  if (!Array.isArray(albums)) return map;
  for (const entry of albums) {
    if (typeof entry !== "object" || entry === null) continue;
    const e = entry as Record<string, unknown>;
    if (
      typeof e.album_id === "string" &&
      isApprovedHttpsUrl(e.uri150) &&
      isApprovedHttpsUrl(e.uri)
    ) {
      map.set(e.album_id, { uri150: e.uri150, uri: e.uri });
    }
  }
  return map;
}

// Keyed by the requested `catalogVersion` (an empty string standing in for
// "no version requested") -- a bare nullable Promise here would let a
// second call in the same page load with a DIFFERENT catalogVersion
// incorrectly reuse the first call's result. Every current page only ever
// calls this once with one version, so this was a latent defect, not an
// observed one -- fixed anyway since nothing about the cache's own contract
// promised single-version use.
const cached = new Map<string, Promise<Map<string, ResolvedArt>>>();

/** Fetch and cache the art registry once per page per requested
 * `catalogVersion`. A missing or malformed registry resolves to an empty
 * map (all placeholders) — never rejects. If `catalogVersion` is given, a
 * registry whose `catalog_version` disagrees is ignored (empty map): art
 * must belong to the catalog the rounds came from. */
export function fetchAlbumArt(
  catalogVersion?: string,
): Promise<Map<string, ResolvedArt>> {
  const cacheKey = catalogVersion ?? "";
  const existing = cached.get(cacheKey);
  if (existing) return existing;
  const promise = (async () => {
    try {
      const res = await fetch("/data/catalog/album-art.v1.json");
      if (!res.ok) return new Map<string, ResolvedArt>();
      const registry = (await res.json()) as unknown;
      if (
        catalogVersion !== undefined &&
        (registry as { catalog_version?: unknown })?.catalog_version !==
          catalogVersion
      ) {
        return new Map<string, ResolvedArt>();
      }
      return buildArtMap(registry);
    } catch {
      return new Map<string, ResolvedArt>();
    }
  })();
  cached.set(cacheKey, promise);
  return promise;
}

/** Test-only: reset the per-page fetch cache. */
export function _resetAlbumArtCache(): void {
  cached.clear();
}
