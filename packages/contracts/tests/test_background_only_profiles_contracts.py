from __future__ import annotations

from copy import deepcopy
from typing import Any

from networked_players_contracts.background_only_profiles import (
    background_only_profiles_failures,
    background_only_profiles_version,
)
from networked_players_contracts.catalog import _catalog_version

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


def _contributor_index() -> dict[str, Any]:
    return {"contributors": [{"artist_id": 100}, {"artist_id": 200}]}


def _artist_ids() -> list[int]:
    return [100, 200]


def _artifact() -> dict[str, Any]:
    catalog = _catalog()
    artist_ids = _artist_ids()
    return {
        "schema_version": 1,
        "catalog_version": catalog["catalog_version"],
        "background_only_profiles_version": background_only_profiles_version(artist_ids, _SNAPSHOT),
        "generated_at": "2026-08-31T00:00:00+00:00",
        "source": "Derived from challenge.v2.json and routes/rounds.v1.json.",
        "license": "See docs/DATA_AND_RIGHTS.md.",
        "artist_ids": artist_ids,
    }


def test_clean_artifact_has_no_failures() -> None:
    assert background_only_profiles_failures(_artifact(), _catalog(), _contributor_index()) == []


def test_wrong_top_level_type_fails() -> None:
    assert background_only_profiles_failures("not a dict", _catalog(), _contributor_index()) != []
    assert background_only_profiles_failures(_artifact(), "not a dict", _contributor_index()) != []
    assert background_only_profiles_failures(_artifact(), _catalog(), "not a dict") != []


def test_mismatched_catalog_version_is_caught() -> None:
    artifact = deepcopy(_artifact())
    artifact["catalog_version"] = "catalog-v1-wrong"
    failures = background_only_profiles_failures(artifact, _catalog(), _contributor_index())
    assert any("catalog_version" in f for f in failures)


def test_stale_version_is_caught() -> None:
    artifact = deepcopy(_artifact())
    artifact["background_only_profiles_version"] = (
        "background-only-profiles-v1-20260601-" + "0" * 12
    )
    failures = background_only_profiles_failures(artifact, _catalog(), _contributor_index())
    assert any("background_only_profiles_version" in f for f in failures)


def test_artist_not_a_published_contributor_is_rejected() -> None:
    artifact = deepcopy(_artifact())
    artifact["artist_ids"] = [999999]
    artifact["background_only_profiles_version"] = background_only_profiles_version(
        artifact["artist_ids"], _SNAPSHOT
    )
    failures = background_only_profiles_failures(artifact, _catalog(), _contributor_index())
    assert any("not a published contributor" in f for f in failures)


def test_non_integer_artist_id_is_reported_not_crashed() -> None:
    """A real gap caught in review for the sibling album-hop-distances
    contract: malformed JSON can supply a list or dict where an int is
    expected, which raises TypeError from a naive set operation instead of
    returning a clean contract failure."""
    artifact = deepcopy(_artifact())
    artifact["artist_ids"] = [["not", "an", "int"]]
    failures = background_only_profiles_failures(artifact, _catalog(), _contributor_index())
    assert any("must be an integer" in f for f in failures)


def test_out_of_order_artist_ids_are_rejected() -> None:
    artifact = deepcopy(_artifact())
    artifact["artist_ids"] = list(reversed(artifact["artist_ids"]))
    failures = background_only_profiles_failures(artifact, _catalog(), _contributor_index())
    assert any("sorted" in f for f in failures)


def test_duplicate_artist_id_is_rejected() -> None:
    artifact = deepcopy(_artifact())
    artifact["artist_ids"] = [100, 100]
    artifact["background_only_profiles_version"] = background_only_profiles_version(
        artifact["artist_ids"], _SNAPSHOT
    )
    failures = background_only_profiles_failures(artifact, _catalog(), _contributor_index())
    assert any("must not repeat" in f for f in failures)


def test_empty_artist_ids_list_is_valid() -> None:
    catalog = _catalog()
    artifact = {
        "schema_version": 1,
        "catalog_version": catalog["catalog_version"],
        "background_only_profiles_version": background_only_profiles_version([], _SNAPSHOT),
        "generated_at": "2026-08-31T00:00:00+00:00",
        "source": "Derived from challenge.v2.json and routes/rounds.v1.json.",
        "license": "See docs/DATA_AND_RIGHTS.md.",
        "artist_ids": [],
    }
    assert background_only_profiles_failures(artifact, catalog, _contributor_index()) == []
