from __future__ import annotations

from copy import deepcopy
from typing import Any

from networked_players_contracts.challenge import CHALLENGE_SCHEMA_VERSION, challenge_failures

_SNAPSHOT = "20260601"
_CATALOG_VERSION = "catalog-v1-20260601-abc123abc123"


def _release(release_id: int, title: str) -> dict[str, Any]:
    return {
        "snapshot_date": _SNAPSHOT,
        "release_id": release_id,
        "status": "Accepted",
        "title": title,
        "country": None,
        "released": "1995",
        "master_id": None,
        "master_is_main_release": None,
        "data_quality": None,
        "source_url": f"https://example.invalid/release/{release_id}",
        "credits": [],
    }


def _album(album_id: str, *, artist_id: int, main_release_id: int) -> dict[str, Any]:
    return {
        "id": album_id,
        "master_id": None,
        "main_release_id": main_release_id,
        "title": album_id.title(),
        "artist_id": artist_id,
        "artist": "Alice",
        "year": 1995,
        "cover_image": None,
    }


def _path(path_id: str, *, release_id: int, artist_a: int, artist_b: int) -> dict[str, Any]:
    return {
        "id": path_id,
        "hops": [
            {
                "release_id": release_id,
                "artist_a_id": artist_a,
                "artist_b_id": artist_b,
            }
        ],
    }


def _artifact() -> dict[str, Any]:
    albums = [
        _album("master-1", artist_id=100, main_release_id=1),
        _album("master-2", artist_id=200, main_release_id=2),
    ]
    releases = [_release(1, "Alpha's Album"), _release(2, "Bravo's Album")]
    artists = [{"artist_id": 100, "name": "Alice"}, {"artist_id": 200, "name": "Bob"}]
    paths = [_path("path-1", release_id=1, artist_a=100, artist_b=200)]
    return {
        "schema_version": CHALLENGE_SCHEMA_VERSION,
        "provenance": {
            "source": "Discogs monthly data dump (CC0), one-hop working set",
            "license": "Derived from the Discogs monthly CC0 data dumps. See "
            "docs/DATA_AND_RIGHTS.md.",
            "snapshot_date": _SNAPSHOT,
            "generated_by": "networked-players-catalog build-challenge-from-dump 0.1.0",
            "graph_core_version": "0.1.0",
            "catalog_version": _CATALOG_VERSION,
            "note": "Derived from a bounded one-hop working set.",
        },
        "albums": albums,
        "artists": artists,
        "paths": paths,
        "releases": releases,
    }


def _catalog() -> dict[str, Any]:
    return {"catalog_version": _CATALOG_VERSION}


def test_valid_artifact_has_no_failures() -> None:
    assert challenge_failures(_artifact()) == []


def test_valid_artifact_with_a_matching_catalog_has_no_failures() -> None:
    assert challenge_failures(_artifact(), _catalog()) == []


def test_rejects_unexpected_top_level_keys() -> None:
    artifact = _artifact()
    artifact["extra"] = "nope"
    assert any("unexpected top-level keys" in f for f in challenge_failures(artifact))


def test_rejects_wrong_schema_version() -> None:
    artifact = _artifact()
    artifact["schema_version"] = 1
    assert any("schema_version must be" in f for f in challenge_failures(artifact))


def test_rejects_missing_provenance_fields() -> None:
    artifact = _artifact()
    del artifact["provenance"]["license"]
    failures = challenge_failures(artifact)
    assert any("provenance.license is required" in f for f in failures)


def test_rejects_a_seed_key_anywhere_in_the_tree() -> None:
    artifact = _artifact()
    artifact["albums"][0]["seed"] = [1, 2, 3]
    assert any("must not have a 'seed' key" in f for f in challenge_failures(artifact))


def test_rejects_a_release_with_unexpected_keys() -> None:
    artifact = _artifact()
    artifact["releases"][0]["extra_field"] = "nope"
    assert any("unexpected keys" in f for f in challenge_failures(artifact))


def test_rejects_an_invalid_main_release_id() -> None:
    artifact = _artifact()
    artifact["albums"][0]["main_release_id"] = 0
    assert any("invalid main_release_id" in f for f in challenge_failures(artifact))


def test_rejects_a_path_hop_referencing_an_unpublished_release() -> None:
    artifact = _artifact()
    artifact["releases"] = [r for r in artifact["releases"] if r["release_id"] != 1]
    assert any("unpublished release" in f for f in challenge_failures(artifact))


def test_rejects_a_path_hop_referencing_an_unpublished_artist() -> None:
    artifact = _artifact()
    artifact["artists"] = [a for a in artifact["artists"] if a["artist_id"] != 200]
    assert any("unpublished artist" in f for f in challenge_failures(artifact))


def test_rejects_a_forbidden_substring() -> None:
    artifact = _artifact()
    artifact["provenance"]["note"] = "cache lives at /home/example/data"
    assert any("forbidden substring" in f for f in challenge_failures(artifact))


def test_rejects_a_forbidden_phrase() -> None:
    artifact = _artifact()
    artifact["provenance"]["note"] = "These two artists worked with each other."
    assert any("forbidden phrase" in f for f in challenge_failures(artifact))


def test_catalog_version_matching_the_given_catalog_passes() -> None:
    artifact = _artifact()
    assert artifact["provenance"]["catalog_version"] == _CATALOG_VERSION
    assert challenge_failures(artifact, _catalog()) == []


def test_catalog_version_disagreeing_with_the_given_catalog_fails() -> None:
    artifact = _artifact()
    mismatched_catalog = {"catalog_version": "catalog-v1-20260601-different"}
    failures = challenge_failures(artifact, mismatched_catalog)
    assert any("catalog_version" in f for f in failures)


def test_none_catalog_version_with_a_catalog_given_still_passes() -> None:
    """A hand-written {artist,title} query list legitimately has no catalog
    to agree with -- its own provenance note documents this (ADR 0012)."""
    artifact = _artifact()
    artifact["provenance"] = deepcopy(artifact["provenance"])
    artifact["provenance"]["catalog_version"] = None
    assert challenge_failures(artifact, _catalog()) == []


def test_no_catalog_argument_skips_the_cross_check_entirely() -> None:
    artifact = _artifact()
    artifact["provenance"]["catalog_version"] = "catalog-v1-20260601-anything-at-all"
    assert challenge_failures(artifact) == []
