"""Curated cohort source ingestion: turns an operator-saved third-party page
(e.g. an editorial "best albums" post) into a small, reviewed set of album
candidates for a gameplay cohort.

Deliberately separate from `networked_players_catalog.discogs`: everything in
that package parses data Discogs itself produced (dumps, the REST API, a
private collection export). This package parses third-party editorial web
content that merely *sometimes references* Discogs -- a structurally and
legally different kind of input, per docs/decisions/0028-curated-cohort-source-ingestion.md.

There is no live fetching anywhere in this package, and none will be added --
see ADR 0028. Raw saved HTML is never committed and never read by anything
other than `extract.py`.
"""

from __future__ import annotations
