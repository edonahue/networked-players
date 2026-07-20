"""Master-level studio-album eligibility, used by catalog assembly.

Release format descriptors alone cannot separate a genuine studio album from a
soundtrack or a stage/screen recording. Confirmed against snapshot 20260601:
Discogs' own contributors tag *zero* pressings of many soundtracks and live
albums with a ``Soundtrack``/``Live`` format descriptor, so a release-level
format policy (``catalog/discogs/release_format_policy.py``) lets them through.
The master's editorial genre/style, however, *does* cleanly mark soundtracks and
stage recordings -- e.g. master 124110 "West Side Story" carries
``genres=['Stage & Screen']``, ``styles=['Soundtrack','Musical']``. This module
is the fail-closed master-level gate that release descriptors are not.

Live albums that carry no genre/style signal at all (e.g. master 14495 "The Last
Waltz": ``styles=['Folk Rock','Country Rock','Blues Rock']``) remain a
human-curation backstop -- see ``data/albums/studio-album-master-exclusions-v1.json``
(ADR 0035's "human curation is the backstop for un-separable cases"; ADR 0036's
interim curation filter).

Lives in graph-core (not catalog's ``release_format_policy``) because catalog
depends on graph-core, and this gate runs *inside* catalog assembly
(``analysis.py``/``challenge.py``), which is graph-core. ``master_non_studio_reason``
(Python) and ``master_non_studio_sql`` (its DuckDB mirror) are kept in step by
``test_album_policy``'s parity test, the same pattern as ``eligibility.py``.
"""

from __future__ import annotations

# Lowercased, whitespace-collapsed. Deliberately narrow: only genres/styles that
# are unambiguously non-studio-band recordings. Widen only after reviewing real
# masters a candidate run would newly exclude (never relax the fail-closed posture).
_NON_STUDIO_GENRES = frozenset({"stage & screen"})
_NON_STUDIO_STYLES = frozenset({"soundtrack", "musical", "score"})


def _norm(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def master_non_studio_reason(genres: list[str] | None, styles: list[str] | None) -> str | None:
    """Return a fail-closed exclusion reason when a master's Discogs genre/style
    marks it non-studio (soundtrack, stage & screen, score, musical), else None.
    """
    hit_genres = sorted({_norm(g) for g in (genres or [])} & _NON_STUDIO_GENRES)
    hit_styles = sorted({_norm(s) for s in (styles or [])} & _NON_STUDIO_STYLES)
    if hit_genres or hit_styles:
        return "non_studio_master_genre_style: " + ", ".join(hit_genres + hit_styles)
    return None


def master_non_studio_sql(genres_col: str, styles_col: str) -> str:
    """DuckDB boolean mirror of ``master_non_studio_reason`` -- true when the
    master is non-studio. NULL genre/style lists read as an empty list (not
    non-studio). Kept in step with the Python form by ``test_album_policy``."""
    genres = ", ".join(f"'{g}'" for g in sorted(_NON_STUDIO_GENRES))
    styles = ", ".join(f"'{s}'" for s in sorted(_NON_STUDIO_STYLES))
    return f"""(
        len(list_intersect(
            list_transform(coalesce({genres_col}, []), x -> lower(trim(x))), [{genres}]
        )) > 0
        OR len(list_intersect(
            list_transform(coalesce({styles_col}, []), x -> lower(trim(x))), [{styles}]
        )) > 0
    )"""
