from __future__ import annotations

from copy import deepcopy
from typing import Any

from networked_players_contracts.album_hop_distances import (
    album_hop_distances_failures,
    album_hop_distances_version,
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


def _entries() -> list[dict[str, Any]]:
    return [
        {"artist_id": 100, "album_id": "master-1", "hop_distance": 0},
        {"artist_id": 100, "album_id": "master-2", "hop_distance": 2},
        {"artist_id": 200, "album_id": "master-2", "hop_distance": 0},
    ]


def _artifact() -> dict[str, Any]:
    catalog = _catalog()
    entries = _entries()
    return {
        "schema_version": 1,
        "catalog_version": catalog["catalog_version"],
        "album_hop_distances_version": album_hop_distances_version(entries, _SNAPSHOT),
        "generated_at": "2026-08-03T00:00:00+00:00",
        "source": "Derived from challenge.v3.json and routes/rounds.v1.json.",
        "license": "See docs/DATA_AND_RIGHTS.md.",
        "entries": entries,
    }


def test_clean_artifact_has_no_failures() -> None:
    assert album_hop_distances_failures(_artifact(), _catalog(), _contributor_index()) == []


def test_wrong_top_level_type_fails() -> None:
    assert album_hop_distances_failures("not a dict", _catalog(), _contributor_index()) != []
    assert album_hop_distances_failures(_artifact(), "not a dict", _contributor_index()) != []
    assert album_hop_distances_failures(_artifact(), _catalog(), "not a dict") != []


def test_mismatched_catalog_version_is_caught() -> None:
    artifact = deepcopy(_artifact())
    artifact["catalog_version"] = "catalog-v1-wrong"
    failures = album_hop_distances_failures(artifact, _catalog(), _contributor_index())
    assert any("catalog_version" in f for f in failures)


def test_stale_version_is_caught() -> None:
    artifact = deepcopy(_artifact())
    artifact["album_hop_distances_version"] = "album-hop-distances-v1-20260601-" + "0" * 12
    failures = album_hop_distances_failures(artifact, _catalog(), _contributor_index())
    assert any("album_hop_distances_version" in f for f in failures)


def test_album_not_in_catalog_is_rejected() -> None:
    artifact = deepcopy(_artifact())
    artifact["entries"][0]["album_id"] = "master-999"
    failures = album_hop_distances_failures(artifact, _catalog(), _contributor_index())
    assert any("not in the canonical catalog" in f for f in failures)


def test_artist_not_a_published_contributor_is_rejected() -> None:
    artifact = deepcopy(_artifact())
    artifact["entries"][0]["artist_id"] = 999999
    failures = album_hop_distances_failures(artifact, _catalog(), _contributor_index())
    assert any("not a published contributor" in f for f in failures)


def test_negative_hop_distance_is_rejected() -> None:
    artifact = deepcopy(_artifact())
    artifact["entries"][0]["hop_distance"] = -1
    failures = album_hop_distances_failures(artifact, _catalog(), _contributor_index())
    assert any("hop_distance must be a non-negative integer" in f for f in failures)


def test_entry_missing_a_key_is_rejected() -> None:
    artifact = deepcopy(_artifact())
    del artifact["entries"][0]["hop_distance"]
    failures = album_hop_distances_failures(artifact, _catalog(), _contributor_index())
    assert any("must have keys" in f for f in failures)


def test_out_of_order_entries_are_rejected() -> None:
    artifact = deepcopy(_artifact())
    artifact["entries"] = list(reversed(artifact["entries"]))
    failures = album_hop_distances_failures(artifact, _catalog(), _contributor_index())
    assert any("must be sorted by" in f for f in failures)


def test_duplicate_artist_album_pair_is_rejected() -> None:
    """A real gap caught in review: a naive set-based id-membership check
    can pass even when the same (artist_id, album_id) pair is repeated with
    conflicting hop_distance values, as long as the repeated entries happen
    to already be in ascending sort order."""
    artifact = deepcopy(_artifact())
    artifact["entries"] = [
        {"artist_id": 100, "album_id": "master-1", "hop_distance": 0},
        {"artist_id": 100, "album_id": "master-1", "hop_distance": 5},
    ]
    artifact["album_hop_distances_version"] = album_hop_distances_version(
        artifact["entries"], _SNAPSHOT
    )
    failures = album_hop_distances_failures(artifact, _catalog(), _contributor_index())
    assert any("must not repeat the same" in f for f in failures)


def test_non_string_album_id_is_reported_not_crashed() -> None:
    """A real gap caught in review: malformed JSON can supply a list or
    dict as album_id, which raises TypeError from a naive `set.add`/`in`
    check instead of returning a clean contract failure."""
    artifact = deepcopy(_artifact())
    artifact["entries"][0]["album_id"] = ["not", "a", "string"]
    failures = album_hop_distances_failures(artifact, _catalog(), _contributor_index())
    assert any("album_id must be a non-empty string" in f for f in failures)


def test_empty_entries_list_is_valid() -> None:
    catalog = _catalog()
    artifact = {
        "schema_version": 1,
        "catalog_version": catalog["catalog_version"],
        "album_hop_distances_version": album_hop_distances_version([], _SNAPSHOT),
        "generated_at": "2026-08-03T00:00:00+00:00",
        "source": "Derived from challenge.v3.json and routes/rounds.v1.json.",
        "license": "See docs/DATA_AND_RIGHTS.md.",
        "entries": [],
    }
    assert album_hop_distances_failures(artifact, catalog, _contributor_index()) == []
