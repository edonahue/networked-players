"""Tests for cohort-candidate resolution against a real dataset."""

from __future__ import annotations

from pathlib import Path

import pytest

from networked_players_graph_core.cohort_resolve import (
    CohortResolveError,
    build_resolved_cohort,
    resolve_candidates,
    validate_resolved_cohort,
)
from networked_players_graph_core.graph import CreditGraph

SOURCE = {
    "source_url": "https://example.invalid/fake-digs-post",
    "page_title": "Fake Digs Post",
    "saved_at": "2026-07-05",
    "operator_note": "",
}


def _extracted(candidates: list[dict]) -> dict:
    return {
        "schema_version": 1,
        "source": SOURCE,
        "extractor_version": 1,
        "generated_at": "2026-07-05T00:00:00+00:00",
        "notes": [],
        "candidates": candidates,
    }


def _candidate(**overrides):
    base = {
        "rank": 1,
        "artist": None,
        "title": None,
        "year": None,
        "master_id": None,
        "release_id": None,
        "confidence": "low",
        "warnings": [],
    }
    base.update(overrides)
    return base


def test_resolve_by_release_id_hint(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        resolved, unresolved = resolve_candidates(
            graph, [_candidate(rank=1, artist="Alice", title="First Light", release_id=1)]
        )
    assert unresolved == []
    assert len(resolved) == 1
    assert resolved[0].resolution_method == "release_id_hint"
    assert resolved[0].artist_id == 100
    assert resolved[0].master_id == 901


def test_resolve_flags_id_hint_text_mismatch_without_rejecting_it(dataset_root: Path) -> None:
    # release_id=1 is real (Alice, "First Light") but the extracted text here
    # is unrelated -- an ID hint is still trusted, but the mismatch must be
    # surfaced for human review, not silently accepted or silently corrected.
    with CreditGraph.open(dataset_root) as graph:
        candidate = _candidate(
            rank=1, artist="Totally Different Artist", title="Wrong Title", release_id=1
        )
        resolved, unresolved = resolve_candidates(graph, [candidate])
    assert unresolved == []
    assert resolved[0].artist_id == 100
    assert "resolved title does not match extracted title_query" in resolved[0].warnings
    assert "resolved artist does not match extracted artist_query" in resolved[0].warnings


def test_resolve_by_master_id_hint(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        resolved, unresolved = resolve_candidates(
            graph, [_candidate(rank=1, artist="Alice", title="First Light", master_id=901)]
        )
    assert unresolved == []
    assert resolved[0].resolution_method == "master_id_hint"
    assert resolved[0].release_id == 1


def test_resolve_falls_back_to_title_artist_match(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        resolved, unresolved = resolve_candidates(
            graph, [_candidate(rank=1, artist="Cara", title="Third Wave")]
        )
    assert unresolved == []
    assert resolved[0].resolution_method == "title_artist_match"
    assert resolved[0].artist_id == 300


def test_resolve_reports_unknown_id_hint_as_unresolved(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        resolved, unresolved = resolve_candidates(
            graph, [_candidate(rank=1, master_id=999_999, artist=None, title=None)]
        )
    assert resolved == []
    assert len(unresolved) == 1
    assert "reason" in unresolved[0]


def test_resolve_reports_missing_text_and_no_hint_as_unresolved(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        resolved, unresolved = resolve_candidates(graph, [_candidate(rank=1)])
    assert resolved == []
    assert len(unresolved) == 1
    assert "no id hint" in unresolved[0]["reason"] or "no hint" in unresolved[0]["reason"]


def test_resolve_deduplicates_by_artist_id(dataset_root: Path) -> None:
    # Both candidates resolve to Alice (100): once via release 1, once via
    # release 4 (Mega Compilation) -- the second must be reported unresolved.
    with CreditGraph.open(dataset_root) as graph:
        resolved, unresolved = resolve_candidates(
            graph,
            [
                _candidate(rank=1, release_id=1),
                _candidate(rank=2, release_id=4),
            ],
        )
    assert len(resolved) == 1
    assert len(unresolved) == 1
    assert "already resolved" in unresolved[0]["reason"]


def test_resolve_candidates_concurrent_matches_sequential(dataset_root: Path) -> None:
    """max_workers > 1 must produce byte-for-byte the same (resolved,
    unresolved) as the sequential path -- including the order-dependent
    used_artist_ids dedup (release_id=4 duplicates Alice from release_id=1),
    a missing-hint case, and a title/artist fallback, so the merge pass
    genuinely exercises every branch, not just the happy path."""
    candidates = [
        _candidate(rank=1, release_id=1),
        _candidate(rank=2, release_id=4),  # dedup: same artist as rank 1
        _candidate(rank=3, artist="Cara", title="Third Wave"),
        _candidate(rank=4),  # no hint, no text -> unresolved
        _candidate(rank=5, master_id=999_999),  # unknown hint -> unresolved
    ]
    with CreditGraph.open(dataset_root) as graph:
        sequential = resolve_candidates(graph, candidates)
        concurrent = resolve_candidates(graph, candidates, max_workers=4)

    assert concurrent == sequential


def test_build_resolved_cohort_round_trips_through_validation(dataset_root: Path) -> None:
    extracted = _extracted(
        [
            _candidate(rank=1, artist="Alice", title="First Light", release_id=1),
            _candidate(rank=2, master_id=999_999),
        ]
    )
    with CreditGraph.open(dataset_root) as graph:
        artifact = build_resolved_cohort(graph, extracted, dataset_snapshot_date="20260601")

    validate_resolved_cohort(artifact)
    assert artifact["source"] == SOURCE
    assert artifact["dataset_snapshot_date"] == "20260601"
    assert len(artifact["resolved"]) == 1
    assert len(artifact["unresolved"]) == 1


def test_validate_rejects_duplicate_artist_id() -> None:
    artifact = {
        "schema_version": 1,
        "source": SOURCE,
        "resolver_version": 1,
        "generated_at": "2026-07-05T00:00:00+00:00",
        "dataset_snapshot_date": "20260601",
        "resolved": [
            {
                "rank": 1,
                "artist_query": "Alice",
                "title_query": "First Light",
                "resolution_method": "release_id_hint",
                "master_id": 901,
                "release_id": 1,
                "title": "First Light",
                "artist_id": 100,
                "artist_name": "Alice",
                "year": 1993,
                "extraction_confidence": "high",
                "warnings": [],
            },
            {
                "rank": 2,
                "artist_query": "Alice",
                "title_query": "First Light Again",
                "resolution_method": "title_artist_match",
                "master_id": None,
                "release_id": 5,
                "title": "First Light Again",
                "artist_id": 100,
                "artist_name": "Alice",
                "year": None,
                "extraction_confidence": "high",
                "warnings": [],
            },
        ],
        "unresolved": [],
    }
    with pytest.raises(CohortResolveError):
        validate_resolved_cohort(artifact)


def test_validate_rejects_forbidden_substring() -> None:
    artifact = {
        "schema_version": 1,
        "source": {**SOURCE, "operator_note": "saved to local/analysis/x"},
        "resolver_version": 1,
        "generated_at": "2026-07-05T00:00:00+00:00",
        "dataset_snapshot_date": "20260601",
        "resolved": [],
        "unresolved": [],
    }
    with pytest.raises(CohortResolveError):
        validate_resolved_cohort(artifact)
