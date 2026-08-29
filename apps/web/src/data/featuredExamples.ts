// Deterministic "featured example" picks for the homepage -- each mirrors
// the "deterministic, not hand-picked" discipline the homepage already
// applies to its other featured picks (challenge.paths[0], the first
// contributor with a real interesting_next_step): a stable scan over an
// already-versioned artifact, not a value chosen at render time.

import type { ChallengeV2, PathV2 } from "./challenge";
import { buildHopViews } from "./evidence";
import { behindTheGlassEdgeFilter } from "../game/roleTaxonomy";

/** The first documented path (stable `challenge.paths` array order) where
 * every hop's two endpoints share a real producer/engineer credit pairing
 * on that hop's own release -- reuses `buildHopViews` (already resolves
 * each hop's credit rows) and `behindTheGlassEdgeFilter` (the exact
 * predicate Connect Two Records' own Behind the Glass mode uses), so this
 * can never silently drift from what that mode itself would actually
 * accept. Returns `undefined` if no path in the given artifact qualifies
 * -- callers should render nothing rather than fall back to a guess. */
export function findBehindTheGlassPath(
  challenge: ChallengeV2,
): PathV2 | undefined {
  return challenge.paths.find((path) => {
    const hopViews = buildHopViews(
      path.hops,
      challenge.releases,
      challenge.artists,
    );
    if (hopViews.length !== path.hops.length) return false;
    return path.hops.every((hop, i) => {
      const rolesFor = (artistId: number) =>
        hopViews[i].rows
          .filter((row) => row.artistId === artistId)
          .map((row) => row.role)
          .filter((role): role is string => role !== null);
      const rolesA = rolesFor(hop.artist_a_id);
      const rolesB = rolesFor(hop.artist_b_id);
      return rolesA.some((roleA) =>
        rolesB.some((roleB) => behindTheGlassEdgeFilter(roleA, roleB)),
      );
    });
  });
}
