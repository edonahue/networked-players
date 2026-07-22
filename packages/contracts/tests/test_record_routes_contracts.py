from __future__ import annotations

from copy import deepcopy
from typing import Any

from networked_players_contracts.record_routes import (
    recomputed_route_id,
    record_routes_failures,
)

_SNAPSHOT = "20260601"
_CATALOG_VERSION = "catalog-v1-20260601-abc"


def _hop(release_id: int, a: int, b: int) -> dict[str, Any]:
    return {
        "release_id": release_id,
        "artist_a_id": a,
        "artist_b_id": b,
        "role_a": "Guitar",
        "role_b": "Bass",
        "quality_flags": ["performer_credit", "same_recording"],
    }


def _one_hop_route() -> dict[str, Any]:
    route: dict[str, Any] = {
        "id": "PLACEHOLDER",
        "kind": "one_hop",
        "difficulty": "medium",
        "from_album_id": "master-1",
        "to_album_id": "master-2",
        "from_artist_id": 100,
        "to_artist_id": 200,
        "hops": [_hop(500, 100, 200)],
        "distractors": [{"album_id": "master-3", "reason": "decoy"}],
    }
    route["id"] = recomputed_route_id(route)
    return route


def _album(album_id: str) -> dict[str, Any]:
    return {
        "id": album_id,
        "master_id": int(album_id.split("-")[1]),
        "main_release_id": int(album_id.split("-")[1]),
        "title": album_id.title(),
        "artist_id": 100,
        "artist": "Act",
        "year": 1990,
    }


def _provenance(rounds: list[dict[str, Any]]) -> dict[str, Any]:
    from networked_players_contracts.canonical import content_hash

    return {
        "source": "Discogs monthly data dump (CC0), one-hop working set",
        "license": "See docs/DATA_AND_RIGHTS.md.",
        "snapshot_date": _SNAPSHOT,
        "generated_by": "networked-players-catalog build-record-routes 0.1.0",
        "graph_core_version": "0.1.0",
        "note": "Real path evidence.",
        "catalog_version": _CATALOG_VERSION,
        "artifact_version": f"routes-artifact-v1-{_SNAPSHOT}-{content_hash(rounds, length=12)}",
    }


def _pair() -> tuple[dict[str, Any], dict[str, Any]]:
    from networked_players_contracts.canonical import content_hash

    routes = [_one_hop_route()]
    pool_version = (
        f"routes-v1-{_SNAPSHOT}-{content_hash(sorted(r['id'] for r in routes), length=12)}"
    )
    prov = _provenance(routes)
    universe = {
        "schema_version": 1,
        "mode": "record_routes",
        "pool_version": pool_version,
        "provenance": prov,
        "counts": {"one_hop": 1, "two_hop": 0, "daily_eligible": 1},
        "albums": [_album("master-1"), _album("master-2"), _album("master-3")],
    }
    rounds = {
        "schema_version": 1,
        "mode": "record_routes",
        "pool_version": pool_version,
        "provenance": prov,
        "rounds": routes,
        "releases": [],
        "artists": [],
    }
    return universe, rounds


def test_valid_pair_has_no_failures() -> None:
    universe, rounds = _pair()
    assert record_routes_failures(universe, rounds) == []


def test_rejects_wrong_mode() -> None:
    universe, rounds = _pair()
    rounds["mode"] = "connection_guesser_one_hop"
    assert any(
        "mode must be 'record_routes'" in f for f in record_routes_failures(universe, rounds)
    )


def test_rejects_ordinal_id() -> None:
    universe, rounds = _pair()
    rounds["rounds"][0]["id"] = "round-000001"
    assert any("content-derived route id" in f for f in record_routes_failures(universe, rounds))


def test_rejects_id_not_matching_content() -> None:
    universe, rounds = _pair()
    # Keep the route-<hex> format but make it not match the content.
    rounds["rounds"][0]["id"] = "route-deadbeef01"
    failures = record_routes_failures(universe, rounds)
    assert any("does not match its own recomputed content" in f for f in failures)


def test_rejects_embedded_art_in_universe_albums() -> None:
    universe, rounds = _pair()
    universe["albums"][0]["cover_image"] = {"uri": "https://i.discogs.com/x/y.jpg"}
    assert any("art-free" in f for f in record_routes_failures(universe, rounds))


def test_rejects_stale_pool_version() -> None:
    universe, rounds = _pair()
    universe["pool_version"] = "routes-v1-20260601-000000000000"
    # rounds keeps the old one -> also a match failure; force both to the stale value
    rounds["pool_version"] = "routes-v1-20260601-000000000000"
    assert any("membership" in f for f in record_routes_failures(universe, rounds))


def test_rejects_stale_artifact_version() -> None:
    universe, rounds = _pair()
    stale = deepcopy(universe["provenance"])
    stale["artifact_version"] = "routes-artifact-v1-20260601-000000000000"
    universe["provenance"] = stale
    rounds["provenance"] = stale
    assert any("artifact_version" in f for f in record_routes_failures(universe, rounds))


def test_rejects_endpoint_not_in_universe() -> None:
    universe, rounds = _pair()
    universe["albums"] = [a for a in universe["albums"] if a["id"] != "master-2"]
    assert any("to_album_id not in universe" in f for f in record_routes_failures(universe, rounds))


def test_rejects_distractor_that_is_an_endpoint() -> None:
    universe, rounds = _pair()
    route = rounds["rounds"][0]
    route["distractors"] = [{"album_id": route["from_album_id"], "reason": "x"}]
    # recompute id since distractors are not part of the id, id stays valid
    assert any(
        "distractor is one of its own endpoints" in f
        for f in record_routes_failures(universe, rounds)
    )


def test_rejects_hop_count_mismatch() -> None:
    universe, rounds = _pair()
    route = rounds["rounds"][0]
    route["kind"] = "two_hop"  # but only one hop present
    route["id"] = recomputed_route_id(route)
    # regenerate versions since content changed
    from networked_players_contracts.canonical import content_hash

    ids = sorted(r["id"] for r in rounds["rounds"])
    pv = f"routes-v1-{_SNAPSHOT}-{content_hash(ids, length=12)}"
    av = f"routes-artifact-v1-{_SNAPSHOT}-{content_hash(rounds['rounds'], length=12)}"
    universe["pool_version"] = rounds["pool_version"] = pv
    universe["provenance"]["artifact_version"] = av
    rounds["provenance"]["artifact_version"] = av
    assert any("must have 2 hop(s)" in f for f in record_routes_failures(universe, rounds))
