"""Unit tests for the automatic-lane policy gates (graph-expansion Phase 2,
plan section 21.3 slice X3) -- the committed roster band and overlap minimum
that `select-graph-rich-candidates` previously never read."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from networked_players_graph_core.expansion_policy import (
    ExpansionPolicyError,
    automatic_lane_rejection,
    filter_to_automatic_lane,
    load_automatic_lane_policy,
)

POLICY = {"roster_band": {"min": 5, "max": 30}, "overlap_existing_minimum": 2}


def _scored(master_id: int, *, roster_size=10, overlap=2, eligibility="eligible"):
    return {
        "master_id": master_id,
        "roster_size": roster_size,
        "overlap_existing": overlap,
        "eligibility": eligibility,
    }


def test_the_real_committed_policy_file_loads(tmp_path: Path) -> None:
    """Pins this against the real artifact, not a fixture -- the whole point is
    that the committed file is finally being read by code."""
    real = Path("data/albums/expansion-policy-v1.json")
    lanes = load_automatic_lane_policy(real)
    assert lanes["roster_band"] == {"min": 5, "max": 30}
    assert lanes["overlap_existing_minimum"] == 2


@pytest.mark.parametrize(
    "payload, message",
    [
        ({}, "no automatic_lanes block"),
        ({"automatic_lanes": {"overlap_existing_minimum": 2}}, "roster_band must define"),
        ({"automatic_lanes": {"roster_band": {"min": 5}}}, "roster_band must define"),
        (
            {"automatic_lanes": {"roster_band": {"min": 5, "max": 30}}},
            "no overlap_existing_minimum",
        ),
    ],
)
def test_an_incomplete_policy_is_refused(tmp_path: Path, payload: dict, message: str) -> None:
    """Fail closed. A policy that gates nothing while reading as enforcement in
    the round log is worse than no policy at all."""
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ExpansionPolicyError, match=message):
        load_automatic_lane_policy(path)


def test_a_candidate_inside_the_band_passes() -> None:
    assert automatic_lane_rejection(_scored(1), policy=POLICY) is None


def test_rosters_outside_the_band_are_rejected() -> None:
    """Round 1's real failure: four of six picks had rosters of 34, 40, 42 and
    50 against a committed 5-30 band."""
    for roster_size in (34, 40, 42, 50):
        reason = automatic_lane_rejection(_scored(1, roster_size=roster_size), policy=POLICY)
        assert reason is not None
        assert reason.startswith("roster_outside_band")
    assert automatic_lane_rejection(_scored(1, roster_size=4), policy=POLICY) is not None


def test_overlap_below_the_minimum_is_rejected() -> None:
    reason = automatic_lane_rejection(_scored(1, overlap=1), policy=POLICY)
    assert reason is not None and reason.startswith("overlap_below_minimum")
    # The collection-relaxed threshold admits it.
    relaxed = {"roster_band": {"min": 5, "max": 30}, "overlap_existing_minimum": 1}
    assert automatic_lane_rejection(_scored(1, overlap=1), policy=relaxed) is None


def test_an_unscored_candidate_is_never_admitted() -> None:
    """The band cannot be checked without roster_size, so an unscored candidate
    must be rejected rather than assumed to pass."""
    assert automatic_lane_rejection(None, policy=POLICY) == "not_scored"
    assert automatic_lane_rejection(_scored(1, roster_size=None), policy=POLICY) == (
        "roster_size_unknown"
    )


def test_an_ineligible_candidate_keeps_its_own_reason() -> None:
    reason = automatic_lane_rejection(
        _scored(1, eligibility="curated_master_exclusion"), policy=POLICY
    )
    assert reason == "curated_master_exclusion"


def test_filter_preserves_order_and_reports_why_the_pool_shrank() -> None:
    finalists = [{"master_id": m} for m in (1, 2, 3, 4, 5)]
    scored = [
        _scored(1),
        _scored(2, roster_size=50),
        _scored(3, overlap=0),
        _scored(4),
        # 5 is deliberately unscored.
    ]
    kept, rejections = filter_to_automatic_lane(finalists, scored, policy=POLICY)

    assert [f["master_id"] for f in kept] == [1, 4]
    assert rejections == {
        "roster_outside_band": 1,
        "overlap_below_minimum": 1,
        "not_scored": 1,
    }
