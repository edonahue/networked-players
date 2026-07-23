// Build-time album-art resolution for the browse surfaces (albums grid, album
// detail, homepage teaser). Cover art lives in a separately versioned public
// registry keyed by canonical album id
// (apps/web/public/data/catalog/album-art.v1.json, ADR 0044/0045) — the same
// single source the client-side game resolver (game/albumArt.ts) reads. The
// registry is read once at build; a missing or malformed registry yields an
// empty map and every album renders the polished placeholder.

import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { ReleaseImage } from "./challenge";

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

/** `album_id -> main_release_id` from the canonical catalog, read once at
 * build time — the cross-check `loadRegistry` uses to catch a registry
 * built against a stale catalog snapshot even when `catalog_version`
 * happens to still agree (e.g. a catalog rebuilt with identical album
 * membership but a different `main_release_id` mapping for one album). */
function loadCanonicalCatalog(): {
  catalogVersion: string | null;
  mainReleaseIdByAlbum: Map<string, number>;
} {
  const mainReleaseIdByAlbum = new Map<string, number>();
  let raw: string;
  try {
    raw = readFileSync(
      join(process.cwd(), "public/data/catalog/albums.v1.json"),
      "utf8",
    );
  } catch {
    return { catalogVersion: null, mainReleaseIdByAlbum };
  }
  let catalog: unknown;
  try {
    catalog = JSON.parse(raw);
  } catch {
    return { catalogVersion: null, mainReleaseIdByAlbum };
  }
  const c = catalog as Record<string, unknown>;
  const catalogVersion =
    typeof c.catalog_version === "string" ? c.catalog_version : null;
  const albums = c.albums;
  if (Array.isArray(albums)) {
    for (const entry of albums) {
      if (typeof entry !== "object" || entry === null) continue;
      const e = entry as Record<string, unknown>;
      if (typeof e.id === "string" && typeof e.main_release_id === "number") {
        mainReleaseIdByAlbum.set(e.id, e.main_release_id);
      }
    }
  }
  return { catalogVersion, mainReleaseIdByAlbum };
}

function loadRegistry(): Map<string, ReleaseImage> {
  const map = new Map<string, ReleaseImage>();
  const { catalogVersion, mainReleaseIdByAlbum } = loadCanonicalCatalog();
  let raw: string;
  try {
    // Resolve from the build's working directory (apps/web during
    // `astro build`) rather than import.meta.url, which Vite rewrites to the
    // bundled chunk location and would not resolve the public asset.
    raw = readFileSync(
      join(process.cwd(), "public/data/catalog/album-art.v1.json"),
      "utf8",
    );
  } catch {
    return map; // registry not present — all placeholders
  }
  let registry: unknown;
  try {
    registry = JSON.parse(raw);
  } catch {
    return map;
  }
  const r = registry as Record<string, unknown>;
  // A registry whose catalog_version disagrees with the canonical catalog's
  // own (or whose version is simply missing) belongs to a different, stale
  // catalog snapshot -- every album falls back to the placeholder rather
  // than risking a mismatched art/main_release_id pairing.
  if (
    catalogVersion !== null &&
    (typeof r.catalog_version !== "string" ||
      r.catalog_version !== catalogVersion)
  ) {
    return map;
  }
  const albums = r.albums;
  if (!Array.isArray(albums)) return map;
  for (const entry of albums) {
    if (typeof entry !== "object" || entry === null) continue;
    const e = entry as Record<string, unknown>;
    if (
      typeof e.album_id === "string" &&
      isApprovedHttpsUrl(e.uri150) &&
      isApprovedHttpsUrl(e.uri)
    ) {
      // Skip an entry whose main_release_id disagrees with the canonical
      // catalog row for this album id -- catches a registry entry built
      // against a different pressing than the one the catalog now points
      // at, even when the registry's own top-level catalog_version matches.
      const canonicalReleaseId = mainReleaseIdByAlbum.get(e.album_id);
      if (
        canonicalReleaseId !== undefined &&
        typeof e.main_release_id === "number" &&
        e.main_release_id !== canonicalReleaseId
      ) {
        continue;
      }
      map.set(e.album_id, {
        uri150: e.uri150,
        uri: e.uri,
        width: typeof e.width === "number" ? e.width : 0,
        height: typeof e.height === "number" ? e.height : 0,
      });
    }
  }
  return map;
}

const registry = loadRegistry();

/** The registry cover for a canonical album id, or null (→ placeholder). */
export function coverFor(albumId: string): ReleaseImage | null {
  return registry.get(albumId) ?? null;
}
