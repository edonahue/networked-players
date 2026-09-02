from __future__ import annotations

from copy import deepcopy
from typing import Any

from networked_players_contracts.catalog import _catalog_version
from networked_players_contracts.contributor_index import (
    contributor_index_failures,
    contributor_index_version,
)

_SNAPSHOT = "20260601"


def _catalog() -> dict[str, Any]:
    albums = [
        {
            "id": "master-1",
            "master_id": None,
            "main_release_id": 1,
            "title": "First Light",
            "artist_id": 100,
            "artist": "Alice",
            "year": 1995,
        },
        {
            "id": "master-2",
            "master_id": None,
            "main_release_id": 2,
            "title": "Second Wave",
            "artist_id": 200,
            "artist": "Bob",
            "year": 1998,
        },
    ]
    return {
        "catalog_version": _catalog_version(albums, _SNAPSHOT),
        "snapshot_date": _SNAPSHOT,
        "generated_by": "networked-players-catalog build-album-catalog 0.1.0",
        "albums": albums,
    }


def _contributors() -> list[dict[str, Any]]:
    return [
        {
            "artist_id": 100,
            "name": "Alice",
            "role_categories": ["strings"],
            "role_text_examples": ["Guitar"],
            "albums": ["master-1", "master-2"],
            "decade_activity": [1990],
            "connection_count": 1,
            "neighboring_contributor_ids": [200],
            "evidence": [{"release_id": 1, "role_text": "Guitar"}],
            "interesting_next_step": None,
        },
        {
            "artist_id": 200,
            "name": "Bob",
            "role_categories": ["strings"],
            "role_text_examples": ["Bass"],
            "albums": ["master-1", "master-2"],
            "decade_activity": [1990],
            "connection_count": 1,
            "neighboring_contributor_ids": [100],
            "evidence": [{"release_id": 1, "role_text": "Bass"}],
            "interesting_next_step": None,
        },
    ]


def _index() -> dict[str, Any]:
    catalog = _catalog()
    contributors = _contributors()
    return {
        "schema_version": 1,
        "catalog_version": catalog["catalog_version"],
        "contributor_index_version": contributor_index_version(contributors, _SNAPSHOT),
        "generated_at": "2026-08-03T00:00:00+00:00",
        "source": "Derived from challenge.v3.json and routes artifacts.",
        "license": "See docs/DATA_AND_RIGHTS.md.",
        "contributors": contributors,
    }


def test_clean_index_has_no_failures() -> None:
    assert contributor_index_failures(_index(), _catalog()) == []


def test_wrong_top_level_type_fails() -> None:
    assert contributor_index_failures("not a dict", _catalog()) != []
    assert contributor_index_failures(_index(), "not a dict") != []


def test_mismatched_catalog_version_is_caught() -> None:
    index = deepcopy(_index())
    index["catalog_version"] = "catalog-v1-wrong"
    failures = contributor_index_failures(index, _catalog())
    assert any("catalog_version" in f for f in failures)


def test_stale_contributor_index_version_is_caught() -> None:
    index = deepcopy(_index())
    index["contributor_index_version"] = "contributor-index-v1-20260601-" + "0" * 12
    failures = contributor_index_failures(index, _catalog())
    assert any("contributor_index_version" in f for f in failures)


def test_unknown_role_category_is_rejected() -> None:
    index = deepcopy(_index())
    index["contributors"][0]["role_categories"] = ["not_a_real_category"]
    failures = contributor_index_failures(index, _catalog())
    assert any("unknown category" in f for f in failures)


def test_album_not_in_catalog_is_rejected() -> None:
    index = deepcopy(_index())
    index["contributors"][0]["albums"] = ["master-999"]
    failures = contributor_index_failures(index, _catalog())
    assert any("not in the canonical catalog" in f for f in failures)


def test_neighbor_id_not_in_this_index_is_rejected() -> None:
    index = deepcopy(_index())
    index["contributors"][0]["neighboring_contributor_ids"] = [999999]
    failures = contributor_index_failures(index, _catalog())
    assert any("not a published contributor" in f for f in failures)


def test_duplicate_artist_id_is_rejected() -> None:
    index = deepcopy(_index())
    index["contributors"].append(deepcopy(index["contributors"][0]))
    # Recompute is skipped on purpose -- the duplicate itself is the defect
    # under test, independent of whether the version string still matches.
    failures = contributor_index_failures(index, _catalog())
    assert any("duplicate artist_id" in f for f in failures)


def test_empty_contributors_list_is_valid() -> None:
    catalog = _catalog()
    index = {
        "schema_version": 1,
        "catalog_version": catalog["catalog_version"],
        "contributor_index_version": contributor_index_version([], _SNAPSHOT),
        "generated_at": "2026-08-03T00:00:00+00:00",
        "source": "Derived from challenge.v3.json and routes artifacts.",
        "license": "See docs/DATA_AND_RIGHTS.md.",
        "contributors": [],
    }
    assert contributor_index_failures(index, catalog) == []


def test_missing_interesting_next_step_is_rejected() -> None:
    index = deepcopy(_index())
    del index["contributors"][0]["interesting_next_step"]
    failures = contributor_index_failures(index, _catalog())
    assert any("missing interesting_next_step" in f for f in failures)


def test_interesting_next_step_null_is_valid() -> None:
    index = deepcopy(_index())
    index["contributors"][0]["interesting_next_step"] = None
    assert contributor_index_failures(index, _catalog()) == []


def test_interesting_next_step_with_extra_key_is_rejected() -> None:
    index = deepcopy(_index())
    index["contributors"][0]["interesting_next_step"] = {
        "artist_id": 200,
        "reason": "credited in a different kind of role than this contributor",
        "score": 0.9,
    }
    failures = contributor_index_failures(index, _catalog())
    assert any("interesting_next_step must be null or have keys" in f for f in failures)


def test_interesting_next_step_artist_id_must_be_a_published_contributor() -> None:
    index = deepcopy(_index())
    index["contributors"][0]["interesting_next_step"] = {
        "artist_id": 999999,
        "reason": "credited in a different kind of role than this contributor",
    }
    failures = contributor_index_failures(index, _catalog())
    assert any(
        "interesting_next_step artist_id 999999" in f and "not a published contributor" in f
        for f in failures
    )


def test_interesting_next_step_artist_id_must_be_a_real_neighbor() -> None:
    # 200 IS a published contributor in this fixture, but not one of Alice's
    # own neighboring_contributor_ids in this deliberately doctored case.
    index = deepcopy(_index())
    index["contributors"][0]["neighboring_contributor_ids"] = []
    index["contributors"][0]["interesting_next_step"] = {
        "artist_id": 200,
        "reason": "credited in a different kind of role than this contributor",
    }
    failures = contributor_index_failures(index, _catalog())
    assert any(
        "not one of this contributor's own neighboring_contributor_ids" in f for f in failures
    )


def test_interesting_next_step_reason_must_be_a_non_empty_string() -> None:
    index = deepcopy(_index())
    index["contributors"][0]["interesting_next_step"] = {"artist_id": 200, "reason": ""}
    failures = contributor_index_failures(index, _catalog())
    assert any("reason must be a non-empty string" in f for f in failures)


def test_forbidden_inference_phrase_is_rejected() -> None:
    index = deepcopy(_index())
    index["source"] = "Alice collaborated with Bob on this record."
    failures = contributor_index_failures(index, _catalog())
    assert any("forbidden inference-implying phrase" in f for f in failures)
