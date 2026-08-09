// Role-signal explanation for a documented alternate route (ADR 0051,
// renamed post-Phase-4 cleanup audit -- see that ADR's addendum). Never a
// ranking or a hidden score: `findAlbumRoute`'s "distinct alternate route"
// is plain BFS with the first route's edges excluded, found or not found,
// nothing more. `explainScore` only produces a human-readable, after-the-
// fact description of an already-found route -- it never selects between
// candidates.

import type { PathHop } from "./pathfindingGraph";
import type { Contributor } from "../data/contributors";

const PERFORMANCE_CATEGORIES = new Set([
  "vocals",
  "strings",
  "percussion_keys",
  "brass_woodwind",
]);

/** A contributor's connection_count (their degree within the published
 * contributor-index graph, not the private full corpus) above this is
 * treated as a "hub" for explanation purposes -- a prolific session
 * engineer or mastering engineer who plausibly connects almost anything to
 * almost anything, which is documented but not musically distinctive. */
const HUB_CONNECTION_COUNT_THRESHOLD = 20;

function isPerformanceContributor(
  contributor: Contributor | undefined,
): boolean {
  if (!contributor) return false;
  return contributor.role_categories.some((category) =>
    PERFORMANCE_CATEGORIES.has(category),
  );
}

/** Every distinct artist_id appearing anywhere in the path (bridge
 * contributors are visited once by construction -- `findPath`'s BFS never
 * revisits a node, so within one path a "repeated hub across non-adjacent
 * hops" cannot occur; the real hub signal is a single contributor's own
 * degree, not repetition within this path). */
function uniqueArtistIds(hops: PathHop[]): Set<number> {
  const ids = new Set<number>();
  for (const hop of hops) {
    ids.add(hop.artist_a_id);
    ids.add(hop.artist_b_id);
  }
  return ids;
}

/** A human-readable breakdown rendered directly in the UI for the distinct
 * alternate route -- names hop count, whether a performer bridges any hop,
 * and whether a high-degree hub contributor appears. Purely descriptive:
 * it never influences which route was found, only how it's explained. */
export function explainScore(
  hops: PathHop[],
  contributorByArtistId: Map<number, Contributor>,
): string[] {
  const explain: string[] = [
    `${hops.length} hop${hops.length === 1 ? "" : "s"}`,
  ];

  const performerHops = hops.filter(
    (hop) =>
      isPerformanceContributor(contributorByArtistId.get(hop.artist_a_id)) ||
      isPerformanceContributor(contributorByArtistId.get(hop.artist_b_id)),
  );
  if (performerHops.length > 0) {
    explain.push(
      `bridged by a performer at ${performerHops.length} of ${hops.length} hop${
        hops.length === 1 ? "" : "s"
      }`,
    );
  }

  const hasHighDegreeHub = [...uniqueArtistIds(hops)].some(
    (artistId) =>
      (contributorByArtistId.get(artistId)?.connection_count ?? 0) >
      HUB_CONNECTION_COUNT_THRESHOLD,
  );
  explain.push(
    hasHighDegreeHub
      ? "passes through a highly-connected hub contributor"
      : "no highly-connected hub in this path",
  );

  return explain;
}
