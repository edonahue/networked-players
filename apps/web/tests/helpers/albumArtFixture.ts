// Generates a test-only variant of the real committed album-art registry,
// for the one Playwright spec (album-cover-placeholder.spec.ts) that needs
// to drive /albums/[album].astro into its TRUE placeholder branch -- both
// coverFor() and album.cover_image falsy at once.
//
// No committed album currently lacks a registry entry (all 140 have one),
// so no real page can reach that branch through the normal build. This
// helper never fakes production data or commits a fixture: it reads the
// REAL registry off disk at test-run time, picks a real connected album by
// the same fewest-path/tie-by-id convention pickBoundedConnectedAlbum
// already uses (a filesystem-context twin, not a shared import -- this
// runs in Node before any server/APIRequestContext exists, a different
// phase from that HTTP-based helper), and writes a copy of the real
// registry with only that one album's entry removed to a gitignored
// scratch path (apps/web/tests/fixtures/.generated/) -- a transient build
// *input* for one isolated test build, never committed, self-healing
// against a future artifact regeneration the same way pickBoundedConnectedAlbum
// already is.

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

interface ChallengeAlbum {
  id: string;
  title: string;
  cover_image: unknown;
}

interface ChallengePath {
  from_album_id: string;
  to_album_id: string;
}

interface AlbumArtRegistry {
  catalog_version: string;
  albums: Array<Record<string, unknown> & { album_id: string }>;
}

export interface PlaceholderFixture {
  /** The real, connected album id whose registry entry was removed. */
  albumId: string;
  albumTitle: string;
  /** Repo-relative path (from apps/web/), suitable for NP_ALBUM_ART_REGISTRY_PATH. */
  registryPath: string;
}

const GENERATED_DIR = "tests/fixtures/.generated";
const GENERATED_REGISTRY_PATH = `${GENERATED_DIR}/album-art-registry-missing-one.v1.json`;

/**
 * Picks a real connected album (fewest documented paths, ties broken by id
 * -- same convention as pickBoundedConnectedAlbum) and writes a copy of the
 * real committed album-art registry with that one album's entry removed.
 * Returns enough to both navigate to the album and point
 * NP_ALBUM_ART_REGISTRY_PATH at the generated file.
 */
export function generatePlaceholderFixture(
  webRoot: string,
): PlaceholderFixture {
  const challenge = JSON.parse(
    readFileSync(join(webRoot, "public/data/challenge.v2.json"), "utf8"),
  ) as { albums: ChallengeAlbum[]; paths: ChallengePath[] };
  const registry = JSON.parse(
    readFileSync(
      join(webRoot, "public/data/catalog/album-art.v1.json"),
      "utf8",
    ),
  ) as AlbumArtRegistry;

  const pathCount = new Map<string, number>();
  for (const path of challenge.paths) {
    for (const id of [path.from_album_id, path.to_album_id]) {
      pathCount.set(id, (pathCount.get(id) ?? 0) + 1);
    }
  }
  const registeredIds = new Set(registry.albums.map((a) => a.album_id));
  const candidates = challenge.albums
    .filter(
      (album) =>
        (pathCount.get(album.id) ?? 0) >= 2 &&
        registeredIds.has(album.id) &&
        // Removing the registry entry alone only reaches the TRUE
        // placeholder branch if album.cover_image (coverFor()'s second
        // fallback) is also falsy. Every committed album's cover_image is
        // null today, so this has no effect now -- but without it, a
        // future artifact regeneration that populates cover_image for
        // whichever album this picks would make the page correctly render
        // that fallback cover, and this test would then assert the
        // placeholder shows when production behavior is actually right.
        album.cover_image == null,
    )
    .sort(
      (a, b) =>
        pathCount.get(a.id)! - pathCount.get(b.id)! || a.id.localeCompare(b.id),
    );
  if (candidates.length === 0) {
    throw new Error(
      "challenge.v2.json must contain a connected, registry-listed album with no cover_image fallback to build the placeholder fixture from",
    );
  }
  const chosen = candidates[0];

  const modifiedRegistry: AlbumArtRegistry = {
    ...registry,
    albums: registry.albums.filter((a) => a.album_id !== chosen.id),
  };

  const outPath = join(webRoot, GENERATED_REGISTRY_PATH);
  mkdirSync(dirname(outPath), { recursive: true });
  writeFileSync(outPath, JSON.stringify(modifiedRegistry, null, 2));

  return {
    albumId: chosen.id,
    albumTitle: chosen.title,
    registryPath: GENERATED_REGISTRY_PATH,
  };
}
