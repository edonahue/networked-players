from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from networked_players_graph_core.connection_daily_manifest import (
    CONNECTION_DAILY_MANIFEST_MODE,
    ConnectionDailyManifestError,
    build_connection_daily_manifest,
    extend_connection_daily_manifest,
    schedule_diagnostics,
    validate_connection_daily_manifest,
)
from networked_players_graph_core.connection_rounds import round_content_fingerprint

PROVENANCE = {
    "source": "Discogs monthly data dump (CC0), one-hop working set",
    "license": "See docs/DATA_AND_RIGHTS.md.",
    "snapshot_date": "20260601",
    "generated_by": "test",
    "catalog_version": "catalog-v1-20260601-abc",
    "pool_version": "connection-v1-20260601-def",
    "artifact_version": "connection-artifact-v1-20260601-ghi",
    "note": "Real records, not synthetic.",
}


def _album(album_id: str, year: int) -> dict[str, Any]:
    return {
        "id": album_id,
        "title": album_id,
        "year": year,
        "act": "Act",
        "label": None,
        "art": None,
    }


def _one_hop_round(
    round_id: str, a: str, c: str, answer_id: int, *, difficulty="hard"
) -> dict[str, Any]:
    return {
        "id": round_id,
        "pool": "real-records",
        "kind": "one_hop",
        "difficulty": difficulty,
        "endpoints": [_album(a, 1990), _album(c, 1995)],
        "answer_set": [
            {"id": answer_id, "name": f"Performer{answer_id}", "role_category": "guitar"}
        ],
        "distractors": [],
        "clues": [],
        "evidence": [{"contributor_id": answer_id}],
        "provenance_note": "test",
    }


def _two_hop_round(round_id: str) -> dict[str, Any]:
    return {
        "id": round_id,
        "pool": "real-records",
        "kind": "two_hop",
        "difficulty": "hard",
        "endpoints": [_album("album-x", 1990), _album("album-y", 1995)],
        "middle": {"album": _album("album-m", 1992), "choices": [_album("album-m", 1992)]},
        "answer_set": [],
        "bridge_answer_sets": [[], []],
        "distractors": [],
        "clues": [],
        "evidence": [],
        "provenance_note": "test",
    }


def _synthetic_one_hop_round(round_id: str) -> dict[str, Any]:
    round_json = _one_hop_round(round_id, "syn-a01", "syn-a02", 90000001)
    round_json["pool"] = "synthetic-universe"
    return round_json


def _rounds_artifact(rounds: list[dict[str, Any]]) -> dict[str, Any]:
    return {"schema_version": 1, "provenance": PROVENANCE, "rounds": rounds}


def _real_pool(n: int = 6) -> dict[str, Any]:
    rounds = [
        _one_hop_round(f"conn-r{i:03d}", f"album-a{i}", f"album-c{i}", 1000 + i) for i in range(n)
    ]
    rounds.append(_two_hop_round("conn-2h001"))
    rounds.append(_synthetic_one_hop_round("syn-1h-001"))
    return _rounds_artifact(rounds)


def test_only_real_one_hop_rounds_are_eligible() -> None:
    pool = _real_pool(4)
    manifest = build_connection_daily_manifest(pool, start_date="2026-08-01", days=10)
    scheduled_ids = {e["round_id"] for e in manifest["schedule"]}
    assert scheduled_ids == {f"conn-r{i:03d}" for i in range(4)}
    assert "conn-2h001" not in scheduled_ids
    assert "syn-1h-001" not in scheduled_ids
    assert len(manifest["schedule"]) == 4  # never padded past what's eligible


def test_manifest_carries_mode_and_versions() -> None:
    pool = _real_pool(4)
    manifest = build_connection_daily_manifest(pool, start_date="2026-08-01", days=10)
    assert manifest["mode"] == CONNECTION_DAILY_MANIFEST_MODE
    assert manifest["catalog_version"] == PROVENANCE["catalog_version"]
    assert manifest["pool_version"] == PROVENANCE["pool_version"]
    assert manifest["artifact_version"] == PROVENANCE["artifact_version"]


def test_initial_generation_is_deterministic() -> None:
    pool = _real_pool(10)
    a = build_connection_daily_manifest(pool, start_date="2026-08-01", days=10)
    b = build_connection_daily_manifest(pool, start_date="2026-08-01", days=10)
    assert a["schedule"] == b["schedule"]


def test_extension_is_deterministic() -> None:
    pool = _real_pool(10)
    base = build_connection_daily_manifest(pool, start_date="2026-08-01", days=3)
    a = extend_connection_daily_manifest(deepcopy(base), pool, days=3)
    b = extend_connection_daily_manifest(deepcopy(base), pool, days=3)
    assert a["schedule"] == b["schedule"]


def test_extension_never_changes_existing_entries() -> None:
    pool = _real_pool(10)
    base = build_connection_daily_manifest(pool, start_date="2026-08-01", days=3)
    extended = extend_connection_daily_manifest(deepcopy(base), pool, days=3)
    assert extended["schedule"][:3] == base["schedule"]
    assert len(extended["schedule"]) == 6
    assert extended["schedule"][3]["date"] == "2026-08-04"


def test_extension_rejects_a_round_whose_content_silently_changed() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(pool, start_date="2026-08-01", days=3)
    tampered_pool = deepcopy(pool)
    # Silently edit the scheduled round's answer -- content changes, id does not.
    tampered_pool["rounds"][0]["answer_set"][0]["name"] = "Someone Else"
    with pytest.raises(ConnectionDailyManifestError, match="fingerprint mismatch"):
        extend_connection_daily_manifest(manifest, tampered_pool, days=2)


def test_extension_rejects_a_missing_scheduled_round() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(pool, start_date="2026-08-01", days=3)
    scheduled_id = manifest["schedule"][0]["round_id"]
    tampered_pool = deepcopy(pool)
    tampered_pool["rounds"] = [r for r in tampered_pool["rounds"] if r["id"] != scheduled_id]
    with pytest.raises(ConnectionDailyManifestError, match="missing from the current rounds"):
        extend_connection_daily_manifest(manifest, tampered_pool, days=2)


def test_extension_after_pool_exhaustion_raises_documented_policy_error() -> None:
    pool = _real_pool(3)
    manifest = build_connection_daily_manifest(pool, start_date="2026-08-01", days=3)
    with pytest.raises(ConnectionDailyManifestError, match="already been scheduled once"):
        extend_connection_daily_manifest(manifest, pool, days=1)


def test_validator_accepts_a_freshly_built_manifest() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(pool, start_date="2026-08-01", days=6)
    validate_connection_daily_manifest(manifest, pool)  # does not raise


def test_validator_rejects_duplicate_dates() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(pool, start_date="2026-08-01", days=6)
    manifest["schedule"][1] = dict(manifest["schedule"][1], date=manifest["schedule"][0]["date"])
    with pytest.raises(ConnectionDailyManifestError, match="duplicate date"):
        validate_connection_daily_manifest(manifest, pool)


def test_validator_rejects_a_gap_in_dates() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(pool, start_date="2026-08-01", days=6)
    manifest["schedule"][2]["date"] = "2026-09-01"
    with pytest.raises(ConnectionDailyManifestError, match="gap or disorder"):
        validate_connection_daily_manifest(manifest, pool)


def test_validator_rejects_an_unknown_round_id() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(pool, start_date="2026-08-01", days=6)
    manifest["schedule"][0]["round_id"] = "conn-doesnotexist"
    manifest["schedule"][0]["round_fingerprint"] = "rfp-doesnotexist"
    with pytest.raises(ConnectionDailyManifestError, match="not in the published pool"):
        validate_connection_daily_manifest(manifest, pool)


def test_validator_rejects_a_two_hop_round_id() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(pool, start_date="2026-08-01", days=6)
    two_hop = next(r for r in pool["rounds"] if r["kind"] == "two_hop")
    manifest["schedule"][0]["round_id"] = two_hop["id"]
    manifest["schedule"][0]["round_fingerprint"] = round_content_fingerprint(two_hop)
    with pytest.raises(ConnectionDailyManifestError, match="not a real one-hop round"):
        validate_connection_daily_manifest(manifest, pool)


def test_validator_rejects_a_synthetic_round_id() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(pool, start_date="2026-08-01", days=6)
    synthetic = next(r for r in pool["rounds"] if r["pool"] == "synthetic-universe")
    manifest["schedule"][0]["round_id"] = synthetic["id"]
    manifest["schedule"][0]["round_fingerprint"] = round_content_fingerprint(synthetic)
    with pytest.raises(ConnectionDailyManifestError, match="not a real one-hop round"):
        validate_connection_daily_manifest(manifest, pool)


def test_validator_rejects_pool_version_mismatch() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(pool, start_date="2026-08-01", days=6)
    other_pool = deepcopy(pool)
    other_pool["provenance"]["pool_version"] = "connection-v1-20260601-different"
    with pytest.raises(ConnectionDailyManifestError, match="pool_version"):
        validate_connection_daily_manifest(manifest, other_pool)


def test_validator_rejects_a_round_fingerprint_mismatch() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(pool, start_date="2026-08-01", days=6)
    manifest["schedule"][0]["round_fingerprint"] = "rfp-wrongvalue00000"
    with pytest.raises(ConnectionDailyManifestError, match="fingerprint mismatch"):
        validate_connection_daily_manifest(manifest, pool)


def test_validator_rejects_a_nested_seed_key() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(pool, start_date="2026-08-01", days=6)
    manifest["schedule"][0]["seed"] = "leaked"
    with pytest.raises(ConnectionDailyManifestError, match="'seed' key"):
        validate_connection_daily_manifest(manifest, pool)


def test_validator_rejects_a_duplicate_round_id_across_dates() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(pool, start_date="2026-08-01", days=6)
    manifest["schedule"][1]["round_id"] = manifest["schedule"][0]["round_id"]
    manifest["schedule"][1]["round_fingerprint"] = manifest["schedule"][0]["round_fingerprint"]
    with pytest.raises(ConnectionDailyManifestError, match="scheduled more than once"):
        validate_connection_daily_manifest(manifest, pool)


def test_no_eligible_rounds_raises() -> None:
    pool = _rounds_artifact([_two_hop_round("conn-2h001")])
    with pytest.raises(ConnectionDailyManifestError, match="no eligible one-hop"):
        build_connection_daily_manifest(pool, start_date="2026-08-01", days=10)


def test_schedule_diagnostics_reports_real_numbers() -> None:
    pool = _real_pool(10)
    manifest = build_connection_daily_manifest(pool, start_date="2026-08-01", days=10)
    diagnostics = schedule_diagnostics(manifest, pool)
    assert diagnostics["total_dates"] == 10
    assert diagnostics["distinct_rounds"] == 10
    assert diagnostics["repeated_rounds"] == 0
    assert "difficulty_distribution" in diagnostics
    assert "decade_distribution" in diagnostics
    assert diagnostics["longest_adjacent_endpoint_repeat_streak"] >= 0
