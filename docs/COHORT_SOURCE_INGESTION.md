# Curated cohort source ingestion

## Goal

Turn an operator-saved third-party curated page (e.g. a "best albums" editorial post)
into a small, reviewed gameplay cohort — a second, curated album pool alongside the
hand-typed `data/albums/top-albums-v1.json`. This document covers ingestion, resolution,
and connectivity scoring (extracting candidates, resolving them against the real Discogs
dataset, then scoring real graph paths between resolved albums); human review and any
eventual publication are later pipeline stages.

## Non-negotiable posture

**Saved-HTML import only. No live fetching of any URL exists in this pipeline, anywhere,
under any flag — not now, not later.** See
[ADR 0028](decisions/0028-curated-cohort-source-ingestion.md) for why this is locked in
rather than left as a future option. The operator saves a page manually (however they
choose); this project never requests it over the network. This also means: no bypassing
Discogs' or any other site's 403/429/Cloudflare/login/CAPTCHA controls, because there is
no request to bypass them with.

**Naming.** This capability is "curated source ingestion" or "cohort source importer" —
never "crawler" or "scraper," in code, docs, commit messages, or CLI help text. Those
words describe automated, recursive, live-fetching systems this project deliberately does
not build.

## Source roles

| Source | Project use | Retention | Publication posture |
| --- | --- | --- | --- |
| Operator-saved HTML page | Extract album candidates (rank, artist, title, year, Discogs master/release link when visible) | Raw HTML: local only, `data/private/source-html/`, never committed | Never publish the page's own prose or selection; only minimal factual metadata, and only after a later human-reviewed promotion step |
| Extracted-candidates JSON | Local-only intermediate for the resolver stage | `local/analysis/cohorts/<source-id>/`, git-ignored | Not published by this stage |
| Resolved-candidates JSON | Local-only intermediate for the connectivity-scoring stage | `local/analysis/cohorts/<source-id>/`, git-ignored | Not published by this stage |
| Connectivity/playable-pairs JSON, review report | Local-only intermediates for human review | `local/analysis/cohorts/<source-id>/`, git-ignored | Not published by this stage |

## Pipeline (this document's scope)

```text
operator saves a page as HTML (manual, out of band)
        │
        ▼
data/private/source-html/<name>.html  (never committed)
        │
        ▼
networked-players-catalog import-cohort-source
        │
        ▼
local/analysis/cohorts/<source-id>/extracted.json
  (data/contracts/album-cohort-extracted-v1.md)
        │
        ▼
networked-players-catalog resolve-cohort  (against a real parsed dataset)
        │
        ▼
local/analysis/cohorts/<source-id>/resolved.json
  (data/contracts/album-cohort-resolved-v1.md)
        │
        ▼
networked-players-catalog score-cohort-connectivity  (against a one-hop dataset)
        │
        ▼
local/analysis/cohorts/<source-id>/{connectivity.json, playable-pairs.json, review-report.md}
  (data/contracts/album-cohort-connectivity-v1.md)
```

Later stages (not built yet): human review of the review report, and — only after
explicit review — publication of a reviewed cohort to the web.

## Connectivity scoring (summary)

`packages/graph-core/src/networked_players_graph_core/cohort_connectivity.py` computes a
real graph path between every pair of resolved albums (never dropping an unreachable pair
— it's reported as `status: "no_path"`), bucketing difficulty by hop count. It also
catches a real gap: `CreditGraph`'s own traversal does not re-apply ADR 0026/0027's
placeholder-artist and non-performer-role exclusions from one-hop dataset construction, so
a hop can still run through a "Trad." credit or a Mastered-By-only credit if it survives as
evidence on an already-retained release. Every hop gets a `quality_flags` entry so this is
visible for human review, never silently hidden or auto-excluded — see
[ADR 0029](decisions/0029-connectivity-scorer-flags-dont-fix-traversal-gap.md) and
`data/contracts/album-cohort-connectivity-v1.md` for the full flag taxonomy.

**Performance.** A real hub artist (a legitimately prolific person, thousands of
co-credits) can make naive per-pair path-finding hang. `score_pairs` instead runs one
bounded search per unique cohort artist, sharing a cache so a hub is queried at most once
per run regardless of how many pairs it sits on, with `--max-frontier-expansion` and
`--pair-timeout-seconds` as operator-tunable guardrails — see
[ADR 0030](decisions/0030-cohort-scoped-connectivity-substrate.md). A pair whose
reachability couldn't be confirmed within those guardrails is reported as
`status: "skipped"` with a `skip_reason`, never conflated with a confirmed `"no_path"`.
Re-run with a larger `--max-frontier-expansion`/`--pair-timeout-seconds` to resolve a
skipped pair. Heavy real-dataset runs (the real one-hop dataset, not a synthetic fixture)
belong on whichever host has that dataset locally — for real work, that's the fleet's
dedicated x86 worker, not the coordination host and never a Pi.

## Resolution (summary)

`packages/graph-core/src/networked_players_graph_core/cohort_resolve.py` resolves each
extracted candidate against a real parsed dataset opened via `CreditGraph`. An explicit
`master_id`/`release_id` hint is tried first (via `CreditGraph.find_release_by_id_hint`,
which redirects a non-main pressing to its master's actual main release rather than
overfitting to a specific reissue); when no hint is present or it doesn't resolve in this
dataset, resolution falls back to `find_release_by_title_artist`'s exact text match. A
candidate whose resolved artist is already claimed by an earlier candidate in the same
cohort is reported unresolved, not silently duplicated — one artist per album is required
for a later connectivity-scoring stage to compare pairs meaningfully. See
`data/contracts/album-cohort-resolved-v1.md` for the full schema and dedup rule.

## Extraction heuristic (summary)

`packages/catalog/src/networked_players_catalog/cohort_source/extract.py` parses
candidate blocks from `<ol>/<li>` list items (falling back to headings/paragraphs for
non-list layouts), splits a leading rank prefix, splits artist/title on a dash or
`"... by ..."`, extracts a trailing four-digit year, and scans each block's links for a
literal `/master/<id>` or `/release/<id>` Discogs URL. **Nothing is ever inferred**: a
missing year, link, or artist/title split leaves that field `null` and appends a
`warnings` entry — the record is never dropped. See
`data/contracts/album-cohort-extracted-v1.md` for the full schema.

## Rights and access

See `docs/DATA_AND_RIGHTS.md`'s "Curated third-party source pages" section and
`docs/PUBLIC_PRIVATE_BOUNDARY.md`. In short: the source author's editorial selection and
prose are never republished; only Discogs-shaped factual metadata is ever extracted, and
even that stays local until an explicit, separate review step.
