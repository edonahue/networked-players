"""Tests for extracted-candidates artifact validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from networked_players_catalog.cohort_source.extract import extract_candidates_from_file
from networked_players_catalog.cohort_source.source import build_cohort_source_meta
from networked_players_catalog.cohort_source.validation import (
    CohortSourceValidationError,
    validate_extracted_candidates,
)

FIXTURE = Path(__file__).parents[3] / "data" / "samples" / "cohort-source-sample.html"


def _artifact_dict():
    source = build_cohort_source_meta(
        source_url="https://example.invalid/fake-digs-post",
        page_title="Fake Digs Post",
        saved_at="2026-07-05",
    )
    return extract_candidates_from_file(FIXTURE, source=source).to_dict()


def test_validate_accepts_sample_fixture_output() -> None:
    validate_extracted_candidates(_artifact_dict())


def test_validate_rejects_unknown_top_level_key() -> None:
    artifact = _artifact_dict()
    artifact["extra_field"] = "unexpected"
    with pytest.raises(CohortSourceValidationError):
        validate_extracted_candidates(artifact)


def test_validate_rejects_bad_confidence_value() -> None:
    artifact = _artifact_dict()
    artifact["candidates"][0]["confidence"] = "certain"
    with pytest.raises(CohortSourceValidationError):
        validate_extracted_candidates(artifact)


def test_validate_rejects_forbidden_substring() -> None:
    artifact = _artifact_dict()
    artifact["source"]["operator_note"] = "saved from data/private/source-html/x.html"
    with pytest.raises(CohortSourceValidationError):
        validate_extracted_candidates(artifact)
