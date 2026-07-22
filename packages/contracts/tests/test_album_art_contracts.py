from __future__ import annotations

from copy import deepcopy
from typing import Any

from networked_players_contracts.album_art import album_art_failures, album_art_version

_SNAPSHOT = "20260601"
_CATALOG_VERSION = "catalog-v1-20260601-abc123abc123"


def _catalog() -> dict[str, Any]:
    return {
        "catalog_version": _CATALOG_VERSION,
        "snapshot_date": _SNAPSHOT,
        "albums": [
            {"id": "master-1", "main_release_id": 11},
            {"id": "master-2", "main_release_id": 22},
            {"id": "master-3", "main_release_id": 33},
        ],
    }


def _entries() -> list[dict[str, Any]]:
    return [
        {
            "album_id": "master-1",
            "main_release_id": 11,
            "uri150": "https://i.discogs.com/a/150.jpg",
            "uri": "https://i.discogs.com/a/full.jpg",
            "width": 600,
            "height": 600,
        },
        {
            "album_id": "master-2",
            "main_release_id": 22,
            "uri150": "https://i.discogs.com/b/150.jpg",
            "uri": "https://i.discogs.com/b/full.jpg",
            "width": 500,
            "height": 500,
        },
    ]


def _registry(entries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    e = _entries() if entries is None else entries
    return {
        "schema_version": 1,
        "catalog_version": _CATALOG_VERSION,
        "art_version": album_art_version(e, _SNAPSHOT),
        "generated_at": "2026-07-22T00:00:00+00:00",
        "source": "Discogs API /releases/{id} images",
        "license": "presentational only",
        "albums": e,
    }


def test_valid_registry_passes() -> None:
    assert album_art_failures(_registry(), _catalog()) == []


def test_empty_registry_is_valid() -> None:
    assert album_art_failures(_registry([]), _catalog()) == []


def test_art_version_is_order_insensitive() -> None:
    forward = album_art_version(_entries(), _SNAPSHOT)
    reversed_entries = list(reversed(_entries()))
    assert album_art_version(reversed_entries, _SNAPSHOT) == forward


def test_rejects_catalog_version_mismatch() -> None:
    catalog = _catalog()
    catalog["catalog_version"] = "catalog-v1-20260601-different"
    failures = album_art_failures(_registry(), catalog)
    assert any("catalog_version" in f for f in failures)


def test_rejects_stale_art_version() -> None:
    registry = _registry()
    registry["art_version"] = "album-art-v1-20260601-000000000000"
    failures = album_art_failures(registry, _catalog())
    assert any("art_version" in f for f in failures)


def test_rejects_album_id_not_in_catalog() -> None:
    entries = _entries()
    entries[0]["album_id"] = "master-does-not-exist"
    registry = _registry(entries)
    failures = album_art_failures(registry, _catalog())
    assert any("not in the canonical catalog" in f for f in failures)


def test_rejects_duplicate_album_id() -> None:
    entries = _entries()
    entries[1]["album_id"] = "master-1"
    registry = _registry(entries)
    failures = album_art_failures(registry, _catalog())
    assert any("duplicate album_id" in f for f in failures)


def test_rejects_non_https_url() -> None:
    entries = _entries()
    entries[0]["uri150"] = "http://i.discogs.com/a/150.jpg"
    registry = _registry(entries)
    failures = album_art_failures(registry, _catalog())
    assert any("uri150" in f for f in failures)


def test_rejects_unapproved_host() -> None:
    entries = _entries()
    entries[0]["uri"] = "https://evil.example.com/a/full.jpg"
    registry = _registry(entries)
    failures = album_art_failures(registry, _catalog())
    assert any("uri" in f and "approved host" in f for f in failures)


def test_rejects_token_bearing_url() -> None:
    entries = _entries()
    entries[0]["uri"] = "https://i.discogs.com/a/full.jpg?token=secret"
    registry = _registry(entries)
    failures = album_art_failures(registry, _catalog())
    assert any("forbidden substring" in f for f in failures)


def test_rejects_unexpected_top_level_key() -> None:
    registry = _registry()
    registry["seed"] = "leaked"
    failures = album_art_failures(registry, _catalog())
    assert any("unexpected top-level keys" in f for f in failures)


def test_rejects_non_integer_main_release_id() -> None:
    entries = _entries()
    entries[0]["main_release_id"] = "11"
    registry = deepcopy(_registry(entries))
    failures = album_art_failures(registry, _catalog())
    assert any("main_release_id" in f for f in failures)
