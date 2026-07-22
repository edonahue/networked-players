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
    schedule_expiry_status,
    validate_connection_daily_manifest,
)
from networked_players_graph_core.connection_rounds import (
    artifact_version as recompute_artifact_version,
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

GENERATED_AT = "2026-07-22T00:00:00+00:00"


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


def _round_id(i: int) -> str:
    # A well-formed conn-<10 hex chars> id (not the real content-derived hash,
    # just format-compliant, since these tests exercise the manifest layer,
    # not the round generator).
    return f"conn-{i:010x}"


def _real_pool(n: int = 6) -> dict[str, Any]:
    rounds = [
        _one_hop_round(_round_id(i), f"album-a{i}", f"album-c{i}", 1000 + i) for i in range(n)
    ]
    rounds.append(_two_hop_round("conn-2h001"))
    rounds.append(_synthetic_one_hop_round("syn-1h-001"))
    return _rounds_artifact(rounds)


def test_only_real_one_hop_rounds_are_eligible() -> None:
    pool = _real_pool(4)
    manifest = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=10, generated_at=GENERATED_AT
    )
    scheduled_ids = {e["round_id"] for e in manifest["schedule"]}
    assert scheduled_ids == {_round_id(i) for i in range(4)}
    assert "conn-2h001" not in scheduled_ids
    assert "syn-1h-001" not in scheduled_ids
    assert len(manifest["schedule"]) == 4  # never padded past what's eligible


def test_manifest_carries_mode_and_versions() -> None:
    pool = _real_pool(4)
    manifest = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=10, generated_at=GENERATED_AT
    )
    assert manifest["mode"] == CONNECTION_DAILY_MANIFEST_MODE
    assert manifest["catalog_version"] == PROVENANCE["catalog_version"]
    assert manifest["pool_version"] == PROVENANCE["pool_version"]
    assert manifest["artifact_version"] == PROVENANCE["artifact_version"]


def test_initial_generation_is_deterministic() -> None:
    pool = _real_pool(10)
    a = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=10, generated_at=GENERATED_AT
    )
    b = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=10, generated_at=GENERATED_AT
    )
    assert a["schedule"] == b["schedule"]


def test_extension_is_deterministic() -> None:
    pool = _real_pool(10)
    base = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=3, generated_at=GENERATED_AT
    )
    a = extend_connection_daily_manifest(deepcopy(base), pool, days=3, generated_at=GENERATED_AT)
    b = extend_connection_daily_manifest(deepcopy(base), pool, days=3, generated_at=GENERATED_AT)
    assert a["schedule"] == b["schedule"]


def test_extension_never_changes_existing_entries() -> None:
    pool = _real_pool(10)
    base = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=3, generated_at=GENERATED_AT
    )
    extended = extend_connection_daily_manifest(
        deepcopy(base), pool, days=3, generated_at=GENERATED_AT
    )
    assert extended["schedule"][:3] == base["schedule"]
    assert len(extended["schedule"]) == 6
    assert extended["schedule"][3]["date"] == "2026-08-04"


def test_extension_rejects_a_round_whose_content_silently_changed() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=3, generated_at=GENERATED_AT
    )
    tampered_pool = deepcopy(pool)
    # Silently edit the scheduled round's answer -- content changes, id does not.
    tampered_pool["rounds"][0]["answer_set"][0]["name"] = "Someone Else"
    with pytest.raises(ConnectionDailyManifestError, match="fingerprint mismatch"):
        extend_connection_daily_manifest(manifest, tampered_pool, days=2, generated_at=GENERATED_AT)


def test_extension_rejects_a_missing_scheduled_round() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=3, generated_at=GENERATED_AT
    )
    scheduled_id = manifest["schedule"][0]["round_id"]
    tampered_pool = deepcopy(pool)
    tampered_pool["rounds"] = [r for r in tampered_pool["rounds"] if r["id"] != scheduled_id]
    with pytest.raises(ConnectionDailyManifestError, match="missing from the current rounds"):
        extend_connection_daily_manifest(manifest, tampered_pool, days=2, generated_at=GENERATED_AT)


def test_extension_after_pool_exhaustion_raises_documented_policy_error() -> None:
    pool = _real_pool(3)
    manifest = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=3, generated_at=GENERATED_AT
    )
    with pytest.raises(ConnectionDailyManifestError, match="already been scheduled once"):
        extend_connection_daily_manifest(manifest, pool, days=1, generated_at=GENERATED_AT)


def test_validator_accepts_a_freshly_built_manifest() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=6, generated_at=GENERATED_AT
    )
    validate_connection_daily_manifest(manifest, pool)  # does not raise


def test_validator_rejects_duplicate_dates() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=6, generated_at=GENERATED_AT
    )
    manifest["schedule"][1] = dict(manifest["schedule"][1], date=manifest["schedule"][0]["date"])
    with pytest.raises(ConnectionDailyManifestError, match="duplicate date"):
        validate_connection_daily_manifest(manifest, pool)


def test_validator_rejects_a_gap_in_dates() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=6, generated_at=GENERATED_AT
    )
    manifest["schedule"][2]["date"] = "2026-09-01"
    with pytest.raises(ConnectionDailyManifestError, match="gap or disorder"):
        validate_connection_daily_manifest(manifest, pool)


def test_validator_rejects_an_unknown_round_id() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=6, generated_at=GENERATED_AT
    )
    manifest["schedule"][0]["round_id"] = "conn-doesnotexist"
    manifest["schedule"][0]["round_fingerprint"] = "rfp-doesnotexist"
    with pytest.raises(ConnectionDailyManifestError, match="not in the published pool"):
        validate_connection_daily_manifest(manifest, pool)


def test_validator_rejects_a_two_hop_round_id() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=6, generated_at=GENERATED_AT
    )
    two_hop = next(r for r in pool["rounds"] if r["kind"] == "two_hop")
    manifest["schedule"][0]["round_id"] = two_hop["id"]
    manifest["schedule"][0]["round_fingerprint"] = round_content_fingerprint(two_hop)
    with pytest.raises(ConnectionDailyManifestError, match="not a real one-hop round"):
        validate_connection_daily_manifest(manifest, pool)


def test_validator_rejects_a_synthetic_round_id() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=6, generated_at=GENERATED_AT
    )
    synthetic = next(r for r in pool["rounds"] if r["pool"] == "synthetic-universe")
    manifest["schedule"][0]["round_id"] = synthetic["id"]
    manifest["schedule"][0]["round_fingerprint"] = round_content_fingerprint(synthetic)
    with pytest.raises(ConnectionDailyManifestError, match="not a real one-hop round"):
        validate_connection_daily_manifest(manifest, pool)


def test_validator_rejects_pool_version_mismatch() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=6, generated_at=GENERATED_AT
    )
    other_pool = deepcopy(pool)
    other_pool["provenance"]["pool_version"] = "connection-v1-20260601-different"
    with pytest.raises(ConnectionDailyManifestError, match="pool_version"):
        validate_connection_daily_manifest(manifest, other_pool)


def test_validator_rejects_a_round_fingerprint_mismatch() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=6, generated_at=GENERATED_AT
    )
    manifest["schedule"][0]["round_fingerprint"] = "rfp-wrongvalue00000"
    with pytest.raises(ConnectionDailyManifestError, match="fingerprint mismatch"):
        validate_connection_daily_manifest(manifest, pool)


def test_validator_rejects_a_nested_seed_key() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=6, generated_at=GENERATED_AT
    )
    manifest["schedule"][0]["seed"] = "leaked"
    with pytest.raises(ConnectionDailyManifestError, match="'seed' key"):
        validate_connection_daily_manifest(manifest, pool)


def test_validator_rejects_a_duplicate_round_id_across_dates() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=6, generated_at=GENERATED_AT
    )
    manifest["schedule"][1]["round_id"] = manifest["schedule"][0]["round_id"]
    manifest["schedule"][1]["round_fingerprint"] = manifest["schedule"][0]["round_fingerprint"]
    with pytest.raises(ConnectionDailyManifestError, match="scheduled more than once"):
        validate_connection_daily_manifest(manifest, pool)


def test_no_eligible_rounds_raises() -> None:
    pool = _rounds_artifact([_two_hop_round("conn-2h001")])
    with pytest.raises(ConnectionDailyManifestError, match="no eligible one-hop"):
        build_connection_daily_manifest(
            pool, start_date="2026-08-01", days=10, generated_at=GENERATED_AT
        )


def test_schedule_diagnostics_reports_real_numbers() -> None:
    pool = _real_pool(10)
    manifest = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=10, generated_at=GENERATED_AT
    )
    diagnostics = schedule_diagnostics(manifest, pool)
    assert diagnostics["total_dates"] == 10
    assert diagnostics["distinct_rounds"] == 10
    assert diagnostics["repeated_rounds"] == 0
    assert "difficulty_distribution" in diagnostics
    assert "decade_distribution" in diagnostics
    assert diagnostics["longest_adjacent_endpoint_repeat_streak"] >= 0


def test_schedule_expiry_status_reports_days_remaining() -> None:
    pool = _real_pool(10)
    manifest = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=10, generated_at=GENERATED_AT
    )
    # schedule spans 2026-08-01..2026-08-10 (10 consecutive dates)
    status = schedule_expiry_status(manifest, as_of="2026-08-01", warn_within_days=14)
    assert status["last_scheduled_date"] == "2026-08-10"
    assert status["total_dates"] == 10
    assert status["days_remaining"] == 9
    assert status["needs_extension_soon"] is True  # 9 <= 14
    assert status["already_expired"] is False


def test_schedule_expiry_status_boundary_at_exactly_warn_within_days() -> None:
    pool = _real_pool(10)
    manifest = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=10, generated_at=GENERATED_AT
    )
    # last date 2026-08-10, as_of 2026-07-27 -> exactly 14 days remaining
    status = schedule_expiry_status(manifest, as_of="2026-07-27", warn_within_days=14)
    assert status["days_remaining"] == 14
    assert status["needs_extension_soon"] is True


def test_schedule_expiry_status_not_needed_well_before_expiry() -> None:
    pool = _real_pool(10)
    manifest = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=10, generated_at=GENERATED_AT
    )
    status = schedule_expiry_status(manifest, as_of="2026-07-01", warn_within_days=14)
    assert status["days_remaining"] == 40
    assert status["needs_extension_soon"] is False
    assert status["already_expired"] is False


def test_schedule_expiry_status_negative_days_remaining_is_expired() -> None:
    pool = _real_pool(10)
    manifest = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=10, generated_at=GENERATED_AT
    )
    status = schedule_expiry_status(manifest, as_of="2026-09-01", warn_within_days=14)
    assert status["days_remaining"] < 0
    assert status["already_expired"] is True
    assert status["needs_extension_soon"] is True


def test_schedule_expiry_status_raises_on_empty_schedule() -> None:
    manifest = build_connection_daily_manifest(
        _real_pool(10), start_date="2026-08-01", days=10, generated_at=GENERATED_AT
    )
    manifest["schedule"] = []
    with pytest.raises(ConnectionDailyManifestError, match="schedule must be non-empty"):
        schedule_expiry_status(manifest, as_of="2026-08-01")


# --- Corrective slice 5.1: strict single-artifact-version manifest policy ---
# A schema-v1 manifest may only ever contain entries from ONE exact rounds
# generation -- catalog_version, pool_version, AND artifact_version must all
# agree exactly between the manifest and the paired rounds artifact, checked
# before validating, building, OR extending (fail before any output).


def test_validator_rejects_catalog_version_mismatch() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=6, generated_at=GENERATED_AT
    )
    other_pool = deepcopy(pool)
    other_pool["provenance"]["catalog_version"] = "catalog-v1-20260601-different"
    with pytest.raises(ConnectionDailyManifestError, match="catalog_version"):
        validate_connection_daily_manifest(manifest, other_pool)


def test_validator_rejects_artifact_version_mismatch() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=6, generated_at=GENERATED_AT
    )
    other_pool = deepcopy(pool)
    other_pool["provenance"]["artifact_version"] = "connection-artifact-v1-20260601-different"
    with pytest.raises(ConnectionDailyManifestError, match="artifact_version"):
        validate_connection_daily_manifest(manifest, other_pool)


def test_extend_rejects_catalog_version_mismatch_before_any_output() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=3, generated_at=GENERATED_AT
    )
    other_pool = deepcopy(pool)
    other_pool["provenance"]["catalog_version"] = "catalog-v1-20260601-different"
    with pytest.raises(ConnectionDailyManifestError, match="catalog_version"):
        extend_connection_daily_manifest(manifest, other_pool, days=2, generated_at=GENERATED_AT)


def test_extend_rejects_pool_version_mismatch_before_any_output() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=3, generated_at=GENERATED_AT
    )
    other_pool = deepcopy(pool)
    other_pool["provenance"]["pool_version"] = "connection-v1-20260601-different"
    with pytest.raises(ConnectionDailyManifestError, match="pool_version"):
        extend_connection_daily_manifest(manifest, other_pool, days=2, generated_at=GENERATED_AT)


def test_extend_rejects_artifact_version_mismatch_before_any_output() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=3, generated_at=GENERATED_AT
    )
    other_pool = deepcopy(pool)
    other_pool["provenance"]["artifact_version"] = "connection-artifact-v1-20260601-different"
    with pytest.raises(ConnectionDailyManifestError, match="artifact_version"):
        extend_connection_daily_manifest(manifest, other_pool, days=2, generated_at=GENERATED_AT)


def test_extend_and_validate_reject_unchanged_membership_but_changed_unscheduled_round() -> None:
    """Realistic drift scenario: an UNSCHEDULED round's content silently
    changes (e.g. a clue edit during a later regeneration). Membership
    (pool_version) is unchanged, but the honestly-recomputed
    artifact_version moves -- the manifest, frozen at the old
    artifact_version, must be refused rather than silently extended or
    accepted as still-valid."""
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=3, generated_at=GENERATED_AT
    )
    scheduled_ids = {e["round_id"] for e in manifest["schedule"]}
    drifted_pool = deepcopy(pool)
    unscheduled = next(r for r in drifted_pool["rounds"] if r["id"] not in scheduled_ids)
    unscheduled["clues"] = [{"kind": "years", "text": "A brand-new clue text."}]
    # Honest regeneration: the rounds artifact's OWN provenance is updated to
    # reflect its real new content -- pool_version (membership) is
    # unchanged, artifact_version (content) is not.
    drifted_pool["provenance"]["artifact_version"] = recompute_artifact_version(
        drifted_pool["rounds"], drifted_pool["provenance"]["snapshot_date"]
    )
    assert drifted_pool["provenance"]["pool_version"] == pool["provenance"]["pool_version"]
    assert drifted_pool["provenance"]["artifact_version"] != pool["provenance"]["artifact_version"]

    with pytest.raises(ConnectionDailyManifestError, match="artifact_version"):
        validate_connection_daily_manifest(manifest, drifted_pool)
    with pytest.raises(ConnectionDailyManifestError, match="artifact_version"):
        extend_connection_daily_manifest(manifest, drifted_pool, days=2, generated_at=GENERATED_AT)


def test_extend_and_validate_reject_reordered_rounds_array() -> None:
    """Same membership, same per-round content, only the published array's
    ORDER changed -- artifact_version is order-sensitive (corrective slice
    5.1), so this must be refused exactly like a content edit."""
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=3, generated_at=GENERATED_AT
    )
    reordered_pool = deepcopy(pool)
    reordered_pool["rounds"] = list(reversed(reordered_pool["rounds"]))
    reordered_pool["provenance"]["artifact_version"] = recompute_artifact_version(
        reordered_pool["rounds"], reordered_pool["provenance"]["snapshot_date"]
    )
    assert (
        reordered_pool["provenance"]["artifact_version"] != pool["provenance"]["artifact_version"]
    )

    with pytest.raises(ConnectionDailyManifestError, match="artifact_version"):
        validate_connection_daily_manifest(manifest, reordered_pool)
    with pytest.raises(ConnectionDailyManifestError, match="artifact_version"):
        extend_connection_daily_manifest(
            manifest, reordered_pool, days=2, generated_at=GENERATED_AT
        )


def test_validator_rejects_manifest_metadata_hand_edited_to_hide_a_mismatch() -> None:
    """Hand-editing ONLY the manifest's top-level version fields to match a
    different rounds artifact's declared versions is not enough to pass
    validation: the manifest's `schedule[]` still reflects the OLD
    generation, and per-entry structural/referential checks are independent
    of the top-level version-agreement check -- a real mismatch (here, a
    scheduled round entirely missing from the "new" artifact) is still
    caught even when the top-level metadata was forged to agree."""
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=6, generated_at=GENERATED_AT
    )
    scheduled_id = manifest["schedule"][0]["round_id"]
    other_pool = _real_pool(6)
    other_pool["rounds"] = [r for r in other_pool["rounds"] if r["id"] != scheduled_id]
    other_pool["provenance"] = {
        **other_pool["provenance"],
        "pool_version": "connection-v1-20260601-otherpool",
        "artifact_version": "connection-artifact-v1-20260601-otherpool",
    }
    # Hand-edit the manifest's OWN metadata to match the other artifact's
    # declared versions, attempting to disguise the mismatch, WITHOUT
    # actually re-deriving the schedule from that artifact.
    tampered_manifest = deepcopy(manifest)
    tampered_manifest["pool_version"] = other_pool["provenance"]["pool_version"]
    tampered_manifest["artifact_version"] = other_pool["provenance"]["artifact_version"]
    with pytest.raises(ConnectionDailyManifestError, match="not in the published pool"):
        validate_connection_daily_manifest(tampered_manifest, other_pool)


# --- Corrective slice 5.1: strengthened structural/format validation -------


def test_validator_rejects_malformed_generated_at() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=6, generated_at=GENERATED_AT
    )
    manifest["generated_at"] = "not-a-datetime"
    with pytest.raises(ConnectionDailyManifestError, match="generated_at"):
        validate_connection_daily_manifest(manifest, pool)


def test_validator_rejects_malformed_start_date() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=6, generated_at=GENERATED_AT
    )
    manifest["start_date"] = "not-a-date"
    with pytest.raises(ConnectionDailyManifestError, match="start_date"):
        validate_connection_daily_manifest(manifest, pool)


def test_validator_rejects_start_date_not_matching_first_entry() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=6, generated_at=GENERATED_AT
    )
    manifest["start_date"] = "2026-08-02"
    with pytest.raises(ConnectionDailyManifestError, match="start_date"):
        validate_connection_daily_manifest(manifest, pool)


def test_validator_rejects_malformed_round_id_format() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=6, generated_at=GENERATED_AT
    )
    manifest["schedule"][0]["round_id"] = "not-a-conn-id"
    with pytest.raises(ConnectionDailyManifestError, match="not a stable content-derived id"):
        validate_connection_daily_manifest(manifest, pool)


def test_validator_rejects_malformed_round_fingerprint_format() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=6, generated_at=GENERATED_AT
    )
    manifest["schedule"][0]["round_fingerprint"] = "not-a-fingerprint"
    with pytest.raises(ConnectionDailyManifestError, match="well-formed content fingerprint"):
        validate_connection_daily_manifest(manifest, pool)


def test_validator_rejects_forbidden_substring() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=6, generated_at=GENERATED_AT
    )
    manifest["catalog_version"] = manifest["catalog_version"] + " /home/operator/data"
    with pytest.raises(ConnectionDailyManifestError, match="forbidden substring"):
        validate_connection_daily_manifest(manifest, pool)


def test_validator_rejects_forbidden_phrase() -> None:
    pool = _real_pool(6)
    manifest = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=6, generated_at=GENERATED_AT
    )
    manifest["catalog_version"] = manifest["catalog_version"] + " they worked with everyone"
    with pytest.raises(ConnectionDailyManifestError, match="forbidden phrase"):
        validate_connection_daily_manifest(manifest, pool)


# --- Corrective slice 5.1: byte-identical reproducibility as COMPLETE ------
# artifacts (not just the schedule array), given an explicit generated_at.


def test_initial_generation_is_byte_identical_as_a_complete_artifact() -> None:
    pool = _real_pool(10)
    a = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=10, generated_at=GENERATED_AT
    )
    b = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=10, generated_at=GENERATED_AT
    )
    assert a == b


def test_extension_is_byte_identical_as_a_complete_artifact() -> None:
    pool = _real_pool(10)
    base = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=3, generated_at=GENERATED_AT
    )
    a = extend_connection_daily_manifest(deepcopy(base), pool, days=3, generated_at=GENERATED_AT)
    b = extend_connection_daily_manifest(deepcopy(base), pool, days=3, generated_at=GENERATED_AT)
    assert a == b


def test_extension_changes_only_generated_at_and_appended_schedule_entries() -> None:
    pool = _real_pool(10)
    base = build_connection_daily_manifest(
        pool, start_date="2026-08-01", days=3, generated_at=GENERATED_AT
    )
    later = "2026-08-05T12:00:00+00:00"
    extended = extend_connection_daily_manifest(deepcopy(base), pool, days=3, generated_at=later)
    for field_name in (
        "schema_version",
        "mode",
        "catalog_version",
        "pool_version",
        "artifact_version",
        "start_date",
    ):
        assert extended[field_name] == base[field_name]
    assert extended["generated_at"] == later
    assert extended["schedule"][: len(base["schedule"])] == base["schedule"]
    assert len(extended["schedule"]) == len(base["schedule"]) + 3


def test_build_rejects_a_non_iso_generated_at() -> None:
    pool = _real_pool(6)
    with pytest.raises(ConnectionDailyManifestError, match="generated_at"):
        build_connection_daily_manifest(
            pool, start_date="2026-08-01", days=6, generated_at="not-a-datetime"
        )


# --- Corrective slice 5.1: extension-boundary adjacency quality ------------


def test_extension_avoids_conflict_with_prior_last_round_when_possible() -> None:
    base_pool = _rounds_artifact(
        [
            _one_hop_round(_round_id(0), "album-a0", "album-c0", 2000),
            _one_hop_round(_round_id(1), "album-a1", "album-c1", 2001),
        ]
    )
    manifest = build_connection_daily_manifest(
        base_pool, start_date="2026-08-01", days=2, generated_at=GENERATED_AT
    )
    last_round_id = manifest["schedule"][-1]["round_id"]
    last_round = next(r for r in base_pool["rounds"] if r["id"] == last_round_id)
    shared_endpoint = last_round["endpoints"][0]["id"]

    extended_pool = deepcopy(base_pool)
    extended_pool["rounds"] += [
        _one_hop_round(_round_id(10), shared_endpoint, "album-cX10", 3010),
        _one_hop_round(_round_id(11), shared_endpoint, "album-cX11", 3011),
        _one_hop_round(_round_id(12), "album-aX12", "album-cX12", 3012),  # no conflict
    ]
    extended = extend_connection_daily_manifest(
        manifest, extended_pool, days=1, generated_at=GENERATED_AT
    )
    assert extended["schedule"][-1]["round_id"] == _round_id(12)


def test_extension_forced_conflict_at_boundary_is_deterministic_and_reported() -> None:
    base_pool = _rounds_artifact([_one_hop_round(_round_id(0), "album-a0", "album-c0", 2000)])
    manifest = build_connection_daily_manifest(
        base_pool, start_date="2026-08-01", days=1, generated_at=GENERATED_AT
    )
    shared_endpoint = base_pool["rounds"][0]["endpoints"][0]["id"]

    conflicting_pool = deepcopy(base_pool)
    conflicting_pool["rounds"] += [
        _one_hop_round(_round_id(10), shared_endpoint, "album-cX10", 3010),
        _one_hop_round(_round_id(11), shared_endpoint, "album-cX11", 3011),
    ]
    a = extend_connection_daily_manifest(
        deepcopy(manifest), conflicting_pool, days=2, generated_at=GENERATED_AT
    )
    b = extend_connection_daily_manifest(
        deepcopy(manifest), conflicting_pool, days=2, generated_at=GENERATED_AT
    )
    assert a["schedule"] == b["schedule"]  # deterministic even under a forced conflict
    assert a["schedule"][0] == manifest["schedule"][0]  # old entry untouched

    diagnostics = schedule_diagnostics(a, conflicting_pool)
    assert diagnostics["longest_adjacent_endpoint_repeat_streak"] >= 2
