// Deterministic album selection for tests that need "a real connected album
// page" from the committed challenge.v2 artifact.
//
// Specs used to write `albums.find((a) => connectedIds.has(a.id))`, i.e.
// whichever connected album happens to come FIRST in artifact order. That is
// currently master-1046042 ("Blonde"), which is the graph hub: 136 of the
// artifact's 300 paths, ~1MB of HTML and 273 hotlinked cover images -- the
// single heaviest page on the site. Every Playwright action against that DOM
// costs ~700-1600ms of trace snapshotting, which put the album smoke test at
// 27.5s against a 30s cap and made it fail intermittently. Nothing those
// tests assert requires the hub; they require an album with at least two
// documented paths, so "Reveal every path" is distinguishable from revealing
// one. Path counts across the 137 connected albums are min 2, median 2,
// max 136 -- the first-in-order pick was an extreme outlier.
//
// Picking the FEWEST-path album (ties broken by id) is both bounded and
// stable: it no longer silently re-rolls onto an arbitrary page when the
// artifact is regenerated.

import { expect, type APIRequestContext } from "@playwright/test";

interface ChallengeAlbum {
  id: string;
  title: string;
}

interface ChallengePath {
  from_album_id: string;
  to_album_id: string;
}

export interface PickedAlbum {
  album: ChallengeAlbum;
  /** How many documented paths this album is an endpoint of. */
  pathCount: number;
}

/**
 * Returns the connected album with the fewest documented paths (>= 2),
 * ties broken by id, plus its path count.
 */
export async function pickBoundedConnectedAlbum(
  request: APIRequestContext,
): Promise<PickedAlbum> {
  const res = await request.get("/data/challenge.v2.json");
  expect(res.ok()).toBeTruthy();
  const { albums, paths } = (await res.json()) as {
    albums: ChallengeAlbum[];
    paths: ChallengePath[];
  };

  const pathCount = new Map<string, number>();
  for (const path of paths) {
    for (const id of [path.from_album_id, path.to_album_id]) {
      pathCount.set(id, (pathCount.get(id) ?? 0) + 1);
    }
  }

  const candidates = albums
    .filter((album) => (pathCount.get(album.id) ?? 0) >= 2)
    .sort(
      (a, b) =>
        pathCount.get(a.id)! - pathCount.get(b.id)! || a.id.localeCompare(b.id),
    );

  expect(
    candidates.length,
    "challenge.v2.json must contain a connected album with at least 2 documented paths",
  ).toBeGreaterThan(0);

  const album = candidates[0];
  return { album, pathCount: pathCount.get(album.id)! };
}

interface AlbumArtRegistry {
  catalog_version: string;
  albums: Array<{ album_id: string }>;
}

interface CatalogAlbum {
  catalog_version: string;
}

/**
 * Returns the connected album with the fewest documented paths (>= 2, ties
 * broken by id) among those with real cover art -- deterministically known
 * to render `.play-header__cover`, independent of `pickBoundedConnectedAlbum`
 * and of whatever `challenge.v2.json` happens to contain.
 *
 * Cover art is resolved at build time from a wholly separate artifact
 * (`public/data/catalog/album-art.v1.json`, see `src/data/albumArt.ts`),
 * with its own presence/version validation -- nothing ties "fewest paths"
 * to "has art". This helper cross-references that registry the same way
 * `coverFor()` does (entry presence + matching `catalog_version`, the
 * primary gate) so a hotlink-contract test can pick an album guaranteed to
 * exercise the real `<img>` branch rather than the placeholder.
 */
export async function pickConnectedAlbumWithArt(
  request: APIRequestContext,
): Promise<PickedAlbum> {
  const [challengeRes, artRes, catalogRes] = await Promise.all([
    request.get("/data/challenge.v2.json"),
    request.get("/data/catalog/album-art.v1.json"),
    request.get("/data/catalog/albums.v1.json"),
  ]);
  expect(challengeRes.ok()).toBeTruthy();
  expect(artRes.ok()).toBeTruthy();
  expect(catalogRes.ok()).toBeTruthy();

  const { albums, paths } = (await challengeRes.json()) as {
    albums: ChallengeAlbum[];
    paths: ChallengePath[];
  };
  const art = (await artRes.json()) as AlbumArtRegistry;
  const catalog = (await catalogRes.json()) as CatalogAlbum;

  const pathCount = new Map<string, number>();
  for (const path of paths) {
    for (const id of [path.from_album_id, path.to_album_id]) {
      pathCount.set(id, (pathCount.get(id) ?? 0) + 1);
    }
  }

  const artAlbumIds =
    art.catalog_version === catalog.catalog_version
      ? new Set(art.albums.map((a) => a.album_id))
      : new Set<string>();

  const candidates = albums
    .filter(
      (album) =>
        (pathCount.get(album.id) ?? 0) >= 2 && artAlbumIds.has(album.id),
    )
    .sort(
      (a, b) =>
        pathCount.get(a.id)! - pathCount.get(b.id)! || a.id.localeCompare(b.id),
    );

  expect(
    candidates.length,
    "challenge.v2.json must contain a connected album with real registry cover art",
  ).toBeGreaterThan(0);

  const album = candidates[0];
  return { album, pathCount: pathCount.get(album.id)! };
}
