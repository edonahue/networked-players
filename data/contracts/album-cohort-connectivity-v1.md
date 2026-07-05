# Album-cohort connectivity contract (schema v1)

This contract describes real graph connectivity computed between every pair of resolved
cohort albums (`album-cohort-resolved-v1.md`), produced by
`networked-players-catalog score-cohort-connectivity` and defined in
`packages/graph-core/src/networked_players_graph_core/cohort_connectivity.py`
(`build_connectivity_cohort`, `SCORER_VERSION`). See
[ADR 0029](../../docs/decisions/0029-connectivity-scorer-flags-dont-fix-traversal-gap.md)
for the traversal-gap finding this artifact's quality flags exist to catch.

> **Source of truth.** The functions in `cohort_connectivity.py` are authoritative. If
> this document and the code disagree, the code wins and this file should be updated.

> **This is a local-only intermediate.** Nothing in this pipeline stage publishes this
> artifact anywhere, and it does not write to `data/albums/`. A later, separate,
> explicitly human-reviewed step is required before anything derived from it is ever
> committed.

## Location and privacy

Written wherever the operator points `--output-dir` (conventionally
`local/analysis/cohorts/<source-id>/`, under the git-ignored `local/` tree). This command
also writes `playable-pairs.json` (a filtered/sorted *view* of this same contract — see
"Derived views" below) and `review-report.md` (a plain-markdown human summary) into the
same directory — neither is a separate schema.

## Top-level shape — one JSON object

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | int | Always 1. |
| `source` | object | Carried forward unchanged from `resolved.json`'s own `source`. |
| `scorer_version` | int | Version of the scoring/quality-flag logic (`SCORER_VERSION`), bumped on any material change. |
| `generated_at` | string (UTC ISO 8601) | When scoring ran. |
| `dataset_snapshot_date` | string (`YYYYMMDD`) | The **one-hop** dataset's own snapshot date. Must equal `resolved.json`'s own `dataset_snapshot_date` — `build_connectivity_cohort` refuses to score against a mismatched vintage rather than silently doing so. |
| `max_hops` | int | The bound actually used for every `find_path` call in this run (operator-settable via `--max-hops`, default 3). |
| `pairs` | array | One entry per unordered pair of resolved albums. Never filtered — a pair with no path is kept as `status: "no_path"`, not omitted. |
| `unresolved` | array | Carried forward **unchanged** from `resolved.json`'s own `unresolved[]`, so one file has the complete resolution-and-connectivity picture. |

## `pairs[]` fields

| Field | Type | Null? | Meaning |
| --- | --- | --- | --- |
| `album_a_id` / `album_b_id` | string | no | `album_id` values from the two resolved albums, ordered deterministically (both sorted by `album_id` ascending; `a` is the earlier one). |
| `artist_a_id` / `artist_b_id` | int | no | The corresponding resolved `artist_id`s, same a/b order. |
| `status` | string enum: `"found"` / `"no_path"` | no | Never a third, silently-dropped state. |
| `hop_count` | int | yes (null iff `no_path`) | Number of hops in the found path. |
| `difficulty` | string enum: `"easy"` (1 hop) / `"medium"` (2) / `"hard"` (3) / `"very_hard"` (4+) | yes (null iff `no_path`) | The 4th bucket exists because `--max-hops` is operator-settable, not hardcoded at 3. |
| `hops` | array | `[]` when `no_path` | See below. |
| `warnings` | array of string | no (`[]` when clean) | Human-readable strings surfacing any hop with a concerning `quality_flags` entry, for quick scanning without inspecting every hop. |

## `hops[]` fields

`{release_id: int, artist_a_id: int, artist_b_id: int, quality_flags: list[string]}` — same
field names as `challenge.py`'s existing `paths[].hops[]` shape, for consistency across
artifacts.

**`quality_flags`** always contains exactly one of these three mutually-exclusive
strength flags, plus an optional stackable fourth:

| Flag | Meaning |
| --- | --- |
| `co_billed_release_artists` | Both endpoints have a `credit_scope="release_artist"` credit on this release — a true split/collaboration release. The strongest connection type. |
| `performer_credit` | At least one endpoint has a performer-caliber credit (main-artist or a non-"non-performer-role" credit), but not both are release-artists. The normal expected connection type. |
| `non_performer_only` | Every credit connecting the two endpoints on this release is a non-performer role token (Written-By, Mastered By, Producer, etc.) — the same category [ADR 0026](../../docs/decisions/0026-exclude-placeholder-artists-from-one-hop-frontier.md)/[ADR 0027](../../docs/decisions/0027-exclude-non-performer-roles-from-one-hop-frontier.md) exclude from *retention*, but which can still survive as *evidence* on an already-retained release (evidence completeness is never compromised). Weak, noisy — surfaced for human review, never auto-excluded. |
| `placeholder_artist_hop` (stackable) | Either endpoint's artist ID is a known Discogs placeholder (194 "Various Artists", 151641 "Trad."). `CreditGraph`'s own traversal only excludes 194 from ever appearing as a hop endpoint; 151641 can still appear. Should be rare — seeing it at all warrants real attention. |

## Derived views (not separate schemas)

- **`playable-pairs.json`** — `[p for p in pairs if p.status == "found"]`, sorted by
  `(hop_count, album_a_id, album_b_id)`. Same per-entry shape as `pairs[]`'s found
  entries.
- **`review-report.md`** — plain markdown: header, summary counts, flagged pairs, no-path
  pairs, and unresolved albums carried forward. Every sentence describing a connection
  says **"connected via a shared release credit"** — never "worked with" or "collaborated
  with," per `docs/DATA_AND_RIGHTS.md`'s standing rule against inferring relationships
  from credits.

## Rules

- **Nothing is ever silently dropped.** Unreachable pairs are `status: "no_path"`, not
  omitted; every hop always gets exactly one strength flag, never zero or an ambiguous
  mix.
- **An ID hint / resolved album is trusted; a graph connection through weak evidence is
  flagged, not hidden or auto-excluded.** A human reviews `warnings` before treating a
  flagged pair as genuinely playable.
- **Never implies a relationship beyond a documented credit.** No generated text may say
  a pair of artists "worked with," "collaborated with," or otherwise imply intent,
  friendship, or influence — only that a shared release credit connects them.
- **Validation:** `validate_connectivity()` checks the exact top-level and per-pair/per-hop
  key sets, that `status`/`difficulty` are valid enum values (and that `no_path` pairs have
  null `hop_count`/`difficulty`), that every hop has exactly one strength flag, and scans
  the serialized artifact for the same forbidden substrings prior cohort-pipeline contracts
  check.
