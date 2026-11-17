// Artifact-derived test facts. Specs must not hard-code real album or artist
// names, ids, or counts that change every catalog round (Atlas F6). Instead
// they ask this module, which reads the committed public artifacts and
// picks albums BY RULE using the same search code the app runs:
//
//   - albums are scanned in catalog order (sorted by id), pairs (i < j), and
//     the FIRST pair satisfying a predicate wins, so the choice is
//     deterministic for a given artifact set;
//   - route predicates call `findAlbumRoute` / `selectRecommendedRoute`
//     with the same filters connect.ts passes, over graph.v4.json.
//
// A new album can change which pair is picked, never whether a test's
// behaviour-under-test is exercised: if no pair satisfies a predicate the
// module throws with the predicate's name rather than silently skipping.

import { createHash } from "node:crypto";
import { readFileSync, renameSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  buildAlbumIndex,
  buildArtistIndex,
  findAlbumRoute,
  loadPathfindingGraph,
  type AlbumRouteResult,
  type PathfindingGraph,
} from "../../src/game/pathfindingGraph";
import { buildEvidenceIndex } from "../../src/game/connectEvidence";
import { selectRecommendedRoute } from "../../src/game/recommendedRoute";
import { buildView } from "../../src/game/networkExplorer";
import type { Contributor } from "../../src/data/contributors";
import {
  guitarPathsEdgeFilter,
  rhythmSectionEdgeFilter,
} from "../../src/game/roleTaxonomy";

const webRoot = join(dirname(fileURLToPath(import.meta.url)), "../..");
export const DATA_DIR = join(webRoot, "public/data");

export function readArtifact<T>(relativePath: string): T {
  return JSON.parse(readFileSync(join(DATA_DIR, relativePath), "utf8")) as T;
}

export interface CatalogAlbum {
  id: string;
  title: string;
  artist: string;
  artist_id: number;
  year: number | null;
}

export const catalogAlbums: CatalogAlbum[] = readArtifact<{
  albums: CatalogAlbum[];
}>("catalog/albums.v1.json")
  .albums.slice()
  .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));

export function albumById(id: string): CatalogAlbum {
  const album = catalogAlbums.find((a) => a.id === id);
  if (!album) throw new Error(`album ${id} is not in the committed catalog`);
  return album;
}

/** A query that reliably surfaces `album` in a picker: its full title. The
 * spec then clicks the option carrying the album's id (see
 * `selectAlbumById`), so duplicate titles cannot pick the wrong record. */
export function titleQuery(album: CatalogAlbum): string {
  return album.title;
}

export function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export interface AlbumPair {
  a: CatalogAlbum;
  b: CatalogAlbum;
}

interface Facts {
  /** First pair (catalog order) with an unfiltered recommended route AND a
   * genuinely distinct alternate route. */
  connected: AlbumPair & { routeHops: number };
  /** A second, album-disjoint connected pair (for "search again" tests). */
  secondConnected: AlbumPair;
  /** First pair whose plain shortest route uses a caveated release while the
   * recommended route avoids caveated evidence entirely. */
  diagnostic: AlbumPair & { caveatedReleaseIds: number[] };
  /** First pair with a Rhythm Section route; `hops` is the engine's own
   * hop count for it. */
  rhythm: AlbumPair & { hops: number };
  /** First pair with a Guitar Paths route. */
  guitar: AlbumPair;
  /** First pair with NO rhythm-section route and NO guitar-only route (both
   * failing with "no-path", not a capped search). */
  negative: AlbumPair;
  /** The Explore seed: the catalog album whose album-artist has the most
   * documented neighbors (ties: lowest album id) -- a high-degree center, so
   * the truncation and "show more" paths are exercised for real. `neighbor`
   * is the first neighbor the app would show for that center that also has
   * a contributor page. */
  explorer: {
    album: CatalogAlbum;
    artistName: string;
    totalNeighbors: number;
    neighbor: { artistId: number; name: string };
    /** The center's own contributor-page album (`albums[0]`). */
    ownAlbumId: string;
  };
  /** An album in neither `connected` nor `secondConnected`, connected to
   * `connected.a` (for "replace side B" tests). */
  replacementB: CatalogAlbum;
}

let factsPromise: Promise<Facts> | null = null;

async function loadGraph(): Promise<PathfindingGraph> {
  const original = globalThis.fetch;
  const text = readFileSync(join(DATA_DIR, "pathfinding/graph.v4.json"));
  globalThis.fetch = (async () =>
    new Response(text, { status: 200 })) as typeof fetch;
  try {
    const result = await loadPathfindingGraph(null, "http://test.invalid/g");
    if (!("graph" in result)) {
      throw new Error(`could not load graph.v4.json: ${result.error}`);
    }
    return result.graph;
  } finally {
    globalThis.fetch = original;
  }
}

function* pairs(): Generator<AlbumPair> {
  for (let i = 0; i < catalogAlbums.length; i++) {
    for (let j = i + 1; j < catalogAlbums.length; j++) {
      yield { a: catalogAlbums[i], b: catalogAlbums[j] };
    }
  }
}

async function computeFacts(): Promise<Facts> {
  const graph = await loadGraph();
  const artistIndex = buildArtistIndex(graph);
  const albumIndex = buildAlbumIndex(graph);
  const registry = readArtifact<Parameters<typeof buildEvidenceIndex>[0]>(
    "evidence/release-registry.v1.json",
  );
  const evidence = buildEvidenceIndex(registry);

  const route = (
    p: AlbumPair,
    filter?: (a: string, b: string) => boolean,
  ): AlbumRouteResult =>
    findAlbumRoute(graph, artistIndex, albumIndex, p.a.id, p.b.id, 4, filter);

  let connected: Facts["connected"] | null = null;
  let secondConnected: AlbumPair | null = null;
  let diagnostic: Facts["diagnostic"] | null = null;
  let rhythm: Facts["rhythm"] | null = null;
  let guitar: AlbumPair | null = null;
  let negative: AlbumPair | null = null;

  for (const p of pairs()) {
    if (
      connected &&
      secondConnected &&
      diagnostic &&
      rhythm &&
      guitar &&
      negative
    )
      break;
    const plain = route(p);
    if (!plain.ok) continue;

    if (!connected || !secondConnected) {
      const rec = selectRecommendedRoute(
        graph,
        artistIndex,
        albumIndex,
        p.a.id,
        p.b.id,
        evidence,
        4,
      );
      // At least one documented hop: albums sharing a credited contributor
      // directly have a zero-hop "route" with no hop evidence to render.
      if (rec.ok && rec.recommended.hops.length >= 1) {
        const alternate = findAlbumRoute(
          graph,
          artistIndex,
          albumIndex,
          p.a.id,
          p.b.id,
          4,
          undefined,
          rec.recommended.usedEdgeKeys,
        );
        if (alternate.ok) {
          if (!connected) {
            connected = { ...p, routeHops: rec.recommended.hops.length };
          } else if (
            !secondConnected &&
            p.a.id !== connected.a.id &&
            p.a.id !== connected.b.id &&
            p.b.id !== connected.a.id &&
            p.b.id !== connected.b.id
          ) {
            secondConnected = p;
          }
        }
      }
    }

    if (!diagnostic) {
      const caveated = plain.hops
        .map((h) => h.release_id)
        .filter((id) => (evidence.releases.get(id)?.caveatFlags ?? 0) !== 0);
      if (caveated.length > 0) {
        const rec = selectRecommendedRoute(
          graph,
          artistIndex,
          albumIndex,
          p.a.id,
          p.b.id,
          evidence,
          4,
        );
        if (
          rec.ok &&
          !rec.usedPlusOneHop &&
          !rec.rankingDegraded &&
          rec.recommended.facts.worstCaveatSeverity === 0 &&
          rec.recommended.hops.every((h) => !caveated.includes(h.release_id))
        ) {
          diagnostic = { ...p, caveatedReleaseIds: caveated };
        }
      }
    }

    // Filtered searches are the expensive ones: only run each while its
    // fact is still unresolved.
    const rhythmRoute: AlbumRouteResult | null =
      !rhythm || !negative ? route(p, rhythmSectionEdgeFilter) : null;
    if (!rhythm && rhythmRoute?.ok && rhythmRoute.hops.length >= 1) {
      rhythm = { ...p, hops: rhythmRoute.hops.length };
    }
    const guitarRoute: AlbumRouteResult | null =
      !guitar || (!negative && rhythmRoute && !rhythmRoute.ok)
        ? route(p, guitarPathsEdgeFilter)
        : null;
    if (!guitar && guitarRoute?.ok && guitarRoute.hops.length >= 1) guitar = p;
    if (
      !negative &&
      rhythmRoute &&
      !rhythmRoute.ok &&
      rhythmRoute.reason === "no-path" &&
      guitarRoute &&
      !guitarRoute.ok &&
      guitarRoute.reason === "no-path"
    ) {
      negative = p;
    }
  }

  // Explore seed: same neighborhood code the app runs, ranked by the real
  // prominence sidecar and contributor index.
  const contributorIndex = readArtifact<{ contributors: Contributor[] }>(
    "contributors/index.v1.json",
  );
  const contributorByArtistId = new Map(
    contributorIndex.contributors.map((c) => [c.artist_id, c]),
  );
  const prominence = readArtifact<{ node_ids: number[]; rank: number[] }>(
    "pathfinding/prominence.v1.json",
  );
  const rankByArtistId = new Map(
    prominence.node_ids.map((id, i) => [id, prominence.rank[i]]),
  );
  let explorer: Facts["explorer"] | null = null;
  let explorerDegree = -1;
  for (const album of catalogAlbums) {
    const view = buildView(
      graph,
      artistIndex,
      contributorByArtistId,
      album.artist_id,
      24,
      rankByArtistId,
    );
    const contributor = contributorByArtistId.get(album.artist_id);
    // The center must have its own contributor page (several specs assert
    // the center-to-contributor link) and a neighbor that does too.
    const neighbor = view?.neighbors.find((n) =>
      contributorByArtistId.has(n.artistId),
    );
    if (!view || !contributor || contributor.albums.length === 0 || !neighbor)
      continue;
    if (view.totalNeighborCount > explorerDegree) {
      explorerDegree = view.totalNeighborCount;
      explorer = {
        album,
        artistName: view.center.name,
        totalNeighbors: view.totalNeighborCount,
        neighbor: { artistId: neighbor.artistId, name: neighbor.name },
        ownAlbumId: contributor.albums[0],
      };
    }
  }

  const missing = Object.entries({
    explorer,
    connected,
    secondConnected,
    diagnostic,
    rhythm,
    guitar,
    negative,
  })
    .filter(([, v]) => v === null)
    .map(([k]) => k);
  if (missing.length > 0) {
    throw new Error(
      `the committed artifacts have no album pair for: ${missing.join(", ")} -- ` +
        "a test premise no longer exists; see tests/helpers/catalogFacts.ts",
    );
  }
  const c = connected!;
  const used = new Set([
    c.a.id,
    c.b.id,
    secondConnected!.a.id,
    secondConnected!.b.id,
  ]);
  const replacementB = catalogAlbums.find(
    (x) => !used.has(x.id) && route({ a: c.a, b: x }).ok,
  );
  if (!replacementB) {
    throw new Error("no album connected to the primary pair's first album");
  }
  return {
    explorer: explorer!,
    connected: c,
    secondConnected: secondConnected!,
    diagnostic: diagnostic!,
    rhythm: rhythm!,
    guitar: guitar!,
    negative: negative!,
    replacementB,
  };
}

// Computing the facts walks real BFS searches over the full graph, so the
// result is cached on disk (keyed by a hash of every input artifact) and
// shared by all Playwright workers. A stale or unreadable cache is simply
// recomputed; the cache never changes what is derived, only when.
function cachePath(): string {
  const hash = createHash("sha1");
  for (const rel of [
    "catalog/albums.v1.json",
    "pathfinding/graph.v4.json",
    "evidence/release-registry.v1.json",
    // The Explore facts (visible neighbour, a contributor's own record) are
    // read from these two; leaving them out would reuse stale facts.
    "contributors/index.v1.json",
    "pathfinding/prominence.v1.json",
  ]) {
    hash.update(readFileSync(join(DATA_DIR, rel)));
  }
  // The helper's own source participates, so editing a rule invalidates it.
  hash.update(readFileSync(fileURLToPath(import.meta.url)));
  return join(tmpdir(), `np-catalog-facts-${hash.digest("hex")}.json`);
}

export function catalogFacts(): Promise<Facts> {
  factsPromise ??= (async () => {
    const path = cachePath();
    try {
      return JSON.parse(readFileSync(path, "utf8")) as Facts;
    } catch {
      // fall through to compute
    }
    const facts = await computeFacts();
    try {
      const tmp = `${path}.${process.pid}`;
      writeFileSync(tmp, JSON.stringify(facts));
      renameSync(tmp, path);
    } catch {
      // cache is best-effort
    }
    return facts;
  })();
  return factsPromise;
}

interface ContributorLite {
  artist_id: number;
  albums: string[];
}

/** Largest contributor page the accessibility scan is bounded to, measured
 * in albums credited. A contributor page grows with its album count (about
 * 220 DOM elements per album); axe's per-element color-contrast/region work
 * takes ~27s at 14 albums (~3,100 elements), so 20 albums (~4,400 elements)
 * stays inside the 3x `test.slow()` budget under full-suite load. Without a
 * bound the scan would grow with every round until it timed out. */
export const SCAN_ALBUM_CAP = 20;

/** The contributor page the accessibility scan audits, chosen by rule: the
 * contributor with the MOST albums among those at or under SCAN_ALBUM_CAP
 * (ties: lowest artist_id). That is always a large page (never the trivial
 * 1-2 album common case) and its size is bounded however the index grows. */
export function pickScanContributorId(): number {
  const { contributors } = readArtifact<{ contributors: ContributorLite[] }>(
    "contributors/index.v1.json",
  );
  const eligible = contributors
    .filter((c) => c.albums.length > 0 && c.albums.length <= SCAN_ALBUM_CAP)
    .sort(
      (x, y) => y.albums.length - x.albums.length || x.artist_id - y.artist_id,
    );
  if (eligible.length === 0) {
    throw new Error("no contributor page within the accessibility scan bound");
  }
  return eligible[0].artist_id;
}

/** The `count` albums (one per album-artist) whose album-artist has the most
 * documented neighbors, ties by album id -- the densest default Explore
 * stars, chosen by rule from the committed artifacts so no name is pinned.
 * Each has more than one page of neighbors, so "Show 24 more" is real. */
export async function denseExplorerAlbums(
  count: number,
): Promise<CatalogAlbum[]> {
  const graph = await loadGraph();
  const artistIndex = buildArtistIndex(graph);
  const contributorIndex = readArtifact<{ contributors: Contributor[] }>(
    "contributors/index.v1.json",
  );
  const contributorByArtistId = new Map(
    contributorIndex.contributors.map((c) => [c.artist_id, c]),
  );
  const prominence = readArtifact<{ node_ids: number[]; rank: number[] }>(
    "pathfinding/prominence.v1.json",
  );
  const rankByArtistId = new Map(
    prominence.node_ids.map((id, i) => [id, prominence.rank[i]]),
  );
  const seen = new Set<number>();
  const scored: { album: CatalogAlbum; degree: number }[] = [];
  for (const album of catalogAlbums) {
    if (seen.has(album.artist_id)) continue;
    const view = buildView(
      graph,
      artistIndex,
      contributorByArtistId,
      album.artist_id,
      24,
      rankByArtistId,
    );
    if (!view || !view.truncated) continue;
    seen.add(album.artist_id);
    scored.push({ album, degree: view.totalNeighborCount });
  }
  scored.sort((a, b) => b.degree - a.degree); // stable: id order breaks ties
  if (scored.length < count) {
    throw new Error("fewer dense Explore records than the spec needs");
  }
  return scored.slice(0, count).map((s) => s.album);
}
