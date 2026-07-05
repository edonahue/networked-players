"""Tests for cohort-source HTML extraction."""

from __future__ import annotations

from pathlib import Path

import pytest

from networked_players_catalog.cohort_source.extract import (
    WARN_NO_LINK,
    WARN_NO_SEPARATOR,
    WARN_NO_YEAR,
    CohortSourceExtractionError,
    extract_candidates_from_file,
    extract_candidates_from_html,
)
from networked_players_catalog.cohort_source.source import build_cohort_source_meta

FIXTURE = Path(__file__).parents[3] / "data" / "samples" / "cohort-source-sample.html"


def _source():
    return build_cohort_source_meta(
        source_url="https://example.invalid/fake-digs-post",
        page_title="Fake Digs Post",
        saved_at="2026-07-05",
    )


def test_extract_happy_path_from_sample_fixture() -> None:
    artifact = extract_candidates_from_file(FIXTURE, source=_source())

    assert artifact.notes == []
    assert len(artifact.candidates) == 4

    entry1 = artifact.candidates[0]
    assert entry1.rank == 1
    assert entry1.artist == "Fake Artist One"
    assert entry1.title == "First Light"
    assert entry1.year == 1971
    assert entry1.master_id == 999901
    assert entry1.release_id is None
    assert entry1.confidence == "high"
    assert entry1.warnings == []

    entry2 = artifact.candidates[1]
    assert entry2.rank == 2
    assert entry2.artist == "Fake Artist Two"
    assert entry2.title == "Second Wave"
    assert entry2.year == 1988
    assert entry2.master_id is None
    assert entry2.release_id == 8888802

    entry3 = artifact.candidates[2]
    assert entry3.rank == 3
    assert entry3.artist == "Fake Artist Three"
    assert entry3.title == "Untitled Session"
    assert entry3.year is None
    assert entry3.master_id is None
    assert entry3.release_id is None
    assert WARN_NO_YEAR in entry3.warnings
    assert WARN_NO_LINK in entry3.warnings

    entry4 = artifact.candidates[3]
    assert entry4.rank == 4
    assert entry4.artist is None
    assert WARN_NO_SEPARATOR in entry4.warnings
    assert entry4.confidence == "low"


def test_extract_missing_link_sets_null_not_guess() -> None:
    html = "<ol><li>1. Some Artist – Some Title (2001)</li>" * 3 + "</ol>"  # noqa: RUF001
    artifact = extract_candidates_from_html(html, source=_source())
    for candidate in artifact.candidates:
        assert candidate.master_id is None
        assert candidate.release_id is None
        assert WARN_NO_LINK in candidate.warnings


def test_extract_empty_html_raises() -> None:
    with pytest.raises(CohortSourceExtractionError) as exc_info:
        extract_candidates_from_html("", source=_source())
    assert "/" not in str(exc_info.value)


def test_extract_no_candidates_found_returns_empty_with_note() -> None:
    artifact = extract_candidates_from_html(
        "<p>Just a paragraph, not a list.</p>", source=_source()
    )
    assert artifact.candidates == []
    assert "no candidate entries detected" in artifact.notes


def test_extract_ambiguous_year_kept_with_warning() -> None:
    html = "<ol><li>1. Some Artist – Some Title</li>" * 3 + "</ol>"  # noqa: RUF001
    artifact = extract_candidates_from_html(html, source=_source())
    for candidate in artifact.candidates:
        assert candidate.year is None
        assert WARN_NO_YEAR in candidate.warnings
