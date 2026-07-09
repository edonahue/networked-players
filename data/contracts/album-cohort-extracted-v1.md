# Album-cohort extracted-candidates contract (schema v1)

This contract describes the album-candidate list extracted from one saved cohort source,
produced by `networked-players-catalog import-cohort-source` and defined in
`packages/catalog/src/networked_players_catalog/cohort_source/extract.py`
(`ExtractedCandidatesArtifact`, `CANDIDATE_SCHEMA_VERSION`).

> **Source of truth.** The dataclasses in `extract.py` are authoritative. If this document
> and the code disagree, the code wins and this file should be updated.

> **This is a local-only intermediate.** Nothing in this pipeline publishes this artifact
> anywhere, and it does not write to `data/albums/`. A later, separate, explicitly
> human-reviewed step is required before anything derived from it is ever committed.

## Location and privacy

Written wherever the operator points `--output` (conventionally
`local/analysis/cohorts/<source-id>/extracted.json`, under the git-ignored `local/` tree).
Not itself under `data/private/`, but carries no pointer back into it either — see `source`
below.

## Top-level shape — one JSON object

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | int | Always 1. |
| `source` | object | A subset of `cohort-source-v1.md`'s fields: **only** `source_url`, `page_title`, `saved_at`, `operator_note`. Deliberately excludes `raw_html_sha256`/`raw_html_relpath` — this artifact carries no pointer into `data/private/`. |
| `extractor_version` | int | Version of the extraction heuristic (`EXTRACTOR_VERSION` in `extract.py`), bumped on any material parsing-rule change. |
| `generated_at` | string (UTC ISO 8601) | When the extraction ran. |
| `notes` | array of string | Source-level extraction notes (e.g. `"no candidate entries detected"`). Distinct from per-candidate `warnings` below. |
| `candidates` | array | One row per detected entry, in source order. |

## `candidates[]` fields

| Field | Type | Null? | Meaning |
| --- | --- | --- | --- |
| `rank` | int | yes | Numbered position in the source, when detectable. |
| `artist` | string | yes | Extracted artist text, verbatim from the source — never normalized or matched against any Discogs dataset. |
| `title` | string | yes | Extracted title text, verbatim from the source. |
| `year` | int | yes | 4-digit year, when visibly present. |
| `master_id` | int | yes | Populated **only** when a literal `/master/<id>` link was visible for this entry. Never inferred. |
| `release_id` | int | yes | Same rule, for a literal `/release/<id>` link. |
| `confidence` | string enum: `"high"` / `"medium"` / `"low"` | no | Confidence in the *extraction itself* — never a claim about the album's merit or the ranking's validity. |
| `warnings` | array of string | no | Empty when nothing to flag; otherwise explains uncertainty (no link found, no year found, could not separate artist from title, detected via the non-list fallback heuristic, no rank/title/artist element found in a release-card block). |

## Rules

- **Records are never dropped.** A candidate with missing or ambiguous data is still
  emitted, with the affected field left `null` and a `warnings` entry explaining why — the
  same evidence-preservation spirit `packages/catalog/discogs` applies to non-linked
  credit names.
- **`master_id`/`release_id` are never guessed.** Populated only from a literal Discogs
  link visible in the source HTML.
- **No resolution against the real Discogs dataset happens here.** `artist`/`title` are
  raw extracted text; a later cohort-resolver stage is responsible for matching them
  against `local/processed/`.
- **Validation:** `validate_extracted_candidates()`
  (`packages/catalog/src/networked_players_catalog/cohort_source/validation.py`) checks
  the exact top-level and per-object key sets, that `confidence` is one of the three
  allowed values, that `master_id`/`release_id` are positive ints or null, and scans the
  serialized artifact for forbidden substrings (`/home/`, `data/private`, `local/`,
  `DISCOGS_TOKEN`, `.ssh`) as defense in depth even though nothing is published yet.
