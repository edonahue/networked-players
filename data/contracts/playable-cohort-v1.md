# Playable-cohort contract (schema v1)

This contract describes the small, public artifact produced by
`networked-players-catalog promote-playable-cohort` — the first artifact in the curated
cohort pipeline meant to leave `local/`/`data/private/` and be committed. Defined in
`packages/graph-core/src/networked_players_graph_core/cohort_promote.py`
(`promote_playable_cohort`, `PLAYABLE_COHORT_SCHEMA_VERSION`). See
[ADR 0031](../../docs/decisions/0031-human-reviewed-cohort-promotion.md) for why promotion
requires an explicit, human-authored selection file rather than any automatic threshold.

> **Source of truth.** `cohort_promote.py` owns promotion and
> `packages/contracts/src/networked_players_contracts/cohort.py` owns the dependency-free
> validator used by graph-core and constrained workers. If this document and the code
> disagree, the code wins and this file should be updated.

> **This is the one artifact in this pipeline meant to be committed.** Everything upstream
> (`extracted.json`, `resolved.json`, `connectivity.json`, `playable-pairs.json`,
> `review-report.md`) stays local-only. A real, Discogs-derived playable cohort should only
> be committed after Erich has reviewed it and explicitly said so — this contract's own
> tests use synthetic fixtures only.

## Promotion inputs

`promote-playable-cohort` takes three files, never re-deriving anything already computed
upstream:

1. **`--resolved`** — `album-cohort-resolved-v1.json`. The only place album `title` /
   `artist_name` / `year` metadata lives; `connectivity.json`'s `pairs[]` carries only IDs.
2. **`--connectivity`** — `album-cohort-connectivity-v1.json`. Source of `status`, `hops`,
   `quality_flags`, and `warnings` for every candidate pair.
3. **`--selection`** — an operator-authored, **private-only** review file. Not a
   `data/contracts/` schema of its own (it's hand-authored, not machine-generated); its
   shape is documented here instead:

   ```json
   {
     "schema_version": 1,
     "reviewed_by": "Erich",
     "reviewed_at": "2026-07-05T12:00:00+00:00",
     "review_note": "Optional cohort-level note, published if present.",
     "allow_flagged_pairs": false,
     "approved_pairs": [
       {
         "album_a_id": "master-123",
         "album_b_id": "master-456",
         "review_note": "Private-only note to self; never published.",
         "allow_flagged_pairs": false
       }
     ]
   }
   ```

   | Field | Type | Meaning |
   | --- | --- | --- |
   | `schema_version` | int | Always 1. |
   | `reviewed_by` | string | Reviewer name. **Never published** — kept out of the promoted artifact deliberately. |
   | `reviewed_at` | string (UTC ISO 8601) | When review happened. Carried into the promoted artifact's own `reviewed_at`. |
   | `review_note` | string, optional | Cohort-level reviewer note. If present, carried into the promoted artifact's own `review_note`. |
   | `allow_flagged_pairs` | bool, default `false` | Cohort-wide override letting *every* flagged pair (non-empty `warnings`) in `approved_pairs` through. |
   | `approved_pairs[]` | array | Which pairs to promote. Each entry's own `review_note` is private-only (never published); each entry's own `allow_flagged_pairs` overrides the cohort-wide setting for just that pair. |

   Conventionally lives at `data/private/cohort-review/<source-id>-selection.json` —
   already covered by the existing blanket `data/private/**` gitignore rule, no new rule
   needed.

## Top-level shape — one JSON object

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | int | Always 1. |
| `cohort_id` | string | Operator-supplied via `--cohort-id`. No upstream artifact stores a cohort/source identifier — this is a new, explicit, required input, not derived from anything. |
| `attribution_label` | string | `resolved["source"]["page_title"]` — the source page's own title, for on-page "via ..." attribution. |
| `source_url` | string | `resolved["source"]["source_url"]`. |
| `generated_from_scorer_version` | int | Carried from `connectivity["scorer_version"]`, for provenance. |
| `reviewed_at` | string (UTC ISO 8601) | From the selection file. |
| `review_note` | string or null | Optional cohort-level reviewer note, from the selection file's own `review_note` (not a per-pair one — those stay private). |
| `albums` | array | See below. Only albums referenced by at least one promoted pair. |
| `pairs` | array | See below. Only promoted, confirmed-`"found"` pairs. |

## `albums[]` fields

`{id, artist_id, artist, title, year}` — the same minimal, already-public-per-Discogs
factual metadata `docs/DATA_AND_RIGHTS.md`'s "Curated third-party source pages" section
already allows (artist, title, year, a Discogs identifier). No `master_id`/`release_id`
split, no cover art, no resolution provenance — this artifact is deliberately narrower than
`resolved.json`.

## `pairs[]` fields

`{album_a_id, album_b_id, artist_a_id, artist_b_id, difficulty, hop_count, hops, warnings}`
— the same field names and meanings as `album-cohort-connectivity-v1.md`'s own `pairs[]`,
minus `status` and `skip_reason`. Both are dropped because every entry here is implicitly
promoted-and-`"found"` — there is no other way for a pair to appear in this artifact.
`hops[]` is unchanged: `{release_id, artist_a_id, artist_b_id, quality_flags}`.

`warnings[]` is retained, not stripped, when a flagged pair was explicitly approved via
`allow_flagged_pairs` — a human already reviewed it; hiding the warning after the fact would
remove exactly the context that justified promoting it.

## Explicitly never carried forward

- `source.saved_at`, `operator_note`, `raw_html_sha256`, `raw_html_relpath` — all
  local-only per `cohort-source-v1.md`'s own rules; none of them are needed to play the
  game.
- `unresolved[]` — could contain extracted text a human deliberately chose not to promote;
  never published.
- `dataset_snapshot_date` — an internal pipeline detail, not needed to play the game.
- Any album with zero promoted pairs, or any pair not explicitly named in
  `approved_pairs[]`.
- `reviewed_by` and any per-pair `review_note` from the selection file — reviewer identity
  and private notes-to-self stay local.

This is a deliberate divergence from `album-cohort-connectivity-v1.md`'s "carry
`unresolved` forward unchanged" rule — that rule exists for local review completeness; a
public artifact has the opposite goal (minimum necessary surface).

## Rules

- **An approved pair that can't be honored raises, never silently drops or reinterprets.**
  A pair named in `approved_pairs[]` but absent from `connectivity.json` (a likely typo),
  not `status: "found"` (an unreachable or unconfirmed pair can never be promoted), or
  flagged without an explicit `allow_flagged_pairs` (cohort-wide or per-pair) always raises
  `CohortPromoteError`.
- **A flagged pair requires one explicit, unified opt-in.** `warnings[]` is already
  populated by `cohort_connectivity.py` exactly for the two weak-connection categories
  (`non_performer_only`, `placeholder_artist_hop`) — there is one `allow_flagged_pairs`
  check, not three separate rules duplicating that logic.
- **Never an empty artifact.** Zero promoted pairs raises rather than writing a
  vacuous file, mirroring `export_graph_snapshot`'s existing "refuse to write an empty
  snapshot" precedent.
- **Never implies a relationship beyond a documented credit.** Same standing rule as every
  other cohort artifact: no generated or reviewer-authored text may say "worked with,"
  "collaborated with," or "influenced" — `validate_playable_cohort` scans the serialized
  artifact for all three, in addition to the standard forbidden-substring scan.
- **Validation:** `validate_playable_cohort()` checks the exact top-level/per-album/
  per-pair/per-hop key sets, that every pair's `album_a_id`/`album_b_id` reference a
  published album, that `difficulty` is a valid enum value, that every hop has exactly one
  strength flag, and scans the serialized artifact for the same forbidden substrings prior
  cohort-pipeline contracts check plus the tone-phrase scan above.
