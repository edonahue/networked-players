from __future__ import annotations

from copy import deepcopy
from typing import Any

from networked_players_contracts import connectivity_failures, playable_cohort_failures


def _hop() -> dict[str, Any]:
    return {
        "release_id": 10,
        "artist_a_id": 1,
        "artist_b_id": 2,
        "quality_flags": ["performer_credit"],
    }


def _connectivity() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": {"source_url": "https://example.invalid/source"},
        "scorer_version": 3,
        "generated_at": "2026-07-10T00:00:00+00:00",
        "dataset_snapshot_date": "20260601",
        "max_hops": 3,
        "scoring_params": {"strategy": "synthetic"},
        "pairs": [
            {
                "album_a_id": "release-1",
                "album_b_id": "release-2",
                "artist_a_id": 1,
                "artist_b_id": 2,
                "status": "found",
                "hop_count": 1,
                "difficulty": "easy",
                "hops": [_hop()],
                "warnings": [],
                "skip_reason": None,
            }
        ],
        "unresolved": [],
    }


def _playable() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "cohort_id": "synthetic",
        "attribution_label": "Synthetic source",
        "source_url": "https://example.invalid/source",
        "generated_from_scorer_version": 3,
        "reviewed_at": "2026-07-10T00:00:00+00:00",
        "review_note": None,
        "albums": [
            {"id": "release-1", "artist_id": 1, "artist": "One", "title": "A", "year": 2000},
            {"id": "release-2", "artist_id": 2, "artist": "Two", "title": "B", "year": 2001},
        ],
        "pairs": [
            {
                "album_a_id": "release-1",
                "album_b_id": "release-2",
                "artist_a_id": 1,
                "artist_b_id": 2,
                "difficulty": "easy",
                "hop_count": 1,
                "hops": [_hop()],
                "warnings": [],
            }
        ],
    }


def test_current_connectivity_shape_and_skip_reason_validate() -> None:
    artifact = _connectivity()
    assert connectivity_failures(artifact) == []
    skipped = artifact["pairs"][0]
    skipped.update(
        status="skipped",
        hop_count=None,
        difficulty=None,
        hops=[],
        skip_reason="reach_too_large",
    )
    assert connectivity_failures(artifact) == []


def test_connectivity_reports_structure_and_privacy_failures() -> None:
    artifact = _connectivity()
    artifact["extra"] = "local/analysis/private.json"
    failures = connectivity_failures(artifact)
    assert any("unexpected top-level" in failure for failure in failures)
    assert any("forbidden substring" in failure for failure in failures)


def test_playable_cohort_validates_and_rejects_tone_leaks() -> None:
    artifact = _playable()
    assert playable_cohort_failures(artifact) == []
    broken = deepcopy(artifact)
    broken["review_note"] = "These artists collaborated with each other."
    assert any("forbidden phrase" in failure for failure in playable_cohort_failures(broken))
