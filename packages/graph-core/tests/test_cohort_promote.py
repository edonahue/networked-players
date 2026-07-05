"""Tests for human-reviewed playable-cohort promotion. Synthetic fixtures only --
a real, Discogs-derived promoted cohort is committed only with explicit human
review and go-ahead, never as a byproduct of these tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from networked_players_graph_core.cohort_promote import (
    CohortPromoteError,
    draft_selection_template,
    promote_playable_cohort,
    validate_playable_cohort,
    validate_selection_file,
    write_playable_cohort,
)

SOURCE = {
    "source_url": "https://example.invalid/fake-digs-post",
    "page_title": "Fake Digs Post",
    "saved_at": "2026-07-05",
    "operator_note": "",
}


def _resolved_album(
    *,
    artist_id: int,
    release_id: int,
    master_id: int | None = None,
    title: str = "Some Title",
    artist_name: str = "Some Artist",
    year: int | None = None,
) -> dict[str, Any]:
    return {
        "rank": 1,
        "artist_query": None,
        "title_query": None,
        "resolution_method": "release_id_hint",
        "master_id": master_id,
        "release_id": release_id,
        "title": title,
        "artist_id": artist_id,
        "artist_name": artist_name,
        "year": year,
        "extraction_confidence": "high",
        "warnings": [],
    }


def _resolved(albums: list[dict[str, Any]], *, snapshot_date: str = "20260601") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": SOURCE,
        "resolver_version": 1,
        "generated_at": "2026-07-05T00:00:00+00:00",
        "dataset_snapshot_date": snapshot_date,
        "resolved": albums,
        "unresolved": [],
    }


def _hop(
    *, release_id: int, artist_a_id: int, artist_b_id: int, flags: list[str]
) -> dict[str, Any]:
    return {
        "release_id": release_id,
        "artist_a_id": artist_a_id,
        "artist_b_id": artist_b_id,
        "quality_flags": flags,
    }


def _pair(
    *,
    album_a_id: str,
    album_b_id: str,
    artist_a_id: int,
    artist_b_id: int,
    status: str = "found",
    hop_count: int | None = 1,
    difficulty: str | None = "easy",
    hops: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
    skip_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "album_a_id": album_a_id,
        "album_b_id": album_b_id,
        "artist_a_id": artist_a_id,
        "artist_b_id": artist_b_id,
        "status": status,
        "hop_count": hop_count,
        "difficulty": difficulty,
        "hops": hops
        if hops is not None
        else [
            _hop(
                release_id=1,
                artist_a_id=artist_a_id,
                artist_b_id=artist_b_id,
                flags=["co_billed_release_artists"],
            )
        ],
        "warnings": warnings or [],
        "skip_reason": skip_reason,
    }


def _connectivity(
    pairs: list[dict[str, Any]],
    *,
    snapshot_date: str = "20260601",
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": source if source is not None else SOURCE,
        "scorer_version": 2,
        "generated_at": "2026-07-05T00:00:00+00:00",
        "dataset_snapshot_date": snapshot_date,
        "max_hops": 3,
        "pairs": pairs,
        "unresolved": [],
    }


def _selection(
    approved_pairs: list[dict[str, Any]],
    *,
    allow_flagged_pairs: bool = False,
    review_note: str | None = None,
) -> dict[str, Any]:
    selection: dict[str, Any] = {
        "schema_version": 1,
        "reviewed_by": "Erich",
        "reviewed_at": "2026-07-05T12:00:00+00:00",
        "allow_flagged_pairs": allow_flagged_pairs,
        "approved_pairs": approved_pairs,
    }
    if review_note is not None:
        selection["review_note"] = review_note
    return selection


ALICE = _resolved_album(
    artist_id=100, release_id=1, title="First Light", artist_name="Alice", year=1993
)
CARA = _resolved_album(
    artist_id=300, release_id=2, title="Third Wave", artist_name="Cara", year=1995
)


def _clean_pair() -> dict[str, Any]:
    return _pair(
        album_a_id="release-1",
        album_b_id="release-2",
        artist_a_id=100,
        artist_b_id=300,
        hop_count=2,
        difficulty="medium",
        hops=[
            _hop(
                release_id=1, artist_a_id=100, artist_b_id=200, flags=["co_billed_release_artists"]
            ),
            _hop(
                release_id=2, artist_a_id=200, artist_b_id=300, flags=["co_billed_release_artists"]
            ),
        ],
    )


# --- validate_selection_file ---


def test_validate_selection_file_accepts_well_formed_file() -> None:
    validate_selection_file(_selection([{"album_a_id": "release-1", "album_b_id": "release-2"}]))


def test_validate_selection_file_accepts_empty_approved_pairs() -> None:
    """An operator reviewing a cohort and approving nothing is a legitimate
    outcome -- rejected later, with a specific message, by
    promote_playable_cohort's own "no pairs promoted" guard, not here."""
    validate_selection_file(_selection([]))


def test_validate_selection_file_rejects_bad_schema_version() -> None:
    selection = _selection([{"album_a_id": "release-1", "album_b_id": "release-2"}])
    selection["schema_version"] = 2
    with pytest.raises(CohortPromoteError):
        validate_selection_file(selection)


def test_validate_selection_file_rejects_non_bool_allow_flagged_pairs() -> None:
    selection = _selection([{"album_a_id": "release-1", "album_b_id": "release-2"}])
    selection["allow_flagged_pairs"] = "yes"
    with pytest.raises(CohortPromoteError):
        validate_selection_file(selection)


def test_validate_selection_file_rejects_malformed_pair_entry() -> None:
    with pytest.raises(CohortPromoteError):
        validate_selection_file(_selection([{"album_a_id": "release-1"}]))


# --- draft_selection_template ---


def test_draft_excludes_no_path_and_skipped_pairs() -> None:
    no_path = _pair(
        album_a_id="release-1",
        album_b_id="release-2",
        artist_a_id=100,
        artist_b_id=300,
        status="no_path",
        hop_count=None,
        difficulty=None,
        hops=[],
    )
    skipped = _pair(
        album_a_id="release-2",
        album_b_id="release-3",
        artist_a_id=300,
        artist_b_id=400,
        status="skipped",
        hop_count=None,
        difficulty=None,
        hops=[],
    )
    skipped["skip_reason"] = "frontier_too_large"
    connectivity = _connectivity([no_path, skipped, _clean_pair()])

    template = draft_selection_template(connectivity)
    assert len(template["candidate_pairs"]) == 1
    assert template["candidate_pairs"][0]["album_a_id"] == "release-1"


def test_draft_never_pre_approves() -> None:
    connectivity = _connectivity([_clean_pair()])
    template = draft_selection_template(connectivity)
    assert template["approved_pairs"] == []
    assert template["schema_version"] == 1
    assert template["allow_flagged_pairs"] is False


def test_draft_sorts_clean_before_flagged_then_by_difficulty_and_hops() -> None:
    hard_clean = _pair(
        album_a_id="release-5",
        album_b_id="release-6",
        artist_a_id=500,
        artist_b_id=600,
        difficulty="hard",
        hop_count=3,
    )
    easy_flagged = _pair(
        album_a_id="release-1",
        album_b_id="release-2",
        artist_a_id=100,
        artist_b_id=300,
        difficulty="easy",
        hop_count=1,
        warnings=["hop 1 flagged"],
    )
    easy_clean = _pair(
        album_a_id="release-3",
        album_b_id="release-4",
        artist_a_id=400,
        artist_b_id=500,
        difficulty="easy",
        hop_count=1,
    )
    connectivity = _connectivity([hard_clean, easy_flagged, easy_clean])

    template = draft_selection_template(connectivity)
    ordered_ids = [(c["album_a_id"], c["album_b_id"]) for c in template["candidate_pairs"]]
    # Clean pairs (regardless of difficulty) sort before any flagged pair.
    assert ordered_ids == [
        ("release-3", "release-4"),  # easy, clean
        ("release-5", "release-6"),  # hard, clean
        ("release-1", "release-2"),  # easy, flagged -- last despite being easy
    ]


def test_hand_edited_draft_promotes_successfully_through_unmodified_functions() -> None:
    """Proves draft_selection_template needs zero changes to
    promote_playable_cohort/validate_selection_file -- an operator moving one
    candidate into approved_pairs is all that's required."""
    resolved = _resolved([ALICE, CARA])
    connectivity = _connectivity([_clean_pair()])
    template = draft_selection_template(connectivity)

    assert len(template["candidate_pairs"]) == 1
    candidate = template["candidate_pairs"][0]
    template["approved_pairs"].append(
        {"album_a_id": candidate["album_a_id"], "album_b_id": candidate["album_b_id"]}
    )
    template["reviewed_by"] = "Erich"
    template["reviewed_at"] = "2026-07-05T12:00:00+00:00"

    artifact = promote_playable_cohort(resolved, connectivity, template, cohort_id="test-cohort")
    assert len(artifact["pairs"]) == 1


def test_unedited_draft_raises_no_pairs_promoted() -> None:
    resolved = _resolved([ALICE, CARA])
    connectivity = _connectivity([_clean_pair()])
    template = draft_selection_template(connectivity)

    with pytest.raises(CohortPromoteError, match="no pairs were promoted"):
        promote_playable_cohort(resolved, connectivity, template, cohort_id="test-cohort")


# --- promote_playable_cohort: core rules ---


def test_clean_pair_promotes_successfully() -> None:
    resolved = _resolved([ALICE, CARA])
    connectivity = _connectivity([_clean_pair()])
    selection = _selection([{"album_a_id": "release-1", "album_b_id": "release-2"}])

    artifact = promote_playable_cohort(resolved, connectivity, selection, cohort_id="test-cohort")

    assert artifact["cohort_id"] == "test-cohort"
    assert artifact["attribution_label"] == "Fake Digs Post"
    assert artifact["source_url"] == SOURCE["source_url"]
    assert artifact["generated_from_scorer_version"] == 2
    assert artifact["reviewed_at"] == "2026-07-05T12:00:00+00:00"
    assert len(artifact["albums"]) == 2
    assert {a["id"] for a in artifact["albums"]} == {"release-1", "release-2"}
    assert len(artifact["pairs"]) == 1
    assert artifact["pairs"][0]["hop_count"] == 2
    assert "status" not in artifact["pairs"][0]
    assert "skip_reason" not in artifact["pairs"][0]
    validate_playable_cohort(artifact)  # round-trips cleanly


def test_no_path_pair_rejected() -> None:
    resolved = _resolved([ALICE, CARA])
    pair = _pair(
        album_a_id="release-1",
        album_b_id="release-2",
        artist_a_id=100,
        artist_b_id=300,
        status="no_path",
        hop_count=None,
        difficulty=None,
        hops=[],
    )
    connectivity = _connectivity([pair])
    selection = _selection([{"album_a_id": "release-1", "album_b_id": "release-2"}])

    with pytest.raises(CohortPromoteError, match="not 'found'"):
        promote_playable_cohort(resolved, connectivity, selection, cohort_id="test-cohort")


def test_skipped_pair_rejected() -> None:
    resolved = _resolved([ALICE, CARA])
    pair = _pair(
        album_a_id="release-1",
        album_b_id="release-2",
        artist_a_id=100,
        artist_b_id=300,
        status="skipped",
        hop_count=None,
        difficulty=None,
        hops=[],
    )
    pair["skip_reason"] = "frontier_too_large"
    connectivity = _connectivity([pair])
    selection = _selection([{"album_a_id": "release-1", "album_b_id": "release-2"}])

    with pytest.raises(CohortPromoteError, match="not 'found'"):
        promote_playable_cohort(resolved, connectivity, selection, cohort_id="test-cohort")


def test_flagged_pair_rejected_without_override() -> None:
    resolved = _resolved([ALICE, CARA])
    pair = _clean_pair()
    pair["warnings"] = ["hop 1 (release 1) connects artist 100 and 200 only via ..."]
    connectivity = _connectivity([pair])
    selection = _selection([{"album_a_id": "release-1", "album_b_id": "release-2"}])

    with pytest.raises(CohortPromoteError, match="allow_flagged_pairs"):
        promote_playable_cohort(resolved, connectivity, selection, cohort_id="test-cohort")


def test_flagged_pair_allowed_with_cohort_wide_override() -> None:
    resolved = _resolved([ALICE, CARA])
    pair = _clean_pair()
    pair["warnings"] = ["hop 1 (release 1) connects artist 100 and 200 only via ..."]
    connectivity = _connectivity([pair])
    selection = _selection(
        [{"album_a_id": "release-1", "album_b_id": "release-2"}], allow_flagged_pairs=True
    )

    artifact = promote_playable_cohort(resolved, connectivity, selection, cohort_id="test-cohort")
    assert artifact["pairs"][0]["warnings"] == pair["warnings"]


def test_flagged_pair_allowed_with_per_pair_override() -> None:
    resolved = _resolved([ALICE, CARA])
    pair = _clean_pair()
    pair["warnings"] = ["hop 1 (release 1) connects artist 100 and 200 only via ..."]
    connectivity = _connectivity([pair])
    selection = _selection(
        [{"album_a_id": "release-1", "album_b_id": "release-2", "allow_flagged_pairs": True}],
        allow_flagged_pairs=False,
    )

    artifact = promote_playable_cohort(resolved, connectivity, selection, cohort_id="test-cohort")
    assert artifact["pairs"][0]["warnings"] == pair["warnings"]


def test_approved_pair_absent_from_connectivity_raises() -> None:
    resolved = _resolved([ALICE, CARA])
    connectivity = _connectivity([_clean_pair()])
    selection = _selection([{"album_a_id": "release-1", "album_b_id": "release-999"}])

    with pytest.raises(CohortPromoteError, match="typo"):
        promote_playable_cohort(resolved, connectivity, selection, cohort_id="test-cohort")


def test_zero_approved_pairs_raises() -> None:
    resolved = _resolved([ALICE, CARA])
    connectivity = _connectivity([_clean_pair()])
    selection = _selection([])

    with pytest.raises(CohortPromoteError, match="empty playable cohort"):
        promote_playable_cohort(resolved, connectivity, selection, cohort_id="test-cohort")


def test_dataset_snapshot_date_mismatch_raises() -> None:
    resolved = _resolved([ALICE, CARA], snapshot_date="20250101")
    connectivity = _connectivity([_clean_pair()], snapshot_date="20260601")
    selection = _selection([{"album_a_id": "release-1", "album_b_id": "release-2"}])

    with pytest.raises(CohortPromoteError, match="dataset_snapshot_date"):
        promote_playable_cohort(resolved, connectivity, selection, cohort_id="test-cohort")


def test_source_url_mismatch_raises() -> None:
    resolved = _resolved([ALICE, CARA])
    other_source = {**SOURCE, "source_url": "https://example.invalid/a-different-post"}
    connectivity = _connectivity([_clean_pair()], source=other_source)
    selection = _selection([{"album_a_id": "release-1", "album_b_id": "release-2"}])

    with pytest.raises(CohortPromoteError, match="source_url"):
        promote_playable_cohort(resolved, connectivity, selection, cohort_id="test-cohort")


def test_selection_pair_order_is_normalized() -> None:
    """A human typing the selection file shouldn't need to know the internal
    a/b sort convention connectivity.json uses."""
    resolved = _resolved([ALICE, CARA])
    connectivity = _connectivity([_clean_pair()])
    selection = _selection([{"album_a_id": "release-2", "album_b_id": "release-1"}])

    artifact = promote_playable_cohort(resolved, connectivity, selection, cohort_id="test-cohort")
    assert len(artifact["pairs"]) == 1
    # Output preserves connectivity.json's own canonical a/b order, not the
    # selection file's.
    assert artifact["pairs"][0]["album_a_id"] == "release-1"
    assert artifact["pairs"][0]["album_b_id"] == "release-2"


def test_review_note_carried_forward_reviewed_by_is_not() -> None:
    resolved = _resolved([ALICE, CARA])
    connectivity = _connectivity([_clean_pair()])
    selection = _selection(
        [{"album_a_id": "release-1", "album_b_id": "release-2"}],
        review_note="A clean, well-documented connection.",
    )

    artifact = promote_playable_cohort(resolved, connectivity, selection, cohort_id="test-cohort")
    assert artifact["review_note"] == "A clean, well-documented connection."
    assert "reviewed_by" not in artifact
    assert "Erich" not in json.dumps(artifact)


# --- validate_playable_cohort: leak/tone regressions ---


def _valid_playable_artifact() -> dict[str, Any]:
    resolved = _resolved([ALICE, CARA])
    connectivity = _connectivity([_clean_pair()])
    selection = _selection([{"album_a_id": "release-1", "album_b_id": "release-2"}])
    return promote_playable_cohort(resolved, connectivity, selection, cohort_id="test-cohort")


def test_validate_rejects_forbidden_substring() -> None:
    artifact = _valid_playable_artifact()
    artifact["review_note"] = "see local/analysis/x for details"
    with pytest.raises(CohortPromoteError):
        validate_playable_cohort(artifact)


@pytest.mark.parametrize("phrase", ["worked with", "collaborated with", "influenced"])
def test_validate_rejects_forbidden_tone_phrases(phrase: str) -> None:
    artifact = _valid_playable_artifact()
    artifact["review_note"] = f"These two artists {phrase} each other."
    with pytest.raises(CohortPromoteError):
        validate_playable_cohort(artifact)


def test_validate_rejects_unexpected_top_level_keys() -> None:
    artifact = _valid_playable_artifact()
    artifact["extra_field"] = "nope"
    with pytest.raises(CohortPromoteError):
        validate_playable_cohort(artifact)


def test_validate_rejects_pair_referencing_unpublished_album() -> None:
    artifact = _valid_playable_artifact()
    artifact["pairs"][0]["album_b_id"] = "release-999"
    with pytest.raises(CohortPromoteError):
        validate_playable_cohort(artifact)


def test_validate_rejects_hop_without_strength_flag() -> None:
    artifact = _valid_playable_artifact()
    artifact["pairs"][0]["hops"][0]["quality_flags"] = ["placeholder_artist_hop"]
    with pytest.raises(CohortPromoteError):
        validate_playable_cohort(artifact)


def test_write_playable_cohort_round_trips(tmp_path: Path) -> None:
    artifact = _valid_playable_artifact()
    output = tmp_path / "cohort-playable-v1.json"
    write_playable_cohort(artifact, output)
    assert json.loads(output.read_text()) == artifact
