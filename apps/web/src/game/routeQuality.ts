// Transparent "more musical route" scoring over an already-found path
// (ADR 0051). Never a new inferred edge or a hidden score -- a presentation
// ordering over the same evidence, with an explicit rendered explanation
// (explainScore) for every score this module produces.

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

/** Higher for hops bridged by a performer (vocals/strings/percussion-keys/
 * brass-woodwind) rather than purely production/business/composition
 * credits -- an explicit, labeled "more musical" signal, never presented as
 * more real or more important than the shortest documented route. */
export function roleSignalScore(
  hops: PathHop[],
  contributorByArtistId: Map<number, Contributor>,
): number {
  let score = 0;
  for (const hop of hops) {
    if (isPerformanceContributor(contributorByArtistId.get(hop.artist_a_id)))
      score += 1;
    if (isPerformanceContributor(contributorByArtistId.get(hop.artist_b_id)))
      score += 1;
  }
  return score;
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

/** Penalizes a path for passing through high-degree hub contributors --
 * summed log-degree over every distinct contributor in the path, so one
 * very prolific session player contributes one penalty, not one per hop
 * they happen to touch. */
export function hubPenalty(
  hops: PathHop[],
  contributorByArtistId: Map<number, Contributor>,
): number {
  let penalty = 0;
  for (const artistId of uniqueArtistIds(hops)) {
    const contributor = contributorByArtistId.get(artistId);
    if (contributor) penalty += Math.log10(1 + contributor.connection_count);
  }
  return penalty;
}

/** Overall "more musical" score -- fewer hops dominate, then role signal,
 * then hub penalty as a tiebreaker. Only ever used to REORDER two already-
 * found, equally-documented paths; never used to manufacture a path that
 * wasn't found by the shortest-path search. */
export function scorePath(
  hops: PathHop[],
  contributorByArtistId: Map<number, Contributor>,
): number {
  return (
    -hops.length * 100 +
    roleSignalScore(hops, contributorByArtistId) * 10 -
    hubPenalty(hops, contributorByArtistId)
  );
}

/** A human-readable breakdown rendered directly in the UI -- the
 * differentiator from every other mode's single verdict. Never a black-box
 * number. */
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
