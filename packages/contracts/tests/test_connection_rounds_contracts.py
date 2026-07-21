from __future__ import annotations

from copy import deepcopy
from typing import Any

from networked_players_contracts import connection_rounds_failures

_PROVENANCE = {
    "source": "Discogs monthly data dump (CC0), one-hop working set",
    "license": "See docs/DATA_AND_RIGHTS.md.",
    "snapshot_date": "20260601",
    "generated_by": "networked-players-catalog build-connection-rounds 0.1.0",
    "catalog_version": "catalog-v1-20260601-abc123abc123",
    "pool_version": "connection-v1-20260601-def456def456",
    "note": "Real records, not synthetic.",
}


def _universe() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "provenance": _PROVENANCE,
        "albums": [
            {
                "id": "album-a",
                "title": "First Light",
                "act": "Alice",
                "act_id": 100,
                "year": 1995,
                "label": None,
                "art": None,
            },
            {
                "id": "album-c",
                "title": "Third Wave",
                "act": "Cara",
                "act_id": 300,
                "year": 1996,
                "label": None,
                "art": None,
            },
        ],
        "contributors": [
            {"id": 700, "name": "Xavier", "role_category": "guitar"},
            {"id": 750, "name": "Walt", "role_category": "drums"},
        ],
        "releases": [
            {
                "id": "album-a",
                "album_id": "album-a",
                "title": "First Light",
                "year": 1995,
                "catalog_stamp": "DISCOGS-1",
            },
            {
                "id": "album-c",
                "album_id": "album-c",
                "title": "Third Wave",
                "year": 1996,
                "catalog_stamp": "DISCOGS-2",
            },
        ],
        "credits": [
            {
                "release_id": "album-a",
                "contributor_id": 700,
                "role_text": "Guitar",
                "role_category": "guitar",
                "credit_scope": "release_credit",
            },
            {
                "release_id": "album-c",
                "contributor_id": 700,
                "role_text": "Guitar",
                "role_category": "guitar",
                "credit_scope": "release_credit",
            },
        ],
    }


def _round() -> dict[str, Any]:
    return {
        "id": "conn-0123456789",
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
        "distractors": [{"id": 750, "name": "Walt", "role_category": "drums"}],
        "clues": [
            {
                "kind": "eliminate",
                "text": "One name struck from the tray.",
                "eliminate_ids": [750],
            }
        ],
        "evidence": [
            {
                "release_ref": "album-a",
                "release_title": "First Light",
                "contributor_id": 700,
                "credited_as": "Xavier",
                "role_text": "Guitar",
                "credit_scope": "release_credit",
            },
            {
                "release_ref": "album-c",
                "release_title": "Third Wave",
                "contributor_id": 700,
                "credited_as": "Xavier",
                "role_text": "Guitar",
                "credit_scope": "release_credit",
            },
        ],
        "provenance_note": "Real records: derived from the Discogs monthly data dump (CC0).",
    }


def _rounds() -> dict[str, Any]:
    return {"schema_version": 1, "provenance": _PROVENANCE, "rounds": [_round()]}


def test_valid_pair_has_no_failures() -> None:
    assert connection_rounds_failures(_universe(), _rounds()) == []


def test_rejects_wrong_pool_label() -> None:
    rounds = _rounds()
    rounds["rounds"][0]["pool"] = "synthetic-universe"
    failures = connection_rounds_failures(_universe(), rounds)
    assert any("real-records" in f for f in failures)


def test_rejects_unstable_round_id() -> None:
    rounds = _rounds()
    rounds["rounds"][0]["id"] = "conn-000001"
    failures = connection_rounds_failures(_universe(), rounds)
    assert any("not a stable content-derived id" in f for f in failures)


def test_rejects_distractor_that_is_also_an_answer() -> None:
    rounds = _rounds()
    rounds["rounds"][0]["distractors"] = [{"id": 700, "name": "Xavier", "role_category": "guitar"}]
    failures = connection_rounds_failures(_universe(), rounds)
    assert any("is an answer" in f for f in failures)


def test_rejects_eliminate_clue_targeting_a_valid_answer() -> None:
    rounds = _rounds()
    rounds["rounds"][0]["clues"][0]["eliminate_ids"] = [700]
    failures = connection_rounds_failures(_universe(), rounds)
    assert any("targets valid answer" in f for f in failures)


def test_rejects_answer_without_evidence() -> None:
    rounds = _rounds()
    rounds["rounds"][0]["evidence"] = []
    failures = connection_rounds_failures(_universe(), rounds)
    assert any("lacks evidence" in f for f in failures)


def test_rejects_missing_catalog_version() -> None:
    universe = deepcopy(_universe())
    universe["provenance"] = dict(universe["provenance"])
    universe["provenance"].pop("catalog_version")
    failures = connection_rounds_failures(universe, _rounds())
    assert any("catalog_version" in f for f in failures)


def test_rejects_nested_seed_key() -> None:
    universe = deepcopy(_universe())
    universe["albums"][0]["seed"] = "leaked"
    failures = connection_rounds_failures(universe, _rounds())
    assert any("'seed' key" in f for f in failures)


def test_rejects_forbidden_substring() -> None:
    universe = deepcopy(_universe())
    universe["provenance"] = dict(universe["provenance"])
    universe["provenance"]["note"] += " see /home/erich/notes"
    failures = connection_rounds_failures(universe, _rounds())
    assert any("forbidden substring" in f for f in failures)


def test_rejects_synthetic_generated_by() -> None:
    universe = deepcopy(_universe())
    universe["provenance"] = dict(universe["provenance"])
    universe["provenance"]["generated_by"] = "build-rounds.mjs synthetic-fixture"
    failures = connection_rounds_failures(universe, _rounds())
    assert any("synthetic fixture" in f for f in failures)


def test_rejects_duplicate_round_ids() -> None:
    rounds = _rounds()
    rounds["rounds"].append(deepcopy(rounds["rounds"][0]))
    failures = connection_rounds_failures(_universe(), rounds)
    assert any("duplicate round id" in f for f in failures)
