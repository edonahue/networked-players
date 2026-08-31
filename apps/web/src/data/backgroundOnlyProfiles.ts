// Types for the public background-only-profiles artifact
// (apps/web/public/data/contributors/background-only-profiles.v1.json,
// data/contracts/background-only-profiles-v1.md, ADR 0048/0060 addendum).
//
// A companion to contributors.ts's ContributorIndex, deliberately a
// separate artifact rather than a field on it -- that index is
// runtime-fetched by already-loaded client JS and validated as an exact
// key set, so adding a new required key to it is not a safe in-place
// change (the same reasoning albumHopDistances.ts already documents).
//
// Also closes a real gap the published ContributorIndex's own
// role_text_examples couldn't: that field is capped to the five most
// frequent role strings, so a contributor with several frequent
// background-engineering credits and one rarer substantive one could be
// misjudged "background-only" if inferred from the capped sample alone (a
// real review finding). This artifact is built server-side from each
// contributor's full, uncapped role-text vocabulary instead.

export interface BackgroundOnlyProfiles {
  schema_version: number;
  catalog_version: string;
  background_only_profiles_version: string;
  generated_at: string;
  source: string;
  license: string;
  artist_ids: number[];
}

/** A Set for O(1) `artist_id` membership checks -- the artifact's
 * `artist_ids` is already sorted, but membership is all any caller needs. */
export function backgroundOnlyArtistIdSet(
  profiles: BackgroundOnlyProfiles,
): Set<number> {
  return new Set(profiles.artist_ids);
}
