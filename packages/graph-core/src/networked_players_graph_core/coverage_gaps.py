"""Measure catalog composition along source-supported, non-sensitive
dimensions -- the input Bucket C's coverage-gap picks are chosen from
(Phase 7, Workstream 1C).

Deliberately measures only what Discogs' own structured metadata directly
supports: release decade, master genre/style, and (when a release's country
field is populated and meaningful) release geography. Never infers an
artist's race, ethnicity, gender identity, sexuality, or nationality from a
name, image, or cultural assumption -- there is no function here that reads
an artist name or biography at all, only `masters.genres`/`masters.year` and
`releases.country`, exactly the fields the mission brief names as acceptable.

This module measures; it does not select. Bucket C's actual eight picks are
a human/tooling decision made from this module's output plus the real
eligibility and marginal-value checks every other addition goes through --
see `analysis.py`/`candidate_review.py` for those.
"""

from __future__ import annotations

from collections import Counter
from typing import Any


def _decade(year: int | None) -> str:
    if year is None:
        return "unknown"
    return f"{(int(year) // 10) * 10}s"


def catalog_composition(
    albums: list[dict[str, Any]],
    masters_by_id: dict[int, dict[str, Any]],
) -> dict[str, Counter[str]]:
    """Decade, genre, and style counts over a list of catalog-shaped album
    dicts (each carrying at least `master_id` and, as a fallback, `year`).

    A master present in `masters_by_id` supplies the authoritative original
    year and Discogs' own genre/style classification (the same source
    `album_policy.master_non_studio_reason` already trusts for eligibility).
    An album whose master isn't in the lookup falls back to its own `year`
    field for the decade count only -- it contributes nothing to genre/style
    counts, since there is no honest source for those without the master.
    A master can carry more than one genre or style; each is counted once
    per album, so counts do not sum to the album count and that is expected
    -- a Rock/Funk album counts once in each bucket, not fractionally.
    """
    decades: Counter[str] = Counter()
    genres: Counter[str] = Counter()
    styles: Counter[str] = Counter()

    for album in albums:
        master_id = album.get("master_id")
        master = masters_by_id.get(master_id) if master_id is not None else None
        if master is not None:
            decades[_decade(master.get("year"))] += 1
            for genre in master.get("genres") or []:
                genres[genre] += 1
            for style in master.get("styles") or []:
                styles[style] += 1
        else:
            decades[_decade(album.get("year"))] += 1

    return {"decades": decades, "genres": genres, "styles": styles}


def identify_underrepresented(
    composition: dict[str, Counter[str]],
    *,
    known_vocabulary: dict[str, frozenset[str]] | None = None,
    min_count: int = 3,
) -> list[dict[str, Any]]:
    """Flag buckets with zero or few members -- the measured gaps a
    coverage-gap pick is chosen to close.

    `known_vocabulary`, when given, is `{"decades": {...}, "genres": {...},
    "styles": {...}}` -- a set of real, Discogs-sourced values known to exist
    in the wider snapshot (e.g. from a broad query over the full parsed
    masters table) but with fewer than `min_count` representatives in this
    catalog's own `composition`. Without it, only buckets already present at
    a non-zero but thin count are reported -- a bucket with truly zero
    catalog representation and no known-vocabulary hint has nothing to
    measure a gap *against*, so it is silently absent rather than guessed.

    Returned entries are sorted by ascending count (thinnest first), then by
    dimension and bucket name for determinism.
    """
    findings: list[dict[str, Any]] = []
    for dimension, counts in composition.items():
        vocabulary = (known_vocabulary or {}).get(dimension)
        buckets = set(counts) | (vocabulary or set())
        for bucket in buckets:
            count = counts.get(bucket, 0)
            if count < min_count:
                findings.append({"dimension": dimension, "bucket": bucket, "count": count})
    findings.sort(key=lambda f: (f["count"], f["dimension"], f["bucket"]))
    return findings
