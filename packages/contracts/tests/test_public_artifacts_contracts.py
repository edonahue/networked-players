"""Cross-checks `public_artifacts_failures` against each individual
validator it wraps, and proves the whole point of this module: a real
defect in any one artifact (here, a deleted `mode` key on Record Routes) is
caught by the combined check, not silently missed."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from networked_players_contracts import public_artifacts_failures
from networked_players_contracts.album_art import album_art_version
from networked_players_contracts.canonical import content_hash, stable_id_digest
from networked_players_contracts.catalog import _catalog_version
from networked_players_contracts.connection_rounds import round_content_fingerprint

_SNAPSHOT = "20260601"
_CATALOG_VERSION = "catalog-v1-20260601-abc123abc123"


# --- catalog + album-art registry -------------------------------------------


def _catalog_album(album_id: str, *, artist_id: int, main_release_id: int) -> dict[str, Any]:
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
        _catalog_album("master-1", artist_id=100, main_release_id=1),
        _catalog_album("master-2", artist_id=200, main_release_id=2),
    ]
    return {
        "catalog_version": _catalog_version(albums, _SNAPSHOT),
        "snapshot_date": _SNAPSHOT,
        "generated_by": "networked-players-catalog build-album-catalog 0.1.0",
        "albums": albums,
    }


def _album_art_registry() -> dict[str, Any]:
    entries = [
        {
            "album_id": "master-1",
            "main_release_id": 1,
            "uri150": "https://i.discogs.com/a/150.jpg",
            "uri": "https://i.discogs.com/a/full.jpg",
            "width": 600,
            "height": 600,
        }
    ]
    return {
        "schema_version": 1,
        "catalog_version": _catalog()["catalog_version"],
        "art_version": album_art_version(entries, _SNAPSHOT),
        "generated_at": "2026-07-22T00:00:00+00:00",
        "source": "Discogs API /releases/{id} images",
        "license": "presentational only",
        "albums": entries,
    }


# --- Connection Guesser ------------------------------------------------------

_CONNECTION_ROUND_ID = f"conn-{stable_id_digest('1h', 'album-a', 'album-c', '700')}"


def _connection_round() -> dict[str, Any]:
    return {
        "id": _CONNECTION_ROUND_ID,
        "pool": "real-records",
        "kind": "one_hop",
        "difficulty": "hard",
        "endpoints": [
            {
                "id": "album-a",
                "title": "First Light",
                "year": 1995,
                "act": "Alice",
                "label": None,
                "art": None,
            },
            {
                "id": "album-c",
                "title": "Third Wave",
                "year": 1996,
                "act": "Cara",
                "label": None,
                "art": None,
            },
        ],
        "answer_set": [{"id": 700, "name": "Xavier", "role_category": "guitar"}],
        "distractors": [],
        "clues": [],
        "evidence": [
            {
                "release_ref": "album-a",
                "release_title": "First Light",
                "contributor_id": 700,
                "credited_as": "Xavier",
                "role_text": "Guitar",
                "credit_scope": "release_credit",
            },
            {
                "release_ref": "album-c",
                "release_title": "Third Wave",
                "contributor_id": 700,
                "credited_as": "Xavier",
                "role_text": "Guitar",
                "credit_scope": "release_credit",
            },
        ],
        "provenance_note": "Real records: derived from the Discogs monthly data dump (CC0).",
    }


def _connection_artifact_version(rounds: list[dict[str, Any]]) -> str:
    fingerprints = [round_content_fingerprint(r) for r in rounds]
    digest = content_hash(fingerprints, length=12)
    return f"connection-artifact-v1-{_SNAPSHOT}-{digest}"


_CONNECTION_PROVENANCE = {
    "source": "Discogs monthly data dump (CC0), one-hop working set",
    "license": "See docs/DATA_AND_RIGHTS.md.",
    "snapshot_date": _SNAPSHOT,
    "generated_by": "networked-players-catalog build-connection-rounds 0.1.0",
    "catalog_version": _CATALOG_VERSION,
    "pool_version": "connection-v1-20260601-def456def456",
    "artifact_version": _connection_artifact_version([_connection_round()]),
    "note": "Real records, not synthetic.",
}


def _connection_universe() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "provenance": dict(_CONNECTION_PROVENANCE),
        "albums": [
            {
                "id": "album-a",
                "title": "First Light",
                "act": "Alice",
                "act_id": 100,
                "year": 1995,
                "label": None,
                "art": None,
            },
            {
                "id": "album-c",
                "title": "Third Wave",
                "act": "Cara",
                "act_id": 300,
                "year": 1996,
                "label": None,
                "art": None,
            },
        ],
        "contributors": [{"id": 700, "name": "Xavier", "role_category": "guitar"}],
        "releases": [
            {
                "id": "album-a",
                "album_id": "album-a",
                "title": "First Light",
                "year": 1995,
                "catalog_stamp": "DISCOGS-1",
            },
            {
                "id": "album-c",
                "album_id": "album-c",
                "title": "Third Wave",
                "year": 1996,
                "catalog_stamp": "DISCOGS-2",
            },
        ],
        "credits": [
            {
                "release_id": "album-a",
                "contributor_id": 700,
                "role_text": "Guitar",
                "role_category": "guitar",
                "credit_scope": "release_credit",
            },
            {
                "release_id": "album-c",
                "contributor_id": 700,
                "role_text": "Guitar",
                "role_category": "guitar",
                "credit_scope": "release_credit",
            },
        ],
    }


def _connection_rounds() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "provenance": dict(_CONNECTION_PROVENANCE),
        "rounds": [_connection_round()],
    }


# --- Connection-daily-manifest -----------------------------------------------


def _daily_manifest() -> dict[str, Any]:
    round_json = _connection_round()
    return {
        "schema_version": 1,
        "mode": "connection_guesser_one_hop",
        "catalog_version": _CATALOG_VERSION,
        "pool_version": _CONNECTION_PROVENANCE["pool_version"],
        "artifact_version": _CONNECTION_PROVENANCE["artifact_version"],
        "generated_at": "2026-07-22T00:00:00+00:00",
        "start_date": "2026-07-22",
        "schedule": [
            {
                "date": "2026-07-22",
                "round_id": round_json["id"],
                "round_fingerprint": round_content_fingerprint(round_json),
            }
        ],
    }


# --- Record Routes ------------------------------------------------------------


def _route_hop(release_id: int, a: int, b: int) -> dict[str, Any]:
    return {
        "release_id": release_id,
        "artist_a_id": a,
        "artist_b_id": b,
        "role_a": "Guitar",
        "role_b": "Bass",
        "quality_flags": ["performer_credit", "same_recording"],
    }


def _route() -> dict[str, Any]:
    endpoints = sorted(("master-1", "master-2"))
    route_id = f"route-{stable_id_digest('rr', *endpoints, '500:100:200')}"
    return {
        "id": route_id,
        "kind": "one_hop",
        "difficulty": "medium",
        "from_album_id": "master-1",
        "to_album_id": "master-2",
        "from_artist_id": 100,
        "to_artist_id": 200,
        "hops": [_route_hop(500, 100, 200)],
        "distractors": [],
    }


def _routes_releases_and_artists(routes: list[dict[str, Any]]) -> tuple[list, list]:
    """Minimal `rounds.releases[]`/`rounds.artists[]` entries covering every
    hop reference in `routes` -- record_routes_failures checks every hop's
    release_id/artist_a_id/artist_b_id resolve against these."""
    release_ids: set[int] = set()
    artist_ids: set[int] = set()
    for route in routes:
        for hop in route["hops"]:
            release_ids.add(hop["release_id"])
            artist_ids.add(hop["artist_a_id"])
            artist_ids.add(hop["artist_b_id"])
    releases = [{"release_id": rid, "title": f"Release {rid}"} for rid in sorted(release_ids)]
    artists = [{"artist_id": aid, "name": f"Artist {aid}"} for aid in sorted(artist_ids)]
    return releases, artists


def _routes_provenance(
    albums: list[dict[str, Any]],
    rounds: list[dict[str, Any]],
    releases: list[dict[str, Any]],
    artists: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = {"albums": albums, "rounds": rounds, "releases": releases, "artists": artists}
    return {
        "source": "Discogs monthly data dump (CC0), one-hop working set",
        "license": "See docs/DATA_AND_RIGHTS.md.",
        "snapshot_date": _SNAPSHOT,
        "generated_by": "networked-players-catalog build-record-routes 0.1.0",
        "graph_core_version": "0.1.0",
        "note": "Real path evidence.",
        "catalog_version": _CATALOG_VERSION,
        "artifact_version": (f"routes-artifact-v1-{_SNAPSHOT}-{content_hash(payload, length=12)}"),
    }


def _routes_pair() -> tuple[dict[str, Any], dict[str, Any]]:
    routes = [_route()]
    albums = [
        _catalog_album("master-1", artist_id=100, main_release_id=1),
        _catalog_album("master-2", artist_id=200, main_release_id=2),
    ]
    releases, artists = _routes_releases_and_artists(routes)
    pool_version = (
        f"routes-v1-{_SNAPSHOT}-{content_hash(sorted(r['id'] for r in routes), length=12)}"
    )
    prov = _routes_provenance(albums, routes, releases, artists)
    universe = {
        "schema_version": 1,
        "mode": "record_routes",
        "pool_version": pool_version,
        "provenance": prov,
        "counts": {"one_hop": 1, "two_hop": 0, "daily_eligible": 1},
        "albums": albums,
    }
    rounds = {
        "schema_version": 1,
        "mode": "record_routes",
        "pool_version": pool_version,
        "provenance": prov,
        "rounds": routes,
        "releases": releases,
        "artists": artists,
    }
    return universe, rounds


# --- the combined check -------------------------------------------------------


def _clean_artifacts() -> dict[str, Any]:
    routes_universe, routes_rounds = _routes_pair()
    return {
        "catalog": _catalog(),
        "album_art": _album_art_registry(),
        "connection_universe": _connection_universe(),
        "connection_rounds": _connection_rounds(),
        "daily_manifest": _daily_manifest(),
        "routes_universe": routes_universe,
        "routes_rounds": routes_rounds,
    }


def test_clean_publication_set_has_no_failures() -> None:
    report = public_artifacts_failures(**_clean_artifacts())
    assert report == {
        "catalog": [],
        "album_art_registry": [],
        "connection_guesser": [],
        "connection_daily_manifest": [],
        "record_routes": [],
    }


def test_every_group_key_always_present() -> None:
    report = public_artifacts_failures(**_clean_artifacts())
    assert set(report) == {
        "catalog",
        "album_art_registry",
        "connection_guesser",
        "connection_daily_manifest",
        "record_routes",
    }


def test_deleted_mode_on_record_routes_is_caught() -> None:
    """The exact regression this module exists to prevent: a real defect in
    one committed artifact must surface in the combined report, not be
    silently missed because nothing ever ran the real validator against it."""
    artifacts = _clean_artifacts()
    broken_universe = deepcopy(artifacts["routes_universe"])
    broken_rounds = deepcopy(artifacts["routes_rounds"])
    del broken_universe["mode"]
    del broken_rounds["mode"]
    artifacts["routes_universe"] = broken_universe
    artifacts["routes_rounds"] = broken_rounds

    report = public_artifacts_failures(**artifacts)
    assert report["record_routes"] != []
    assert any("mode" in f for f in report["record_routes"])
    # Every other artifact stays clean -- one defect doesn't mask another.
    assert report["catalog"] == []
    assert report["album_art_registry"] == []
    assert report["connection_guesser"] == []
    assert report["connection_daily_manifest"] == []


def test_catalog_defect_is_caught_independently() -> None:
    artifacts = _clean_artifacts()
    broken_catalog = deepcopy(artifacts["catalog"])
    del broken_catalog["albums"][0]["title"]
    artifacts["catalog"] = broken_catalog

    report = public_artifacts_failures(**artifacts)
    assert report["catalog"] != []
    assert report["record_routes"] == []
