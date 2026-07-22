from __future__ import annotations

from copy import deepcopy
from typing import Any

from networked_players_contracts.connection_daily_manifest import (
    CONNECTION_DAILY_MANIFEST_MODE,
    CONNECTION_DAILY_MANIFEST_SCHEMA_VERSION,
    connection_daily_manifest_failures,
)
from networked_players_contracts.connection_rounds import round_content_fingerprint

_SNAPSHOT_DATE = "20260601"
_CATALOG_VERSION = "catalog-v1-20260601-abc123abc123"
_POOL_VERSION = "connection-v1-20260601-def456def456"
_ARTIFACT_VERSION = "connection-artifact-v1-20260601-aaa111aaa111"


def _round(round_id: str = "conn-0000000001") -> dict[str, Any]:
    return {
        "id": round_id,
        "pool": "real-records",
        "kind": "one_hop",
        "difficulty": "hard",
        "endpoints": [
            {
                "id": "album-a",
                "title": "First Light",
                "year": 1995,
                "act": "Alice",
                "label": None,
                "art": None,
            },
            {
                "id": "album-c",
                "title": "Third Wave",
                "year": 1996,
                "act": "Cara",
                "label": None,
                "art": None,
            },
        ],
        "answer_set": [{"id": 700, "name": "Xavier", "role_category": "guitar"}],
        "distractors": [],
        "clues": [],
        "evidence": [],
        "provenance_note": "Real records: derived from the Discogs monthly data dump (CC0).",
    }


_PROVENANCE = {
    "catalog_version": _CATALOG_VERSION,
    "pool_version": _POOL_VERSION,
    "artifact_version": _ARTIFACT_VERSION,
}


def _rounds_artifact() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "provenance": dict(_PROVENANCE),
        "rounds": [_round()],
    }


def _manifest() -> dict[str, Any]:
    round_json = _round()
    return {
        "schema_version": CONNECTION_DAILY_MANIFEST_SCHEMA_VERSION,
        "mode": CONNECTION_DAILY_MANIFEST_MODE,
        "catalog_version": _CATALOG_VERSION,
        "pool_version": _POOL_VERSION,
        "artifact_version": _ARTIFACT_VERSION,
        "generated_at": "2026-07-22T00:00:00+00:00",
        "start_date": "2026-07-22",
        "schedule": [
            {
                "date": "2026-07-22",
                "round_id": round_json["id"],
                "round_fingerprint": round_content_fingerprint(round_json),
            }
        ],
    }


def test_valid_pair_has_no_failures() -> None:
    assert connection_daily_manifest_failures(_manifest(), _rounds_artifact()) == []


def test_rejects_non_object_inputs() -> None:
    assert connection_daily_manifest_failures([], {}) == ["manifest artifact must be an object"]
    assert connection_daily_manifest_failures({}, []) == ["rounds artifact must be an object"]


def test_rejects_wrong_mode() -> None:
    manifest = _manifest()
    manifest["mode"] = "record_routes"
    failures = connection_daily_manifest_failures(manifest, _rounds_artifact())
    assert any("mode must be" in f for f in failures)


def test_rejects_unexpected_top_level_key() -> None:
    manifest = _manifest()
    manifest["extra"] = "nope"
    failures = connection_daily_manifest_failures(manifest, _rounds_artifact())
    assert any("unexpected top-level keys" in f for f in failures)


def test_rejects_version_mismatch() -> None:
    manifest = _manifest()
    manifest["pool_version"] = "connection-v1-20260601-000000000000"
    failures = connection_daily_manifest_failures(manifest, _rounds_artifact())
    assert any("does not match the paired rounds artifact" in f for f in failures)


def test_rejects_bad_generated_at() -> None:
    manifest = _manifest()
    manifest["generated_at"] = "not-a-datetime"
    failures = connection_daily_manifest_failures(manifest, _rounds_artifact())
    assert any("is not a valid ISO datetime" in f for f in failures)


def test_rejects_start_date_mismatch_with_schedule() -> None:
    manifest = _manifest()
    manifest["start_date"] = "2026-07-23"
    failures = connection_daily_manifest_failures(manifest, _rounds_artifact())
    assert any("does not match schedule[0].date" in f for f in failures)


def test_rejects_non_contiguous_dates() -> None:
    round_a = _round("conn-0000000001")
    round_b = _round("conn-0000000002")
    rounds_artifact = {
        "schema_version": 1,
        "provenance": dict(_PROVENANCE),
        "rounds": [round_a, round_b],
    }
    manifest = _manifest()
    manifest["schedule"].append(
        {
            "date": "2026-07-24",  # gap: should be 2026-07-23
            "round_id": round_b["id"],
            "round_fingerprint": round_content_fingerprint(round_b),
        }
    )
    failures = connection_daily_manifest_failures(manifest, rounds_artifact)
    assert any("gap or disorder" in f for f in failures)


def test_rejects_duplicate_round_id_in_schedule() -> None:
    manifest = _manifest()
    entry = dict(manifest["schedule"][0])
    entry["date"] = "2026-07-23"
    manifest["schedule"].append(entry)
    failures = connection_daily_manifest_failures(manifest, _rounds_artifact())
    assert any("is scheduled more than once" in f for f in failures)


def test_rejects_stale_fingerprint() -> None:
    manifest = _manifest()
    manifest["schedule"][0]["round_fingerprint"] = "rfp-0000000000000000"
    failures = connection_daily_manifest_failures(manifest, _rounds_artifact())
    assert any("fingerprint mismatch" in f for f in failures)


def test_rejects_round_not_in_pool() -> None:
    manifest = _manifest()
    manifest["schedule"][0]["round_id"] = "conn-9999999999"
    failures = connection_daily_manifest_failures(manifest, _rounds_artifact())
    assert any("is not in the published pool" in f for f in failures)


def test_rejects_two_hop_round_scheduled() -> None:
    two_hop = _round("conn-0000000003")
    two_hop["kind"] = "two_hop"
    rounds_artifact = {
        "schema_version": 1,
        "provenance": dict(_PROVENANCE),
        "rounds": [two_hop],
    }
    manifest = _manifest()
    manifest["schedule"][0]["round_id"] = two_hop["id"]
    manifest["schedule"][0]["round_fingerprint"] = round_content_fingerprint(two_hop)
    failures = connection_daily_manifest_failures(manifest, rounds_artifact)
    assert any("is not a real one-hop round" in f for f in failures)


def test_rejects_seed_key() -> None:
    manifest = _manifest()
    manifest["schedule"][0]["seed"] = "leak"
    failures = connection_daily_manifest_failures(manifest, _rounds_artifact())
    assert any("must not have a 'seed' key" in f for f in failures)


def test_rejects_forbidden_substring() -> None:
    manifest = _manifest()
    manifest["catalog_version"] = "/home/leak"
    failures = connection_daily_manifest_failures(manifest, _rounds_artifact())
    assert any("forbidden substring" in f for f in failures)


def test_cross_check_agrees_with_graph_core_reference() -> None:
    from networked_players_graph_core.connection_daily_manifest import (
        ConnectionDailyManifestError,
        validate_connection_daily_manifest,
    )

    manifest = _manifest()
    rounds_artifact = _rounds_artifact()
    validate_connection_daily_manifest(deepcopy(manifest), deepcopy(rounds_artifact))
    assert connection_daily_manifest_failures(manifest, rounds_artifact) == []

    broken = _manifest()
    broken["mode"] = "record_routes"
    try:
        validate_connection_daily_manifest(deepcopy(broken), deepcopy(rounds_artifact))
        raised = False
    except ConnectionDailyManifestError:
        raised = True
    assert raised
    assert connection_daily_manifest_failures(broken, rounds_artifact) != []
