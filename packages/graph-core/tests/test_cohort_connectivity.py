"""Tests for cohort connectivity scoring."""

from __future__ import annotations

from pathlib import Path

import pytest

from networked_players_graph_core.cohort_connectivity import (
    CohortConnectivityError,
    build_connectivity_cohort,
    classify_hop_quality,
    score_pairs,
    summarize_connectivity,
    validate_connectivity,
)
from networked_players_graph_core.graph import CreditGraph

SOURCE = {
    "source_url": "https://example.invalid/fake-digs-post",
    "page_title": "Fake Digs Post",
    "saved_at": "2026-07-05",
    "operator_note": "",
}


def _resolved_album(*, artist_id: int, release_id: int, master_id: int | None = None):
    return {
        "rank": 1,
        "artist_query": None,
        "title_query": None,
        "resolution_method": "release_id_hint",
        "master_id": master_id,
        "release_id": release_id,
        "title": "Some Title",
        "artist_id": artist_id,
        "artist_name": "Some Artist",
        "year": None,
        "extraction_confidence": "high",
        "warnings": [],
    }


def _resolved(albums, unresolved=None):
    return {
        "schema_version": 1,
        "source": SOURCE,
        "resolver_version": 1,
        "generated_at": "2026-07-05T00:00:00+00:00",
        "dataset_snapshot_date": "20260601",
        "resolved": albums,
        "unresolved": unresolved or [],
    }


def _row(*, artist_id: int, credit_scope: str, role_text: str | None):
    return {"artist_id": artist_id, "credit_scope": credit_scope, "role_text": role_text}


# --- classify_hop_quality: unit tests, no dataset needed ---


def test_classify_co_billed_release_artists() -> None:
    rows_a = [_row(artist_id=100, credit_scope="release_artist", role_text=None)]
    rows_b = [_row(artist_id=200, credit_scope="release_artist", role_text=None)]
    flags = classify_hop_quality(rows_a, rows_b, artist_a_id=100, artist_b_id=200)
    assert flags == ["co_billed_release_artists"]


def test_classify_performer_credit_when_one_side_is_track_performer() -> None:
    rows_a = [_row(artist_id=100, credit_scope="release_artist", role_text=None)]
    rows_b = [_row(artist_id=200, credit_scope="track_credit", role_text="Guitar")]
    flags = classify_hop_quality(rows_a, rows_b, artist_a_id=100, artist_b_id=200)
    assert flags == ["performer_credit"]


def test_classify_non_performer_only() -> None:
    rows_a = [_row(artist_id=800, credit_scope="release_credit", role_text="Mastered By")]
    rows_b = [_row(artist_id=900, credit_scope="release_credit", role_text="Producer, Engineer")]
    flags = classify_hop_quality(rows_a, rows_b, artist_a_id=800, artist_b_id=900)
    assert flags == ["non_performer_only"]


def test_classify_placeholder_stacks_with_strength_flag() -> None:
    rows_a = [_row(artist_id=1000, credit_scope="release_artist", role_text=None)]
    rows_b = [_row(artist_id=151641, credit_scope="release_artist", role_text=None)]
    flags = classify_hop_quality(rows_a, rows_b, artist_a_id=1000, artist_b_id=151641)
    assert set(flags) == {"co_billed_release_artists", "placeholder_artist_hop"}


# --- score_pairs / build_connectivity_cohort: integration, shared dataset_root fixture ---


def test_one_hop_pair_is_easy(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        pairs = score_pairs(
            graph,
            [
                _resolved_album(artist_id=100, release_id=1),
                _resolved_album(artist_id=200, release_id=1),
            ],
            max_hops=3,
        )
    assert len(pairs) == 1
    pair = pairs[0]
    assert pair["status"] == "found"
    assert pair["hop_count"] == 1
    assert pair["difficulty"] == "easy"
    assert pair["hops"][0]["quality_flags"] == ["co_billed_release_artists"]
    assert pair["warnings"] == []


def test_two_hop_pair_is_medium(dataset_root: Path) -> None:
    # Alice(100) -> Cara(300): 2 hops via Bob (R1 then R2), same pair
    # test_graph.py's test_find_path_two_hop already verifies.
    with CreditGraph.open(dataset_root) as graph:
        pairs = score_pairs(
            graph,
            [
                _resolved_album(artist_id=100, release_id=1),
                _resolved_album(artist_id=300, release_id=2),
            ],
            max_hops=3,
        )
    pair = pairs[0]
    assert pair["status"] == "found"
    assert pair["hop_count"] == 2
    assert pair["difficulty"] == "medium"


def test_no_path_pair_kept_not_dropped(dataset_root: Path) -> None:
    # Same pair as above, but max_hops=1 makes it unreachable -- test_graph.py's
    # test_find_path_none_when_max_hops_too_small already verifies this at the
    # CreditGraph level.
    with CreditGraph.open(dataset_root) as graph:
        pairs = score_pairs(
            graph,
            [
                _resolved_album(artist_id=100, release_id=1),
                _resolved_album(artist_id=300, release_id=2),
            ],
            max_hops=1,
        )
    assert len(pairs) == 1
    pair = pairs[0]
    assert pair["status"] == "no_path"
    assert pair["hop_count"] is None
    assert pair["difficulty"] is None
    assert pair["hops"] == []


def test_placeholder_artist_survives_as_live_hop_endpoint(tmp_path: Path) -> None:
    """Proves the ADR 0029 gap is real: CreditGraph.NON_INDIVIDUAL_ARTIST_IDS only
    excludes 194, so 151641 ("Trad.") can still be a live find_path endpoint."""
    from conftest import write_synthetic_dataset

    def _release(release_id, title, master_id=None, master_is_main_release=None):
        return {
            "snapshot_date": "20260601",
            "release_id": release_id,
            "status": "Accepted",
            "title": title,
            "country": None,
            "released": "2001",
            "master_id": master_id,
            "master_is_main_release": master_is_main_release,
            "data_quality": None,
            "source_url": f"https://example.invalid/release/{release_id}",
        }

    def _credit(release_id, artist_id, name):
        return {
            "snapshot_date": "20260601",
            "release_id": release_id,
            "track_index": None,
            "track_path": None,
            "track_position": None,
            "track_title": None,
            "credit_scope": "release_artist",
            "artist_id": artist_id,
            "name": name,
            "anv": None,
            "join_text": None,
            "role_text": None,
            "credited_tracks_text": None,
            "is_linked": True,
            "playable_identity": True,
        }

    root = write_synthetic_dataset(
        tmp_path / "snapshot=20260601",
        release_rows=[_release(30, "Traditional Session")],
        credit_rows=[_credit(30, 1000, "Zed"), _credit(30, 151641, "Trad.")],
    )
    with CreditGraph.open(root) as graph:
        path = graph.find_path(1000, 151641)
        assert path is not None
        assert len(path.hops) == 1

        pairs = score_pairs(
            graph,
            [
                _resolved_album(artist_id=1000, release_id=30),
                _resolved_album(artist_id=151641, release_id=30),
            ],
        )
    assert set(pairs[0]["hops"][0]["quality_flags"]) == {
        "co_billed_release_artists",
        "placeholder_artist_hop",
    }
    assert any("placeholder" in w for w in pairs[0]["warnings"])


def test_dataset_snapshot_date_mismatch_raises(dataset_root: Path) -> None:
    resolved = _resolved(
        [_resolved_album(artist_id=100, release_id=1), _resolved_album(artist_id=200, release_id=1)]
    )
    resolved["dataset_snapshot_date"] = "20250101"
    with CreditGraph.open(dataset_root) as graph, pytest.raises(CohortConnectivityError):
        build_connectivity_cohort(graph, resolved, dataset_snapshot_date="20260601")


def test_max_pairs_safety_valve_aborts(dataset_root: Path) -> None:
    albums = [
        _resolved_album(artist_id=100, release_id=1),
        _resolved_album(artist_id=200, release_id=1),
        _resolved_album(artist_id=300, release_id=2),
    ]
    resolved = _resolved(albums)  # 3 albums -> 3 pairs
    with (
        CreditGraph.open(dataset_root) as graph,
        pytest.raises(CohortConnectivityError) as exc_info,
    ):
        build_connectivity_cohort(graph, resolved, dataset_snapshot_date="20260601", max_pairs=2)
    assert "3" in str(exc_info.value)


def test_build_connectivity_cohort_round_trips_through_validation(dataset_root: Path) -> None:
    resolved = _resolved(
        [
            _resolved_album(artist_id=100, release_id=1),
            _resolved_album(artist_id=200, release_id=1),
        ],
        unresolved=[{"artist": "Ghost", "title": "Nowhere", "reason": "no match"}],
    )
    with CreditGraph.open(dataset_root) as graph:
        artifact = build_connectivity_cohort(graph, resolved, dataset_snapshot_date="20260601")
    validate_connectivity(artifact)
    assert artifact["source"] == SOURCE
    assert artifact["unresolved"] == resolved["unresolved"]


# --- validate_connectivity rejections ---


def _valid_artifact():
    return {
        "schema_version": 1,
        "source": SOURCE,
        "scorer_version": 1,
        "generated_at": "2026-07-05T00:00:00+00:00",
        "dataset_snapshot_date": "20260601",
        "max_hops": 3,
        "pairs": [
            {
                "album_a_id": "release-1",
                "album_b_id": "release-2",
                "artist_a_id": 100,
                "artist_b_id": 200,
                "status": "found",
                "hop_count": 1,
                "difficulty": "easy",
                "hops": [
                    {
                        "release_id": 1,
                        "artist_a_id": 100,
                        "artist_b_id": 200,
                        "quality_flags": ["co_billed_release_artists"],
                    }
                ],
                "warnings": [],
            }
        ],
        "unresolved": [],
    }


def test_validate_rejects_bad_status() -> None:
    artifact = _valid_artifact()
    artifact["pairs"][0]["status"] = "maybe"
    with pytest.raises(CohortConnectivityError):
        validate_connectivity(artifact)


def test_validate_rejects_bad_difficulty() -> None:
    artifact = _valid_artifact()
    artifact["pairs"][0]["difficulty"] = "impossible"
    with pytest.raises(CohortConnectivityError):
        validate_connectivity(artifact)


def test_validate_rejects_no_path_pair_with_hop_count() -> None:
    artifact = _valid_artifact()
    artifact["pairs"][0]["status"] = "no_path"
    # hop_count/difficulty left non-null -- invalid for no_path.
    with pytest.raises(CohortConnectivityError):
        validate_connectivity(artifact)


def test_validate_rejects_hop_without_strength_flag() -> None:
    artifact = _valid_artifact()
    artifact["pairs"][0]["hops"][0]["quality_flags"] = ["placeholder_artist_hop"]
    with pytest.raises(CohortConnectivityError):
        validate_connectivity(artifact)


def test_validate_rejects_forbidden_substring() -> None:
    artifact = _valid_artifact()
    artifact["source"] = {**SOURCE, "operator_note": "see local/analysis/x"}
    with pytest.raises(CohortConnectivityError):
        validate_connectivity(artifact)


# --- summarize_connectivity: pure Python, no graph dependency ---


def test_summarize_connectivity_filters_and_sorts_playable_pairs() -> None:
    artifact = _valid_artifact()
    artifact["pairs"].append(
        {
            "album_a_id": "release-3",
            "album_b_id": "release-4",
            "artist_a_id": 300,
            "artist_b_id": 400,
            "status": "no_path",
            "hop_count": None,
            "difficulty": None,
            "hops": [],
            "warnings": [],
        }
    )
    playable_pairs, _ = summarize_connectivity(artifact)
    assert len(playable_pairs) == 1
    assert playable_pairs[0]["album_a_id"] == "release-1"


def test_summarize_connectivity_report_sections_and_tone() -> None:
    artifact = _valid_artifact()
    artifact["pairs"][0]["warnings"] = [
        "hop 1 (release 1) connects artist 100 and 200 only via ..."
    ]
    artifact["unresolved"] = [{"artist": "Ghost", "title": "Nowhere", "reason": "no match"}]
    _, report = summarize_connectivity(artifact)
    for heading in (
        "## Header",
        "## Summary counts",
        "## Flagged pairs",
        "## No-path pairs",
        "## Unresolved albums carried forward",
    ):
        assert heading in report
    assert "Ghost" in report
    assert "worked with" not in report.lower()
    assert "collaborated with" not in report.lower()
