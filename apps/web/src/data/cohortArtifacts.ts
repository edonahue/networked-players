// The hand-maintained static import map `cohorts.astro` uses to resolve a
// manifest entry's `cohort_id` to its parsed artifact. Vite needs statically
// analyzable import paths, and this project deliberately has no router or
// dynamic-import machinery, so this map is hand-maintained, not generated.
//
// Kept as its own module (rather than declared inline in cohorts.astro) so
// the page and apps/web/tests/cohort-manifest.spec.ts's drift check import
// the exact same object -- a test that re-declared its own copy of this map
// could itself silently drift from the real one.
//
// Adding a second cohort means adding one import line and one map entry
// here, plus a matching entry in apps/web/public/data/cohorts/index.json --
// see docs/COHORT_SOURCE_INGESTION.md for the full three-step process.

import type { PlayableCohort } from "./cohort";
// The `with { type: 'json' }` import attribute is required for this module
// to load under Node's own ESM loader (apps/web/tests/cohort-manifest.spec.ts
// imports this file directly, outside Vite's bundler, which is more lenient
// about bare JSON imports). Astro's own Vite-based build accepts this same
// syntax, so one import statement works in both contexts.
import syntheticExampleArtifact from "../../public/data/cohorts/synthetic-example.playable-v1.json" with { type: "json" };

export const cohortArtifacts: Record<string, PlayableCohort> = {
  "synthetic-example": syntheticExampleArtifact as PlayableCohort,
};
