# Discogs ingestion references

Reviewed for the initial ingestion foundation on 2026-06-29.

## Primary sources

- Discogs monthly data-dump landing page: dump types, XML format, and CC0 statement.
- Discogs API Terms of Use: CC0 versus restricted data, attribution/linking, freshness, credentials, and user-associated data restrictions.
- Discogs Database Guidelines: release, artist, credit, track position, and role semantics.

## Implementation comparisons

- `discogskit`: contemporary Python converter/loader using lxml, PyArrow, chunked parsing, and parallel workers. It is a useful benchmark and possible future dependency evaluation, but Networked Players keeps a small project-specific parser now so evidence semantics and constrained-hardware behavior remain explicit.
- `dgtools` Parquet benchmark: August 2025 record counts, conversion timing, and compressed XML/Parquet sizes used in `DATA_SIZING.md`.
- The Ogger Club dump statistics: independent monthly record-count corroboration used only for growth planning, not as the source of catalog facts.

External references are research inputs. Their code and licenses are not copied into this repository.
