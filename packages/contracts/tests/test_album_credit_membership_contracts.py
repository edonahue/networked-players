from __future__ import annotations

from copy import deepcopy
from typing import Any

from networked_players_contracts.album_credit_membership import (
    album_credit_membership_failures,
    album_credit_membership_version,
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


def _credit(artist_id: int, name: str, *, role_text: str | None = "Guitar") -> dict[str, Any]:
    return {
        "artist_id": artist_id,
        "name": name,
        "anv": None,
        "role_text": role_text,
        "credit_scope": "release_artist",
        "track_position": None,
        "track_title": None,
    }


def _albums() -> list[dict[str, Any]]:
    return [
        {"album_id": "master-1", "main_release_id": 1, "credits": [_credit(100, "Alice")]},
        {"album_id": "master-2", "main_release_id": 2, "credits": [_credit(200, "Bob")]},
    ]


def _membership() -> dict[str, Any]:
    catalog = _catalog()
    albums = _albums()
    return {
        "schema_version": 1,
        "catalog_version": catalog["catalog_version"],
        "album_credit_membership_version": album_credit_membership_version(albums, _SNAPSHOT),
        "generated_at": "2026-08-07T00:00:00+00:00",
        "source": "Derived from each album's own main_release_id.",
        "license": "See docs/DATA_AND_RIGHTS.md.",
        "albums": albums,
    }


def test_clean_membership_has_no_failures() -> None:
    assert album_credit_membership_failures(_membership(), _catalog()) == []


def test_wrong_top_level_type_fails() -> None:
    assert album_credit_membership_failures("not a dict", _catalog()) != []
    assert album_credit_membership_failures(_membership(), "not a dict") != []


def test_mismatched_catalog_version_is_caught() -> None:
    membership = deepcopy(_membership())
    membership["catalog_version"] = "catalog-v1-wrong"
    failures = album_credit_membership_failures(membership, _catalog())
    assert any("catalog_version" in f for f in failures)


def test_stale_version_is_caught() -> None:
    membership = deepcopy(_membership())
    membership["album_credit_membership_version"] = (
        "album-credit-membership-v1-20260601-" + "0" * 12
    )
    failures = album_credit_membership_failures(membership, _catalog())
    assert any("album_credit_membership_version" in f for f in failures)


def test_missing_catalog_album_is_rejected() -> None:
    membership = deepcopy(_membership())
    membership["albums"].pop()
    failures = album_credit_membership_failures(membership, _catalog())
    assert any("missing" in f and "catalog album" in f for f in failures)


def test_album_id_not_in_catalog_is_rejected() -> None:
    membership = deepcopy(_membership())
    membership["albums"][0]["album_id"] = "master-999"
    failures = album_credit_membership_failures(membership, _catalog())
    assert any("not in the canonical catalog" in f for f in failures)


def test_wrong_main_release_id_is_rejected() -> None:
    """The whole point of this artifact is to reuse the catalog's own
    release choice verbatim -- a mismatch must fail closed, not be
    silently accepted as a different-but-valid choice."""
    membership = deepcopy(_membership())
    membership["albums"][0]["main_release_id"] = 999
    failures = album_credit_membership_failures(membership, _catalog())
    assert any("does not match the catalog's own choice" in f for f in failures)


def test_duplicate_album_id_is_rejected() -> None:
    membership = deepcopy(_membership())
    membership["albums"].append(deepcopy(membership["albums"][0]))
    failures = album_credit_membership_failures(membership, _catalog())
    assert any("duplicate album_id" in f for f in failures)


def test_unknown_credit_scope_is_rejected() -> None:
    membership = deepcopy(_membership())
    membership["albums"][0]["credits"][0]["credit_scope"] = "not_a_real_scope"
    failures = album_credit_membership_failures(membership, _catalog())
    assert any("credit_scope" in f for f in failures)


def test_empty_credits_list_is_valid() -> None:
    catalog = _catalog()
    albums = [
        {"album_id": "master-1", "main_release_id": 1, "credits": []},
        {"album_id": "master-2", "main_release_id": 2, "credits": []},
    ]
    membership = {
        "schema_version": 1,
        "catalog_version": catalog["catalog_version"],
        "album_credit_membership_version": album_credit_membership_version(albums, _SNAPSHOT),
        "generated_at": "2026-08-07T00:00:00+00:00",
        "source": "Derived from each album's own main_release_id.",
        "license": "See docs/DATA_AND_RIGHTS.md.",
        "albums": albums,
    }
    assert album_credit_membership_failures(membership, catalog) == []


def test_forbidden_inference_phrase_is_rejected() -> None:
    membership = deepcopy(_membership())
    membership["source"] = "Alice collaborated with Bob on this record."
    failures = album_credit_membership_failures(membership, _catalog())
    assert any("forbidden inference-implying phrase" in f for f in failures)
