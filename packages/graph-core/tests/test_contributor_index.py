from __future__ import annotations

from typing import Any

from networked_players_graph_core.contributor_index import build_contributor_index
from networked_players_graph_core.role_taxonomy import RoleCategory

_SNAPSHOT = "20260601"
_CATALOG_VERSION = "catalog-v1-20260601-abc123abc123"


def _catalog() -> dict[str, Any]:
    return {
        "catalog_version": _CATALOG_VERSION,
        "snapshot_date": _SNAPSHOT,
        "albums": [
            {"id": "master-1", "title": "First Light", "artist_id": 100, "year": 1995},
            {"id": "master-2", "title": "Second Wave", "artist_id": 200, "year": 2001},
            {"id": "master-3", "title": "Third Decoy", "artist_id": 300, "year": 1988},
        ],
    }


def _challenge_release(release_id: int, credits: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "snapshot_date": _SNAPSHOT,
        "release_id": release_id,
        "title": f"R{release_id}",
        "credits": credits,
    }


def _credit(artist_id: int, role_text: str) -> dict[str, Any]:
    return {
        "release_id": None,
        "credit_scope": "release_artist",
        "artist_id": artist_id,
        "name": f"Artist {artist_id}",
        "anv": None,
        "role_text": role_text,
        "is_linked": True,
        "playable_identity": True,
    }


def _challenge() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "provenance": {"catalog_version": _CATALOG_VERSION},
        "artists": [
            {"artist_id": 100, "name": "Alice"},
            {"artist_id": 200, "name": "Bob"},
        ],
        "paths": [
            {
                "id": "path-1",
                "from_album_id": "master-1",
                "to_album_id": "master-2",
                "hops": [{"release_id": 501, "artist_a_id": 100, "artist_b_id": 200}],
            }
        ],
        "releases": [
            _challenge_release(501, [_credit(100, "Guitar"), _credit(200, "Bass")]),
        ],
    }


def _routes_universe() -> dict[str, Any]:
    return {"provenance": {"catalog_version": _CATALOG_VERSION}, "albums": []}


def _routes_rounds() -> dict[str, Any]:
    return {
        "provenance": {"catalog_version": _CATALOG_VERSION},
        "artists": [
            {"artist_id": 200, "name": "Bob"},
            {"artist_id": 300, "name": "Carol"},
        ],
        "rounds": [
            {
                "from_album_id": "master-2",
                "to_album_id": "master-3",
                "hops": [
                    {
                        "release_id": 900,
                        "artist_a_id": 200,
                        "artist_b_id": 300,
                        "role_a": "Producer",
                        "role_b": "Mastered By",
                    }
                ],
            }
        ],
        "releases": [],
    }


def _build() -> dict[str, Any]:
    return build_contributor_index(
        challenge=_challenge(),
        routes_universe=_routes_universe(),
        routes_rounds=_routes_rounds(),
        catalog=_catalog(),
        generated_at="2026-08-03T00:00:00+00:00",
    )


def test_top_level_shape() -> None:
    index = _build()
    assert index["schema_version"] == 1
    assert index["catalog_version"] == _CATALOG_VERSION
    assert index["contributor_index_version"].startswith(f"contributor-index-v1-{_SNAPSHOT}-")
    assert index["generated_at"] == "2026-08-03T00:00:00+00:00"


def test_every_hop_artist_becomes_a_contributor() -> None:
    index = _build()
    ids = {c["artist_id"] for c in index["contributors"]}
    assert ids == {100, 200, 300}


def test_role_text_from_challenge_credit_rows_is_attached() -> None:
    index = _build()
    alice = next(c for c in index["contributors"] if c["artist_id"] == 100)
    assert "Guitar" in alice["role_text_examples"]
    assert RoleCategory.STRINGS.value in alice["role_categories"]


def test_role_text_from_routes_hop_fields_is_attached() -> None:
    index = _build()
    carol = next(c for c in index["contributors"] if c["artist_id"] == 300)
    assert "Mastered By" in carol["role_text_examples"]
    assert RoleCategory.ENGINEERING.value in carol["role_categories"]


def test_albums_are_the_endpoints_of_every_path_or_round_the_contributor_appears_in() -> None:
    index = _build()
    bob = next(c for c in index["contributors"] if c["artist_id"] == 200)
    assert bob["albums"] == ["master-1", "master-2", "master-3"]


def test_decade_activity_derived_from_catalog_years() -> None:
    # Alice appears only on the master-1<->master-2 path, so she's associated
    # with both of that path's endpoint albums (1995 and 2001).
    index = _build()
    alice = next(c for c in index["contributors"] if c["artist_id"] == 100)
    assert alice["decade_activity"] == [1990, 2000]
    # Bob bridges both the master-1<->master-2 path and the master-2<->
    # master-3 round, so all three albums' decades apply to him.
    bob = next(c for c in index["contributors"] if c["artist_id"] == 200)
    assert bob["decade_activity"] == [1980, 1990, 2000]


def test_connection_count_and_neighbors_reflect_published_hops_only() -> None:
    index = _build()
    bob = next(c for c in index["contributors"] if c["artist_id"] == 200)
    assert bob["connection_count"] == 2
    assert set(bob["neighboring_contributor_ids"]) == {100, 300}


def test_evidence_entries_reference_real_release_ids() -> None:
    index = _build()
    alice = next(c for c in index["contributors"] if c["artist_id"] == 100)
    assert {"release_id": 501, "role_text": "Guitar"} in alice["evidence"]


def test_deterministic_across_repeated_builds() -> None:
    assert _build() == _build()


def test_mismatched_catalog_version_raises() -> None:
    import pytest

    bad_challenge = _challenge()
    bad_challenge["provenance"]["catalog_version"] = "catalog-v1-wrong"
    with pytest.raises(ValueError, match="catalog_version"):
        build_contributor_index(
            challenge=bad_challenge,
            routes_universe=_routes_universe(),
            routes_rounds=_routes_rounds(),
            catalog=_catalog(),
            generated_at="2026-08-03T00:00:00+00:00",
        )
