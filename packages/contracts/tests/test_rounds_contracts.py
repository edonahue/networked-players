from __future__ import annotations

from copy import deepcopy
from typing import Any

from networked_players_contracts import rounds_failures


def _hop() -> dict[str, Any]:
    return {
        "release_id": 1,
        "artist_a_id": 100,
        "artist_b_id": 200,
        "role_a": "Vocals",
        "role_b": "Guitar",
        "quality_flags": ["performer_credit", "same_recording"],
    }


def _universe() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "pool_version": "rounds-v1-20260719",
        "provenance": {
            "source": "Discogs monthly data dump (CC0), one-hop working set",
            "license": "See docs/DATA_AND_RIGHTS.md.",
            "snapshot_date": "20260601",
            "generated_by": "networked-players-catalog build-rounds-from-dump 0.1.0",
            "graph_core_version": "0.1.0",
            "note": "Real evidence, performer-only.",
        },
        "counts": {"one_hop": 1, "two_hop": 0, "daily_eligible": 1},
        "albums": [
            {
                "id": "release-1",
                "master_id": None,
                "main_release_id": 1,
                "title": "First Light",
                "artist_id": 100,
                "artist": "Alice",
                "year": 1995,
                "cover_image": None,
            },
            {
                "id": "release-2",
                "master_id": None,
                "main_release_id": 2,
                "title": "Second Set",
                "artist_id": 200,
                "artist": "Bob",
                "year": 1995,
                "cover_image": None,
            },
        ],
    }


def _rounds() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "pool_version": "rounds-v1-20260719",
        "provenance": _universe()["provenance"],
        "rounds": [
            {
                "id": "round-000001",
                "kind": "one_hop",
                "difficulty": "easy",
                "from_album_id": "release-1",
                "to_album_id": "release-2",
                "from_artist_id": 100,
                "to_artist_id": 200,
                "hops": [_hop()],
                "distractors": [],
            }
        ],
        "releases": [
            {
                "snapshot_date": "20260601",
                "release_id": 1,
                "status": "Accepted",
                "title": "First Light",
                "country": None,
                "released": "1995",
                "master_id": None,
                "master_is_main_release": None,
                "data_quality": None,
                "source_url": "https://example.invalid/release/1",
                "credits": [],
            }
        ],
        "artists": [
            {"artist_id": 100, "name": "Alice"},
            {"artist_id": 200, "name": "Bob"},
        ],
    }


def test_valid_pair_has_no_failures() -> None:
    assert rounds_failures(_universe(), _rounds()) == []


def test_pool_version_mismatch_is_flagged() -> None:
    universe = _universe()
    universe["pool_version"] = "rounds-v1-other"
    failures = rounds_failures(universe, _rounds())
    assert any("pool_version must match" in f for f in failures)


def test_missing_strength_flag_is_flagged() -> None:
    rounds = _rounds()
    rounds["rounds"][0]["hops"][0]["quality_flags"] = ["same_recording"]
    failures = rounds_failures(_universe(), rounds)
    assert any("exactly one strength flag" in f for f in failures)


def test_missing_scope_flag_is_flagged() -> None:
    rounds = _rounds()
    rounds["rounds"][0]["hops"][0]["quality_flags"] = ["performer_credit"]
    failures = rounds_failures(_universe(), rounds)
    assert any("exactly one scope flag" in f for f in failures)


def test_missing_role_is_flagged() -> None:
    rounds = _rounds()
    rounds["rounds"][0]["hops"][0]["role_b"] = None
    failures = rounds_failures(_universe(), rounds)
    assert any("missing role_a/role_b" in f for f in failures)


def test_kind_hop_count_mismatch_is_flagged() -> None:
    rounds = _rounds()
    rounds["rounds"][0]["kind"] = "two_hop"
    failures = rounds_failures(_universe(), rounds)
    assert any("must have hops matching its kind" in f for f in failures)


def test_dangling_album_reference_is_flagged() -> None:
    rounds = _rounds()
    rounds["rounds"][0]["from_album_id"] = "release-999"
    failures = rounds_failures(_universe(), rounds)
    assert any("unpublished album" in f for f in failures)


def test_dangling_release_reference_is_flagged() -> None:
    rounds = _rounds()
    rounds["rounds"][0]["hops"][0]["release_id"] = 999
    failures = rounds_failures(_universe(), rounds)
    assert any("unpublished release" in f for f in failures)


def test_duplicate_round_id_is_flagged() -> None:
    rounds = _rounds()
    rounds["rounds"].append(deepcopy(rounds["rounds"][0]))
    failures = rounds_failures(_universe(), rounds)
    assert any("duplicate round id" in f for f in failures)


def test_forbidden_substring_is_flagged() -> None:
    universe = _universe()
    universe["provenance"]["note"] = "see /home/erich/notes"
    failures = rounds_failures(universe, _rounds())
    assert any("forbidden substring" in f for f in failures)


def test_forbidden_phrase_is_flagged() -> None:
    universe = _universe()
    universe["provenance"]["note"] = "Alice worked with Bob"
    failures = rounds_failures(universe, _rounds())
    assert any("forbidden phrase" in f for f in failures)


def test_unexpected_top_level_key_is_flagged() -> None:
    universe = _universe()
    universe["extra"] = True
    failures = rounds_failures(universe, _rounds())
    assert any("unexpected top-level keys" in f for f in failures)


def test_nested_seed_key_is_flagged() -> None:
    # A leaked pseudo-random seed nested below the top level must be rejected too,
    # matching graph-core's generation-time validator (the gap this closes).
    rounds = _rounds()
    rounds["provenance"]["seed"] = "flagship-42"
    failures = rounds_failures(_universe(), rounds)
    assert any("must not have a 'seed' key" in f and "provenance.seed" in f for f in failures)


def test_deeply_nested_seed_key_in_list_is_flagged() -> None:
    universe = _universe()
    universe["albums"][0]["seed"] = 7  # inside a list element, one level deeper
    failures = rounds_failures(universe, _rounds())
    assert any("must not have a 'seed' key" in f for f in failures)
