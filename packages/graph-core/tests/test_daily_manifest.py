from __future__ import annotations

from datetime import date, timedelta

import pytest

from networked_players_graph_core.daily_manifest import (
    DailyManifestError,
    build_daily_manifest,
    extend_daily_manifest,
    validate_daily_manifest,
)

ROUND_IDS = [f"round-{i:06d}" for i in range(1, 11)]


def test_build_daily_manifest_schedules_consecutive_dates() -> None:
    manifest = build_daily_manifest(
        ROUND_IDS, pool_version="rounds-v1-a", start_date="2026-07-19", days=5
    )
    dates = [entry["date"] for entry in manifest["schedule"]]
    assert dates == [(date(2026, 7, 19) + timedelta(days=i)).isoformat() for i in range(5)]
    assert len(manifest["schedule"]) == 5


def test_build_daily_manifest_uses_every_round_at_most_once() -> None:
    manifest = build_daily_manifest(
        ROUND_IDS, pool_version="rounds-v1-a", start_date="2026-07-19", days=5
    )
    round_ids = [entry["round_id"] for entry in manifest["schedule"]]
    assert len(round_ids) == len(set(round_ids))
    assert set(round_ids) <= set(ROUND_IDS)


def test_build_daily_manifest_never_pads_past_available_rounds() -> None:
    manifest = build_daily_manifest(
        ROUND_IDS, pool_version="rounds-v1-a", start_date="2026-07-19", days=365
    )
    assert len(manifest["schedule"]) == len(ROUND_IDS)  # 10, not 365 -- no repeats


def test_build_daily_manifest_is_deterministic_for_a_fixed_pool_version() -> None:
    first = build_daily_manifest(
        ROUND_IDS, pool_version="rounds-v1-a", start_date="2026-07-19", days=5
    )
    second = build_daily_manifest(
        ROUND_IDS, pool_version="rounds-v1-a", start_date="2026-07-19", days=5
    )
    assert first["schedule"] == second["schedule"]


def test_build_daily_manifest_differs_across_pool_versions() -> None:
    a = build_daily_manifest(
        ROUND_IDS, pool_version="rounds-v1-a", start_date="2026-07-19", days=10
    )
    b = build_daily_manifest(
        ROUND_IDS, pool_version="rounds-v1-b", start_date="2026-07-19", days=10
    )
    assert [e["round_id"] for e in a["schedule"]] != [e["round_id"] for e in b["schedule"]]


def test_build_daily_manifest_rejects_duplicate_round_ids() -> None:
    with pytest.raises(ValueError, match="must not contain duplicates"):
        build_daily_manifest(
            [*ROUND_IDS, ROUND_IDS[0]], pool_version="rounds-v1-a", start_date="2026-07-19", days=5
        )


def test_extend_daily_manifest_appends_after_the_last_date_without_touching_history() -> None:
    manifest = build_daily_manifest(
        ROUND_IDS[:5], pool_version="rounds-v1-a", start_date="2026-07-19", days=5
    )
    original_schedule = list(manifest["schedule"])

    extended = extend_daily_manifest(manifest, ROUND_IDS, days=5)

    assert extended["schedule"][:5] == original_schedule  # history untouched
    new_entries = extended["schedule"][5:]
    assert len(new_entries) == 5
    assert new_entries[0]["date"] == "2026-07-24"  # day after 2026-07-23
    # Rounds already scheduled in history are never reused.
    already_used = {e["round_id"] for e in original_schedule}
    assert not ({e["round_id"] for e in new_entries} & already_used)


def test_extend_daily_manifest_raises_when_no_unscheduled_rounds_remain() -> None:
    manifest = build_daily_manifest(
        ROUND_IDS, pool_version="rounds-v1-a", start_date="2026-07-19", days=10
    )
    with pytest.raises(DailyManifestError, match="no unscheduled rounds"):
        extend_daily_manifest(manifest, ROUND_IDS, days=5)


def test_validate_daily_manifest_accepts_a_valid_manifest() -> None:
    manifest = build_daily_manifest(
        ROUND_IDS, pool_version="rounds-v1-a", start_date="2026-07-19", days=5
    )
    validate_daily_manifest(manifest, valid_round_ids=set(ROUND_IDS))


def test_validate_daily_manifest_rejects_unpublished_round() -> None:
    manifest = build_daily_manifest(
        ROUND_IDS, pool_version="rounds-v1-a", start_date="2026-07-19", days=5
    )
    with pytest.raises(DailyManifestError, match="not in the published pool"):
        validate_daily_manifest(manifest, valid_round_ids={"round-999999"})


def test_validate_daily_manifest_rejects_a_gap() -> None:
    manifest = build_daily_manifest(
        ROUND_IDS, pool_version="rounds-v1-a", start_date="2026-07-19", days=5
    )
    manifest["schedule"][2]["date"] = "2099-01-01"
    with pytest.raises(DailyManifestError, match="gap or disorder"):
        validate_daily_manifest(manifest, valid_round_ids=set(ROUND_IDS))


def test_validate_daily_manifest_rejects_duplicate_round_across_dates() -> None:
    manifest = build_daily_manifest(
        ROUND_IDS, pool_version="rounds-v1-a", start_date="2026-07-19", days=5
    )
    manifest["schedule"][1]["round_id"] = manifest["schedule"][0]["round_id"]
    with pytest.raises(DailyManifestError, match="scheduled more than once"):
        validate_daily_manifest(manifest, valid_round_ids=set(ROUND_IDS))
