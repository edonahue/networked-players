# Curated cohort source ingestion

## Goal

Turn an operator-saved third-party curated page (e.g. a "best albums" editorial post)
into a small, reviewed gameplay cohort — a second, curated album pool alongside the
hand-typed `data/albums/top-albums-v1.json`. This document covers the ingestion stage
only (extracting candidates from a saved page); resolving those candidates against the
real Discogs dataset and scoring graph connectivity are later pipeline stages.

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
| Extracted-candidates JSON | Local-only intermediate for a later resolver stage | `local/analysis/cohorts/<source-id>/`, git-ignored | Not published by this stage |

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
```

Later stages (not built yet): resolve candidates against the real parsed dataset, score
1–3 hop graph connectivity between resolved albums, human review, and — only after
explicit review — publication of a reviewed cohort.

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
