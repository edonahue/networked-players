from __future__ import annotations

from typing import Any

import pytest

from networked_players_graph_core.search_index import build_search_index, search_index_version

_SNAPSHOT = "20260601"
_CATALOG_VERSION = "catalog-v1-20260601-test"
_CONTRIBUTOR_INDEX_VERSION = "contributor-index-v1-20260601-test"


def _catalog() -> dict[str, Any]:
    return {
        "catalog_version": _CATALOG_VERSION,
        "snapshot_date": _SNAPSHOT,
        "albums": [
            {
                "id": "master-1",
                "artist_id": 100,
                "artist": "Alice",
                "master_id": 1,
                "main_release_id": 1,
                "title": "First Light",
                "year": 1995,
            },
            {
                "id": "master-2",
                "artist_id": 200,
                "artist": "Bob",
                "master_id": 2,
                "main_release_id": 2,
                "title": "Second Wave",
                "year": 1998,
            },
        ],
    }


def _contributor_index() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "catalog_version": _CATALOG_VERSION,
        "contributor_index_version": _CONTRIBUTOR_INDEX_VERSION,
        "generated_at": "2026-09-03T00:00:00+00:00",
        "source": "test",
        "license": "test",
        "contributors": [
            {
                "artist_id": 100,
                "name": "Alice",
                "role_categories": ["strings"],
                "role_text_examples": ["Guitar"],
                "albums": ["master-1"],
                "decade_activity": [1990],
                "connection_count": 1,
                "neighboring_contributor_ids": [200],
                "evidence": [],
                "interesting_next_step": None,
            },
            {
                "artist_id": 300,
                "name": "Cara",
                "role_categories": ["vocals"],
                "role_text_examples": ["Vocals"],
                "albums": [],
                "decade_activity": [],
                "connection_count": 0,
                "neighboring_contributor_ids": [],
                "evidence": [],
                "interesting_next_step": None,
            },
        ],
    }


def test_indexes_every_album_and_contributor() -> None:
    payload = build_search_index(
        catalog=_catalog(),
        contributor_index=_contributor_index(),
        generated_at="2026-09-03T00:00:00+00:00",
    )
    kinds = [(e["kind"], e["id"]) for e in payload["entries"]]
    assert ("album", "master-1") in kinds
    assert ("album", "master-2") in kinds
    assert ("contributor", "100") in kinds
    assert ("contributor", "300") in kinds
    assert len(payload["entries"]) == 4


def test_album_entry_shape() -> None:
    payload = build_search_index(
        catalog=_catalog(),
        contributor_index=_contributor_index(),
        generated_at="2026-09-03T00:00:00+00:00",
    )
    album_entry = next(e for e in payload["entries"] if e["id"] == "master-1")
    assert album_entry == {
        "kind": "album",
        "id": "master-1",
        "label": "First Light",
        "sublabel": "Alice",
        "state": "present",
    }


def test_contributor_entry_shape() -> None:
    payload = build_search_index(
        catalog=_catalog(),
        contributor_index=_contributor_index(),
        generated_at="2026-09-03T00:00:00+00:00",
    )
    contributor_entry = next(e for e in payload["entries"] if e["id"] == "100")
    assert contributor_entry == {
        "kind": "contributor",
        "id": "100",
        "label": "Alice",
        "sublabel": None,
        "state": "present",
    }


def test_every_entry_state_is_present() -> None:
    """Phase 1 has no catalog/candidates.v1.json to derive 'candidate'
    entries from -- that's a Phase 3 dependency this builder deliberately
    doesn't have."""
    payload = build_search_index(
        catalog=_catalog(),
        contributor_index=_contributor_index(),
        generated_at="2026-09-03T00:00:00+00:00",
    )
    assert all(e["state"] == "present" for e in payload["entries"])


def test_pins_catalog_and_contributor_index_versions() -> None:
    payload = build_search_index(
        catalog=_catalog(),
        contributor_index=_contributor_index(),
        generated_at="2026-09-03T00:00:00+00:00",
    )
    assert payload["catalog_version"] == _CATALOG_VERSION
    assert payload["contributor_index_version"] == _CONTRIBUTOR_INDEX_VERSION


def test_search_index_version_matches_recomputation() -> None:
    payload = build_search_index(
        catalog=_catalog(),
        contributor_index=_contributor_index(),
        generated_at="2026-09-03T00:00:00+00:00",
    )
    assert payload["search_index_version"] == search_index_version(payload["entries"], _SNAPSHOT)
    assert payload["search_index_version"].startswith(f"search-index-v1-{_SNAPSHOT}-")


def test_catalog_version_mismatch_raises() -> None:
    contributor_index = _contributor_index()
    contributor_index["catalog_version"] = "catalog-v1-20260601-different"
    with pytest.raises(ValueError, match="catalog_version"):
        build_search_index(
            catalog=_catalog(),
            contributor_index=contributor_index,
            generated_at="2026-09-03T00:00:00+00:00",
        )
