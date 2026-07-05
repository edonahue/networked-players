# Cohort source contract (schema v1)

This contract describes the provenance record for one operator-saved curated cohort
source (e.g. a "best albums" blog post), produced by
`networked-players-catalog import-cohort-source` and defined in
`packages/catalog/src/networked_players_catalog/cohort_source/source.py`
(`CohortSourceMeta`, `COHORT_SOURCE_VERSION`). See
[ADR 0028](../../docs/decisions/0028-curated-cohort-source-ingestion.md) for the decision
behind this whole ingestion category.

> **Source of truth.** The `CohortSourceMeta` dataclass in `source.py` is authoritative.
> If this document and the code disagree, the code wins and this file should be updated.

## Location and privacy

The raw saved HTML lives at `data/private/source-html/<name>.html` — **never committed**.
`data/private/**` is already git-ignored and denied to agent `Read` access at the tooling
layer (`.claude/settings.json`), the same protection the private release-ID seed uses. This
manifest object records facts *about* the saved source; it never carries the source's
article text or any absolute filesystem path.

## `CohortSourceMeta` — one JSON object

| Field | Type | Null? | Meaning |
| --- | --- | --- | --- |
| `cohort_source_version` | int | no | Schema version of this contract (currently 1). |
| `source_url` | string | no | URL the operator saved the page from. Metadata only — this pipeline never re-fetches it. |
| `page_title` | string | no | Title of the saved source page, as the operator records it. |
| `saved_at` | string (`YYYY-MM-DD`) | no | Date the operator saved the page. |
| `operator_note` | string | no (default `""`) | Free-text operator context. |
| `raw_html_sha256` | string | yes | SHA-256 of the saved HTML file's bytes — an integrity/dedup pointer, never the content. |
| `raw_html_relpath` | string | yes | The saved file's own name only (no directories) — never an absolute or otherwise locatable path. |

## Rules

- **Raw HTML never leaves `data/private/source-html/`.** No code in this project reads it
  from anywhere else, and no artifact derived from it ever embeds its content.
- **This manifest records *about* the source, never the source's own prose.** No article
  text, no reproduced editorial content.
- **No live re-fetch capability exists anywhere in this contract's tooling.** `source_url`
  is provenance only, per [ADR 0028](../../docs/decisions/0028-curated-cohort-source-ingestion.md).
- **`raw_html_relpath` is a bare filename.** Never a path with directory components, so it
  can't reveal where on disk the operator keeps saved sources.
