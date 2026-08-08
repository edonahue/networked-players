from __future__ import annotations

from copy import deepcopy
from typing import Any

from networked_players_contracts.catalog import _catalog_version
from networked_players_contracts.evidence_release_registry import (
    evidence_release_registry_failures,
    evidence_release_registry_version,
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
        }
    ]
    return {
        "catalog_version": _catalog_version(albums, _SNAPSHOT),
        "snapshot_date": _SNAPSHOT,
        "generated_by": "networked-players-catalog build-album-catalog 0.1.0",
        "albums": albums,
    }


def _base_fields() -> dict[str, Any]:
    return {
        "release_ids": [1, 2],
        "titles": ["First Light", "Other Release"],
        "years": [1995, None],
        "countries": ["US", None],
        "master_ids": [1, None],
        "source_urls": ["https://data.discogs.com/?download=fake"] * 2,
        "cover_uri150s": ["https://i.discogs.com/thumb.jpg", None],
        "relation_to_catalog_album_ids": ["master-1", None],
    }


def _registry() -> dict[str, Any]:
    catalog = _catalog()
    fields = _base_fields()
    registry = {
        "schema_version": 1,
        "catalog_version": catalog["catalog_version"],
        "generated_at": "2026-08-07T00:00:00+00:00",
        "source": "Union of challenge/routes/pathfinding-graph release ids.",
        "license": "See docs/DATA_AND_RIGHTS.md.",
        **fields,
    }
    registry["evidence_release_registry_version"] = evidence_release_registry_version(
        registry, _SNAPSHOT
    )
    return registry


def test_clean_registry_has_no_failures() -> None:
    assert evidence_release_registry_failures(_registry(), _catalog()) == []


def test_wrong_top_level_type_fails() -> None:
    assert evidence_release_registry_failures("not a dict", _catalog()) != []
    assert evidence_release_registry_failures(_registry(), "not a dict") != []


def test_mismatched_catalog_version_is_caught() -> None:
    registry = deepcopy(_registry())
    registry["catalog_version"] = "catalog-v1-wrong"
    failures = evidence_release_registry_failures(registry, _catalog())
    assert any("catalog_version" in f for f in failures)


def test_stale_version_is_caught() -> None:
    registry = deepcopy(_registry())
    registry["evidence_release_registry_version"] = (
        "evidence-release-registry-v1-20260601-" + "0" * 12
    )
    failures = evidence_release_registry_failures(registry, _catalog())
    assert any("evidence_release_registry_version" in f for f in failures)


def test_unsorted_release_ids_is_rejected() -> None:
    registry = deepcopy(_registry())
    registry["release_ids"] = [2, 1]
    failures = evidence_release_registry_failures(registry, _catalog())
    assert any("sorted and deduplicated" in f for f in failures)


def test_mismatched_array_length_is_rejected() -> None:
    registry = deepcopy(_registry())
    registry["titles"] = ["Only One"]
    failures = evidence_release_registry_failures(registry, _catalog())
    assert any("titles has length" in f for f in failures)


def test_implausible_year_is_rejected() -> None:
    registry = deepcopy(_registry())
    registry["years"] = [3000, None]
    failures = evidence_release_registry_failures(registry, _catalog())
    assert any("plausible release-year range" in f for f in failures)


def test_non_https_source_url_is_rejected() -> None:
    registry = deepcopy(_registry())
    registry["source_urls"] = ["ftp://example.invalid", "https://data.discogs.com/?download=fake"]
    failures = evidence_release_registry_failures(registry, _catalog())
    assert any("source_urls[0]" in f for f in failures)


def test_cover_art_not_hotlinking_approved_host_is_rejected() -> None:
    registry = deepcopy(_registry())
    registry["cover_uri150s"] = ["https://evil.example/rehosted.jpg", None]
    failures = evidence_release_registry_failures(registry, _catalog())
    assert any("cover_uri150s[0]" in f for f in failures)


def test_relation_to_unknown_catalog_album_is_rejected() -> None:
    registry = deepcopy(_registry())
    registry["relation_to_catalog_album_ids"] = ["master-999", None]
    failures = evidence_release_registry_failures(registry, _catalog())
    assert any("relation_to_catalog_album_ids[0]" in f for f in failures)


def test_empty_registry_is_valid() -> None:
    catalog = _catalog()
    registry = {
        "schema_version": 1,
        "catalog_version": catalog["catalog_version"],
        "generated_at": "2026-08-07T00:00:00+00:00",
        "source": "Union of challenge/routes/pathfinding-graph release ids.",
        "license": "See docs/DATA_AND_RIGHTS.md.",
        "release_ids": [],
        "titles": [],
        "years": [],
        "countries": [],
        "master_ids": [],
        "source_urls": [],
        "cover_uri150s": [],
        "relation_to_catalog_album_ids": [],
    }
    registry["evidence_release_registry_version"] = evidence_release_registry_version(
        registry, _SNAPSHOT
    )
    assert evidence_release_registry_failures(registry, catalog) == []
