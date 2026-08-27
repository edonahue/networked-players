"""Tests for Bucket C's coverage-gap measurement (Phase 7, Workstream 1C)."""

from __future__ import annotations

from networked_players_graph_core.coverage_gaps import (
    catalog_composition,
    identify_underrepresented,
)


def _master(genres: list[str], styles: list[str], year: int) -> dict:
    return {"genres": genres, "styles": styles, "year": year}


def test_catalog_composition_counts_decade_genre_and_style() -> None:
    albums = [
        {"master_id": 1, "year": 1990},
        {"master_id": 2, "year": 1990},
        {"master_id": 3, "year": 1990},
    ]
    masters = {
        1: _master(["Rock"], ["Pop Rock"], 1972),
        2: _master(["Rock", "Funk / Soul"], ["Funk"], 1979),
        3: _master(["Jazz"], ["Bop"], 2001),
    }
    composition = catalog_composition(albums, masters)
    assert composition["decades"] == {"1970s": 2, "2000s": 1}
    assert composition["genres"] == {"Rock": 2, "Funk / Soul": 1, "Jazz": 1}
    assert composition["styles"] == {"Pop Rock": 1, "Funk": 1, "Bop": 1}


def test_a_master_with_two_genres_counts_once_in_each_not_fractionally() -> None:
    albums = [{"master_id": 1, "year": 2000}]
    masters = {1: _master(["Rock", "Electronic"], [], 2000)}
    composition = catalog_composition(albums, masters)
    assert composition["genres"]["Rock"] == 1
    assert composition["genres"]["Electronic"] == 1


def test_album_without_a_master_falls_back_to_its_own_year_for_decade_only() -> None:
    albums = [{"master_id": 99, "year": 1985}]
    composition = catalog_composition(albums, masters_by_id={})
    assert composition["decades"] == {"1980s": 1}
    assert composition["genres"] == {}
    assert composition["styles"] == {}


def test_null_master_year_falls_back_to_the_album_own_year() -> None:
    """The masters parser explicitly nulls out a missing/non-positive year --
    a resolved master with year=None is not a "not found" case, and must not
    dump a real, dateable album into "unknown" when the catalog's own album
    dict already carries a usable year (the same fallback the editorial and
    challenge resolution paths already use)."""
    albums = [{"master_id": 1, "year": 1985}]
    masters = {1: {"genres": ["Rock"], "styles": [], "year": None}}
    composition = catalog_composition(albums, masters)
    assert composition["decades"] == {"1980s": 1}
    # Genre/style still come from the master, independent of the year fallback.
    assert composition["genres"] == {"Rock": 1}


def test_missing_year_and_missing_master_is_unknown_decade_not_dropped() -> None:
    albums = [{"master_id": None, "year": None}]
    composition = catalog_composition(albums, masters_by_id={})
    assert composition["decades"] == {"unknown": 1}


def test_identify_underrepresented_flags_thin_buckets_only() -> None:
    composition = {
        "decades": {"1970s": 54, "1980s": 44, "2000s": 2, "2010s": 1},
        "genres": {"Rock": 104, "Reggae": 0},
        "styles": {},
    }
    findings = identify_underrepresented(composition, min_count=3)
    dims_buckets = {(f["dimension"], f["bucket"]) for f in findings}
    assert ("decades", "2010s") in dims_buckets
    assert ("decades", "2000s") in dims_buckets
    assert ("decades", "1970s") not in dims_buckets
    # A bucket at exactly zero with no observed key at all never appears
    # without a known_vocabulary hint -- "Reggae": 0 wasn't in the dict, so
    # confirm the *shape* rather than a specific missing genre.
    assert all(f["count"] < 3 for f in findings)


def test_identify_underrepresented_surfaces_a_known_vocabulary_zero() -> None:
    """A genre with real Discogs-sourced evidence of existing (from a wider
    snapshot query) but zero representation in this catalog is a genuine,
    measured gap -- not silently invisible just because the catalog's own
    Counter never saw the key."""
    composition = {"decades": {}, "genres": {"Rock": 104}, "styles": {}}
    findings = identify_underrepresented(
        composition,
        known_vocabulary={"genres": frozenset({"Rock", "Reggae"})},
        min_count=3,
    )
    reggae = [f for f in findings if f["bucket"] == "Reggae"]
    assert reggae == [{"dimension": "genres", "bucket": "Reggae", "count": 0}]


def test_identify_underrepresented_is_sorted_thinnest_first_then_deterministic() -> None:
    composition = {"decades": {"2010s": 1, "1950s": 2}, "genres": {}, "styles": {}}
    findings = identify_underrepresented(composition, min_count=3)
    assert [f["bucket"] for f in findings] == ["2010s", "1950s"]
