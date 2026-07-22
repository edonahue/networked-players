// Build-time album-art resolution for the browse surfaces (albums grid, album
// detail, homepage teaser). Cover art lives in a separately versioned public
// registry keyed by canonical album id
// (apps/web/public/data/catalog/album-art.v1.json, ADR 0044/0045) — the same
// single source the client-side game resolver (game/albumArt.ts) reads. The
// registry is read once at build; a missing or malformed registry yields an
// empty map and every album renders the polished placeholder.

import { readFileSync } from "node:fs";
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

function loadRegistry(): Map<string, ReleaseImage> {
  const map = new Map<string, ReleaseImage>();
  let raw: string;
  try {
    const path = new URL(
      "../../public/data/catalog/album-art.v1.json",
      import.meta.url,
    );
    raw = readFileSync(path, "utf8");
  } catch {
    return map; // registry not present yet — all placeholders
  }
  let registry: unknown;
  try {
    registry = JSON.parse(raw);
  } catch {
    return map;
  }
  const albums = (registry as { albums?: unknown })?.albums;
  if (!Array.isArray(albums)) return map;
  for (const entry of albums) {
    if (typeof entry !== "object" || entry === null) continue;
    const e = entry as Record<string, unknown>;
    if (
      typeof e.album_id === "string" &&
      isApprovedHttpsUrl(e.uri150) &&
      isApprovedHttpsUrl(e.uri)
    ) {
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
