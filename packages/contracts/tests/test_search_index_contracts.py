from __future__ import annotations

from typing import Any

from networked_players_contracts.search_index import search_index_failures, search_index_version

_SNAPSHOT = "20260601"
_CATALOG_VERSION = "catalog-v1-20260601-test"
_CONTRIBUTOR_INDEX_VERSION = "contributor-index-v1-20260601-test"


def _catalog() -> dict[str, Any]:
    return {
        "catalog_version": _CATALOG_VERSION,
        "snapshot_date": _SNAPSHOT,
        "albums": [
            {"id": "master-1", "title": "First Light", "artist": "Alice"},
        ],
    }


def _contributor_index() -> dict[str, Any]:
    return {
        "catalog_version": _CATALOG_VERSION,
        "contributor_index_version": _CONTRIBUTOR_INDEX_VERSION,
        "contributors": [{"artist_id": 100, "name": "Alice"}],
    }


def _search_index() -> dict[str, Any]:
    entries = [
        {
            "kind": "album",
            "id": "master-1",
            "label": "First Light",
            "sublabel": "Alice",
            "state": "present",
        },
        {
            "kind": "contributor",
            "id": "100",
            "label": "Alice",
            "sublabel": None,
            "state": "present",
        },
    ]
    payload: dict[str, Any] = {
        "schema_version": 1,
        "catalog_version": _CATALOG_VERSION,
        "contributor_index_version": _CONTRIBUTOR_INDEX_VERSION,
        "generated_at": "2026-09-03T00:00:00+00:00",
        "source": "test",
        "license": "test",
        "entries": entries,
    }
    payload["search_index_version"] = search_index_version(entries, _SNAPSHOT)
    return payload


def test_clean_payload_has_no_failures() -> None:
    assert search_index_failures(_search_index(), _catalog(), _contributor_index()) == []


def test_rejects_non_object_inputs() -> None:
    assert search_index_failures(None, {}, {}) == ["search index artifact must be an object"]
    assert search_index_failures({}, None, {}) == ["catalog must be an object"]
    assert search_index_failures({}, {}, None) == ["contributor_index must be an object"]


def test_rejects_unexpected_top_level_keys() -> None:
    broken = _search_index()
    broken["extra"] = 1
    failures = search_index_failures(broken, _catalog(), _contributor_index())
    assert any("unexpected top-level keys" in f for f in failures)


def test_rejects_catalog_version_mismatch() -> None:
    broken = _search_index()
    broken["catalog_version"] = "catalog-v1-20260601-other"
    failures = search_index_failures(broken, _catalog(), _contributor_index())
    assert any("catalog_version" in f for f in failures)


def test_rejects_contributor_index_version_mismatch() -> None:
    broken = _search_index()
    broken["contributor_index_version"] = "contributor-index-v1-20260601-other"
    failures = search_index_failures(broken, _catalog(), _contributor_index())
    assert any("contributor_index_version" in f for f in failures)


def test_rejects_missing_album() -> None:
    """The exact regression this cross-check exists to catch: an index
    that doesn't cover every catalog album."""
    broken = _search_index()
    broken["entries"] = [e for e in broken["entries"] if e["kind"] != "album"]
    broken["search_index_version"] = search_index_version(broken["entries"], _SNAPSHOT)
    failures = search_index_failures(broken, _catalog(), _contributor_index())
    assert any("must be indexed" in f for f in failures)


def test_rejects_album_entry_not_in_catalog() -> None:
    broken = _search_index()
    broken["entries"].append(
        {
            "kind": "album",
            "id": "master-999",
            "label": "Nonexistent",
            "sublabel": "Nobody",
            "state": "present",
        }
    )
    broken["search_index_version"] = search_index_version(broken["entries"], _SNAPSHOT)
    failures = search_index_failures(broken, _catalog(), _contributor_index())
    assert any("is not in the canonical catalog" in f for f in failures)


def test_rejects_contributor_entry_not_in_index() -> None:
    broken = _search_index()
    broken["entries"].append(
        {
            "kind": "contributor",
            "id": "999",
            "label": "Nobody",
            "sublabel": None,
            "state": "present",
        }
    )
    broken["search_index_version"] = search_index_version(broken["entries"], _SNAPSHOT)
    failures = search_index_failures(broken, _catalog(), _contributor_index())
    assert any("is not a published contributor" in f for f in failures)


def test_rejects_invalid_kind() -> None:
    broken = _search_index()
    broken["entries"][0]["kind"] = "artist"
    broken["search_index_version"] = search_index_version(broken["entries"], _SNAPSHOT)
    failures = search_index_failures(broken, _catalog(), _contributor_index())
    assert any("kind must be one of" in f for f in failures)


def test_rejects_invalid_state() -> None:
    broken = _search_index()
    broken["entries"][0]["state"] = "unknown"
    broken["search_index_version"] = search_index_version(broken["entries"], _SNAPSHOT)
    failures = search_index_failures(broken, _catalog(), _contributor_index())
    assert any("state must be one of" in f for f in failures)


def test_rejects_duplicate_entry() -> None:
    broken = _search_index()
    broken["entries"].append(dict(broken["entries"][0]))
    broken["search_index_version"] = search_index_version(broken["entries"], _SNAPSHOT)
    failures = search_index_failures(broken, _catalog(), _contributor_index())
    assert any("must not repeat" in f for f in failures)


def test_rejects_tampered_version() -> None:
    broken = _search_index()
    broken["entries"][0]["label"] = "Tampered"
    failures = search_index_failures(broken, _catalog(), _contributor_index())
    assert any("does not match the artifact's own" in f for f in failures)


def test_rejects_malformed_version_pattern() -> None:
    broken = _search_index()
    broken["search_index_version"] = "not-a-real-version"
    failures = search_index_failures(broken, _catalog(), _contributor_index())
    assert any("not a well-formed search-index-v1 version" in f for f in failures)
