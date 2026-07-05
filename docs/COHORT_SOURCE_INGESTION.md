# Curated cohort source ingestion

## Goal

Turn an operator-saved third-party curated page (e.g. a "best albums" editorial post)
into a small, reviewed gameplay cohort — a second, curated album pool alongside the
hand-typed `data/albums/top-albums-v1.json`. This document covers the whole pipeline:
extracting candidates, resolving them against the real Discogs dataset, scoring real graph
paths between resolved albums, and — after explicit human review — promoting a small,
public playable-cohort artifact. Web integration that consumes a promoted artifact is a
later stage, not covered here.

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
| Selection file (human review decisions) | Private input to the promotion stage | `data/private/cohort-review/`, git-ignored | Never published — reviewer identity and per-pair notes stay local |
| Playable-cohort JSON | The one artifact meant to be committed | `data/albums/cohorts/<source-id>-playable-v1.json` | Published only after explicit human review names specific approved pairs |

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
        │
        ▼
human review of review-report.md
        │
        ▼
data/private/cohort-review/<source-id>-selection.json  (hand-authored, never committed)
        │
        ▼
networked-players-catalog promote-playable-cohort
        │
        ▼
data/albums/cohorts/<source-id>-playable-v1.json
  (data/contracts/playable-cohort-v1.md)
```

The pipeline now runs end-to-end through a web shell: `apps/web/src/pages/cohorts.astro`
(`apps/web/src/data/cohort.ts`) renders a promoted `playable-cohort-v1` artifact with the
same guess/reveal framing `play/[album].astro` already established, sourced from a small
manifest (`apps/web/public/data/cohorts/index.json`) rather than a single hardcoded
import. It currently lists only one entry, a bundled, clearly-marked synthetic fixture
(`apps/web/public/data/cohorts/synthetic-example.playable-v1.json`, `status:
"synthetic"`) — no real cohort exists yet. Generating and reviewing a real cohort from an
operator-saved source is the next actual step, gated by explicit human review through
`promote-playable-cohort`'s selection file exactly as
[ADR 0031](decisions/0031-human-reviewed-cohort-promotion.md) specifies; nothing publishes
a real cohort automatically.

**A committed `playable-cohort-v1.json` is not automatically web-visible.** Promotion
(below) only writes `data/albums/cohorts/<source-id>-playable-v1.json`; making it
appear on `/cohorts/` is a separate, later, explicit step: an operator adds an entry with
`status: "reviewed"` to `apps/web/public/data/cohorts/index.json` plus a matching static
import in `cohorts.astro` (Vite needs a statically analyzable import path, not a router),
done only after the artifact is already committed via the review gate above.

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

## Promotion (summary)

`packages/graph-core/src/networked_players_graph_core/cohort_promote.py` is the explicit,
human-reviewed step `docs/DATA_AND_RIGHTS.md`/`docs/PUBLIC_PRIVATE_BOUNDARY.md` already
anticipated — deliberately pure Python (no `CreditGraph`/DuckDB), since it only reads
already-computed JSON. An operator hand-authors a small selection file naming which
`connectivity.json` pairs to approve; `promote_playable_cohort` refuses (never silently
skips) an approved pair that's absent from `connectivity.json`, not `status: "found"`, or
flagged (`warnings[]` non-empty) without an explicit `allow_flagged_pairs` opt-in
(cohort-wide or per-pair). The resulting `playable-cohort-v1.json` is deliberately
narrower than any local intermediate — only `attribution_label`/`source_url` survive from
the source's own metadata, no prose, no raw HTML, no reviewer identity, no per-pair private
notes. See `data/contracts/playable-cohort-v1.md` and
[ADR 0031](decisions/0031-human-reviewed-cohort-promotion.md) for the full design and why a
selection file was chosen over CLI-flag pair selection. `connectivity.json` and
`playable-cohort-v1.json` can each be independently re-validated later — locally via
`validate-connectivity`/`validate-playable-cohort`, or as a bounded Pi ambient job (see
`docs/OPERATOR_SETUP.md`'s "Pi ambient cohort-artifact checks") — without re-running the
pipeline that produced them.

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
even that stays local until the explicit `promote-playable-cohort` review step names
specific approved pairs.
