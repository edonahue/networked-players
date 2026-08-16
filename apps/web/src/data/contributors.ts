// Types for the public contributor index
// (apps/web/public/data/contributors/index.v1.json,
// data/contracts/contributor-index-v1.md, ADR 0048).
//
// Built entirely from challenge.v2.json + routes/{universe,rounds}.v1.json --
// never a fresh full-corpus query. connection_count/neighboring_contributor_ids
// reflect this contributor's degree within those two published artifacts
// only, never the private full corpus.

export interface ContributorEvidence {
  release_id: number;
  role_text: string;
}

/** ADR 0060: one of this contributor's own `neighboring_contributor_ids`
 * whose `role_categories` are entirely disjoint from this contributor's own
 * -- a real structural fact, never an inferred claim about interest or
 * importance. `null` when no neighbor qualifies. */
export interface InterestingNextStep {
  artist_id: number;
  reason: string;
}

export interface Contributor {
  artist_id: number;
  name: string;
  role_categories: string[];
  role_text_examples: string[];
  /** Canonical catalog album ids whose documented path/route this
   * contributor's credits help establish -- not a claim these are "their"
   * albums (see the contract doc's frontend-copy rule). */
  albums: string[];
  decade_activity: number[];
  connection_count: number;
  neighboring_contributor_ids: number[];
  evidence: ContributorEvidence[];
  interesting_next_step: InterestingNextStep | null;
}

export interface ContributorIndex {
  schema_version: number;
  catalog_version: string;
  contributor_index_version: string;
  generated_at: string;
  source: string;
  license: string;
  contributors: Contributor[];
}

/** Display labels for role_taxonomy.RoleCategory values -- presentational only. */
export const ROLE_CATEGORY_LABEL: Record<string, string> = {
  vocals: "Vocals",
  strings: "Strings",
  percussion_keys: "Percussion & Keys",
  brass_woodwind: "Brass & Woodwind",
  production: "Production",
  engineering: "Engineering",
  arrangement: "Arrangement",
  composition: "Composition",
  rework: "Rework",
  packaging_business: "Packaging & Business",
  unknown: "Unclassified",
};
