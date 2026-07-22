from __future__ import annotations

from copy import deepcopy
from typing import Any

from networked_players_contracts.catalog import _catalog_version, public_album_catalog_failures

_SNAPSHOT_DATE = "20260601"


def _album(album_id: str, *, artist_id: int, main_release_id: int) -> dict[str, Any]:
    return {
        "id": album_id,
        "master_id": None,
        "main_release_id": main_release_id,
        "title": album_id.title(),
        "artist_id": artist_id,
        "artist": "Alice",
        "year": 1995,
    }


def _catalog() -> dict[str, Any]:
    albums = [
        _album("master-1", artist_id=100, main_release_id=1),
        _album("master-2", artist_id=200, main_release_id=2),
    ]
    return {
        "catalog_version": _catalog_version(albums, _SNAPSHOT_DATE),
        "snapshot_date": _SNAPSHOT_DATE,
        "generated_by": "networked-players-catalog build-album-catalog 0.1.0",
        "albums": albums,
    }


def test_valid_catalog_has_no_failures() -> None:
    assert public_album_catalog_failures(_catalog()) == []


def test_rejects_non_object_input() -> None:
    assert public_album_catalog_failures([]) == ["catalog artifact must be an object"]


def test_rejects_missing_catalog_version() -> None:
    catalog = _catalog()
    del catalog["catalog_version"]
    failures = public_album_catalog_failures(catalog)
    assert any("catalog_version is required" in f for f in failures)


def test_rejects_missing_snapshot_date() -> None:
    catalog = _catalog()
    del catalog["snapshot_date"]
    failures = public_album_catalog_failures(catalog)
    assert any("snapshot_date is required" in f for f in failures)


def test_rejects_empty_albums() -> None:
    catalog = _catalog()
    catalog["albums"] = []
    failures = public_album_catalog_failures(catalog)
    assert any("albums must not be empty" in f for f in failures)


def test_rejects_duplicate_album_id() -> None:
    catalog = _catalog()
    catalog["albums"].append(deepcopy(catalog["albums"][0]))
    failures = public_album_catalog_failures(catalog)
    assert any("duplicate album id" in f for f in failures)


def test_rejects_missing_required_field() -> None:
    catalog = _catalog()
    del catalog["albums"][0]["artist"]
    failures = public_album_catalog_failures(catalog)
    assert any("missing required field 'artist'" in f for f in failures)


def test_rejects_invalid_main_release_id() -> None:
    catalog = _catalog()
    catalog["albums"][0]["main_release_id"] = -1
    failures = public_album_catalog_failures(catalog)
    assert any("invalid main_release_id" in f for f in failures)


def test_rejects_tampered_catalog_version() -> None:
    catalog = _catalog()
    catalog["catalog_version"] = "catalog-v1-20260601-000000000000"
    failures = public_album_catalog_failures(catalog)
    assert any("does not match its own content" in f for f in failures)


def test_rejects_forbidden_substring() -> None:
    catalog = _catalog()
    catalog["generated_by"] = "/home/leak"
    failures = public_album_catalog_failures(catalog)
    assert any("forbidden substring" in f for f in failures)


def test_cross_check_agrees_with_graph_core_reference() -> None:
    from networked_players_graph_core.analysis import (
        AlbumCatalogValidationError,
        validate_album_catalog,
    )

    catalog = _catalog()
    validate_album_catalog(deepcopy(catalog))  # does not raise
    assert public_album_catalog_failures(catalog) == []

    broken = _catalog()
    del broken["albums"][0]["title"]
    try:
        validate_album_catalog(deepcopy(broken))
        raised = False
    except AlbumCatalogValidationError:
        raised = True
    assert raised
    assert public_album_catalog_failures(broken) != []
