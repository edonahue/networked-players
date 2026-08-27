"""Tests for the Phase 7 catalog-expansion review packet assembler --
combines Bucket A/B/C sources, never promotes, never selects."""

from __future__ import annotations

import pytest

from networked_players_catalog.expansion_review import (
    EXPANSION_REVIEW_SCHEMA_VERSION,
    build_expansion_review_packet,
)

SNAPSHOT = "20260601"


def _catalog(master_ids: list[int], *, snapshot_date: str = SNAPSHOT) -> dict:
    return {"snapshot_date": snapshot_date, "albums": [{"master_id": mid} for mid in master_ids]}


def _seed(albums: list[dict], *, snapshot_date: str = SNAPSHOT) -> dict:
    return {"snapshot_date": snapshot_date, "albums": albums}


def _graph_rich(selected: list[dict], *, snapshot_date: str = SNAPSHOT) -> dict:
    return {"snapshot_date": snapshot_date, "selected": selected}


def _coverage_gap(candidates: list[dict], *, snapshot_date: str = SNAPSHOT) -> dict:
    return {"snapshot_date": snapshot_date, "candidates": candidates}


def test_combines_all_three_buckets_with_correct_counts() -> None:
    packet = build_expansion_review_packet(
        generated_at="2026-08-27T00:00:00+00:00",
        current_catalog=_catalog([1, 2, 3]),
        personal_seed=_seed([{"master_id": 10, "artist": "A", "title": "Alpha"}]),
        graph_rich_selection=_graph_rich(
            [
                {
                    "master_id": 20,
                    "artist_name": "B",
                    "sample_title": "Beta",
                    "marginal_new_edges": 5,
                    "marginal_new_contributors": 3,
                }
            ]
        ),
        coverage_gap=_coverage_gap(
            [
                {
                    "master_id": 30,
                    "artist": "C",
                    "title": "Gamma",
                    "gap_dimension": "genres",
                    "gap_bucket": "Reggae",
                    "gap_rationale": "zero catalog representation",
                }
            ]
        ),
    )
    assert packet["schema_version"] == EXPANSION_REVIEW_SCHEMA_VERSION
    assert packet["snapshot_date"] == SNAPSHOT
    assert packet["current_catalog_count"] == 3
    assert packet["proposed_addition_count"] == 3
    assert packet["proposed_total_count"] == 6
    assert packet["bucket_counts"] == {"personal": 1, "graph_rich": 1, "coverage_gap": 1}
    assert packet["warnings"] == []
    buckets = {e["bucket"]: e for e in packet["entries"]}
    assert buckets["personal"]["artist"] == "A"
    assert buckets["graph_rich"]["artist"] == "B"
    assert buckets["graph_rich"]["marginal_new_edges"] == 5
    assert buckets["coverage_gap"]["gap_bucket"] == "Reggae"


def test_flags_an_entry_already_in_the_published_catalog() -> None:
    packet = build_expansion_review_packet(
        generated_at="2026-08-27T00:00:00+00:00",
        current_catalog=_catalog([1, 2, 3]),
        personal_seed=_seed([{"master_id": 2, "artist": "X", "title": "Dup"}]),
        graph_rich_selection=_graph_rich([]),
        coverage_gap=_coverage_gap([]),
    )
    assert packet["entries"][0]["already_in_catalog"] is True
    assert any("already in the published catalog" in w for w in packet["warnings"])


def test_flags_a_master_id_appearing_in_two_buckets() -> None:
    packet = build_expansion_review_packet(
        generated_at="2026-08-27T00:00:00+00:00",
        current_catalog=_catalog([]),
        personal_seed=_seed([{"master_id": 99, "artist": "X", "title": "Dup"}]),
        graph_rich_selection=_graph_rich([{"master_id": 99, "artist_name": "X"}]),
        coverage_gap=_coverage_gap([]),
    )
    assert any("more than one bucket" in w for w in packet["warnings"])
    assert any("personal" in w and "graph_rich" in w for w in packet["warnings"])


def test_empty_buckets_produce_a_valid_empty_packet() -> None:
    packet = build_expansion_review_packet(
        generated_at="2026-08-27T00:00:00+00:00",
        current_catalog=_catalog([1]),
        personal_seed=_seed([]),
        graph_rich_selection=_graph_rich([]),
        coverage_gap=_coverage_gap([]),
    )
    assert packet["entries"] == []
    assert packet["proposed_addition_count"] == 0
    assert packet["proposed_total_count"] == 1
    assert packet["warnings"] == []


def test_an_album_without_a_master_id_is_never_flagged_as_already_in_catalog() -> None:
    packet = build_expansion_review_packet(
        generated_at="2026-08-27T00:00:00+00:00",
        current_catalog=_catalog([1]),
        personal_seed=_seed([{"master_id": None, "artist": "X", "title": "No Master"}]),
        graph_rich_selection=_graph_rich([]),
        coverage_gap=_coverage_gap([]),
    )
    assert packet["entries"][0]["already_in_catalog"] is False
    assert packet["warnings"] == []


def test_a_mismatched_snapshot_date_is_refused() -> None:
    with pytest.raises(ValueError, match="mismatched snapshot_date"):
        build_expansion_review_packet(
            generated_at="2026-08-27T00:00:00+00:00",
            current_catalog=_catalog([1]),
            personal_seed=_seed([], snapshot_date="20200101"),
            graph_rich_selection=_graph_rich([]),
            coverage_gap=_coverage_gap([]),
        )


def test_a_missing_snapshot_date_is_refused() -> None:
    with pytest.raises(ValueError, match="missing snapshot_date"):
        build_expansion_review_packet(
            generated_at="2026-08-27T00:00:00+00:00",
            current_catalog=_catalog([1]),
            personal_seed={"albums": []},  # no snapshot_date at all
            graph_rich_selection=_graph_rich([]),
            coverage_gap=_coverage_gap([]),
        )


def test_a_mismatched_coverage_gap_snapshot_date_is_refused() -> None:
    """The fourth input (Bucket C) is cross-checked too, not just the first
    three -- a stale coverage-gap candidate list must not silently combine
    with a newer catalog/selection generation."""
    with pytest.raises(ValueError, match="mismatched snapshot_date"):
        build_expansion_review_packet(
            generated_at="2026-08-27T00:00:00+00:00",
            current_catalog=_catalog([1]),
            personal_seed=_seed([]),
            graph_rich_selection=_graph_rich([]),
            coverage_gap=_coverage_gap([], snapshot_date="20200101"),
        )


def test_all_four_inputs_agreeing_records_the_agreed_snapshot() -> None:
    packet = build_expansion_review_packet(
        generated_at="2026-08-27T00:00:00+00:00",
        current_catalog=_catalog([1], snapshot_date="20260701"),
        personal_seed=_seed([], snapshot_date="20260701"),
        graph_rich_selection=_graph_rich([], snapshot_date="20260701"),
        coverage_gap=_coverage_gap([], snapshot_date="20260701"),
    )
    assert packet["snapshot_date"] == "20260701"
