# Album-cohort resolved-candidates contract (schema v1)

This contract describes extracted cohort candidates
(`album-cohort-extracted-v1.md`) after resolution against a real parsed
Discogs dataset, produced by `networked-players-catalog resolve-cohort` and
defined in `packages/graph-core/src/networked_players_graph_core/cohort_resolve.py`
(`resolve_candidates`, `RESOLVER_VERSION`).

> **Source of truth.** The functions in `cohort_resolve.py` are authoritative. If this
> document and the code disagree, the code wins and this file should be updated.

> **This is a local-only intermediate.** Nothing in this pipeline stage publishes this
> artifact anywhere, and it does not write to `data/albums/`. A later, separate,
> explicitly human-reviewed step is required before anything derived from it is ever
> committed.

## Location and privacy

Written wherever the operator points `--output` (conventionally
`local/analysis/cohorts/<source-id>/resolved.json`, under the git-ignored `local/` tree).

## Top-level shape — one JSON object

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | int | Always 1. |
| `source` | object | Carried over unchanged from the extracted-candidates artifact's own `source` field. |
| `resolver_version` | int | Version of the resolution logic (`RESOLVER_VERSION` in `cohort_resolve.py`), bumped on any material change to matching/dedup rules. |
| `generated_at` | string (UTC ISO 8601) | When resolution ran. |
| `dataset_snapshot_date` | string (`YYYYMMDD`) | The real parsed snapshot this was resolved against. |
| `resolved` | array | One entry per successfully resolved candidate. |
| `unresolved` | array | One entry per candidate that could not be resolved — the ambiguity report. |

## `resolved[]` fields

| Field | Type | Null? | Meaning |
| --- | --- | --- | --- |
| `rank` | int | yes | Carried over from the extracted candidate. |
| `artist_query` / `title_query` | string | yes | The raw extracted text this candidate was resolved from. |
| `resolution_method` | string enum: `"release_id_hint"` / `"master_id_hint"` / `"title_artist_match"` | no | Which strategy actually resolved this candidate. |
| `master_id` | int | yes | The resolved release's master, if it has one. |
| `release_id` | int | no | The resolved release — always the master's main release when the release belongs to a master, even if a `release_id` hint pointed at a different pressing (never overfits to a specific reissue). |
| `title` | string | no | The resolved release's real title (not necessarily identical to `title_query` — case/formatting may differ). |
| `artist_id` | int | no | The resolved release-artist's real Discogs artist ID. Unique across `resolved[]` — see dedup rule below. |
| `artist_name` | string | no | The resolved artist's most common credited name in this dataset. |
| `year` | int | yes | From the resolved release's `released` field when parseable, else carried over from the extracted candidate. |
| `extraction_confidence` | string | no | Carried over from the extracted candidate's own `confidence` — resolution success is orthogonal to extraction confidence; both are kept for review. |
| `warnings` | array of string | no | Empty except when an ID-hint resolution's real title/artist doesn't resemble `title_query`/`artist_query` at all — a strong signal the source HTML's link was mislinked to the wrong entry. The ID is still trusted (never silently overridden by text), but flagged for human review. Never populated for `"title_artist_match"` resolutions, since those already matched the text exactly by construction. |

## `unresolved[]` fields

Every field from the original extracted candidate (`rank`, `artist`, `title`, `year`,
`master_id`, `release_id`, `confidence`, `warnings`), plus:

| Field | Type | Meaning |
| --- | --- | --- |
| `reason` | string | Why resolution failed: missing artist/title text with no ID hint, an ID hint that doesn't exist in this dataset, no title/artist match found, or a resolved `artist_id` that a rank-earlier candidate in this same cohort already claimed. |

## Rules

- **An ID hint is trusted, but a large text mismatch is flagged, not hidden.** An explicit
  `master_id`/`release_id` always wins over text — real Discogs IDs span a huge numeric
  range, and a source HTML page's link can be mislinked to the wrong list entry. When that
  happens, the resolved `title`/`artist_name` won't resemble `title_query`/`artist_query`
  at all; `warnings` flags this for human review rather than silently accepting a likely-
  wrong ID or silently overriding it with a guess.
- **An ID hint is never silently abandoned for a text guess without saying so.** If
  `master_id`/`release_id` is present but doesn't resolve in this dataset, resolution
  falls back to a title/artist match only if both are present — and either way, the
  actual `resolution_method` (or the `unresolved` reason) always says which path was
  taken.
- **A `release_id` hint that names a non-main pressing is redirected to that master's
  actual main release.** Never overfit to a specific reissue.
- **One resolved album per `artist_id`.** A cohort needs one artist per album for
  `CreditGraph.find_path` to compare pairs meaningfully; a candidate that resolves to an
  already-used `artist_id` is reported unresolved (with a reason), not silently merged
  or dropped without explanation.
- **Nothing is ever guessed.** Both the resolver and its underlying `CreditGraph` methods
  return "not found" rather than a best-effort guess when a hint or text query doesn't
  match anything real.
- **Validation:** `validate_resolved_cohort()` checks the exact top-level and
  per-resolved-entry key sets, that `resolution_method` is one of the three allowed
  values, that no `artist_id` repeats in `resolved[]`, and scans the serialized artifact
  for the same forbidden substrings `album-cohort-extracted-v1.md` checks.
