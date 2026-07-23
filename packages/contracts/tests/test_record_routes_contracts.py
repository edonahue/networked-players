from __future__ import annotations

from copy import deepcopy
from typing import Any

from networked_players_contracts.canonical import content_hash
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


def _two_hop_route() -> dict[str, Any]:
    route: dict[str, Any] = {
        "id": "PLACEHOLDER",
        "kind": "two_hop",
        "difficulty": "hard",
        "from_album_id": "master-1",
        "to_album_id": "master-2",
        "from_artist_id": 100,
        "to_artist_id": 200,
        "hops": [_hop(500, 100, 999), _hop(501, 999, 200)],
        "distractors": [],
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


def _releases_and_artists(
    routes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Minimal `rounds.releases[]`/`rounds.artists[]` entries covering every
    hop reference in `routes` -- the exact shape `record_routes_failures`
    checks resolution against. The validator doesn't check per-item key
    sets for these two arrays (only album entries get that), so a minimal
    shape is enough for these tests."""
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


def _provenance(
    routes: list[dict[str, Any]],
    albums: list[dict[str, Any]],
    releases: list[dict[str, Any]],
    artists: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = {"albums": albums, "rounds": routes, "releases": releases, "artists": artists}
    return {
        "source": "Discogs monthly data dump (CC0), one-hop working set",
        "license": "See docs/DATA_AND_RIGHTS.md.",
        "snapshot_date": _SNAPSHOT,
        "generated_by": "networked-players-catalog build-record-routes 0.1.0",
        "graph_core_version": "0.1.0",
        "note": "Real path evidence.",
        "catalog_version": _CATALOG_VERSION,
        "artifact_version": f"routes-artifact-v1-{_SNAPSHOT}-{content_hash(payload, length=12)}",
    }


def _pair(routes: list[dict[str, Any]] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    routes = routes if routes is not None else [_one_hop_route()]
    pool_version = (
        f"routes-v1-{_SNAPSHOT}-{content_hash(sorted(r['id'] for r in routes), length=12)}"
    )
    albums = [_album("master-1"), _album("master-2"), _album("master-3")]
    releases, artists = _releases_and_artists(routes)
    prov = _provenance(routes, albums, releases, artists)
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


def _resync_versions(universe: dict[str, Any], rounds: dict[str, Any]) -> None:
    """After hand-mutating `rounds["rounds"]`/`releases`/`artists` in a test,
    recompute pool_version/artifact_version so only the mutation under test
    is exercised, not an incidental version mismatch."""
    routes = rounds["rounds"]
    ids = sorted(r["id"] for r in routes)
    pv = f"routes-v1-{_SNAPSHOT}-{content_hash(ids, length=12)}"
    prov = _provenance(routes, universe["albums"], rounds["releases"], rounds["artists"])
    universe["pool_version"] = rounds["pool_version"] = pv
    universe["provenance"] = prov
    rounds["provenance"] = prov


def test_valid_pair_has_no_failures() -> None:
    universe, rounds = _pair()
    assert record_routes_failures(universe, rounds) == []


def test_valid_two_hop_pair_has_no_failures() -> None:
    universe, rounds = _pair([_two_hop_route()])
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


def test_artifact_version_moves_on_an_artist_name_change() -> None:
    """Proves the redefinition actually closes the gap it was written for:
    a display-name edit in rounds.artists (not touched by the old
    rounds-only formula) must move artifact_version."""
    universe, rounds = _pair()
    edited_artists = deepcopy(rounds["artists"])
    edited_artists[0]["name"] = edited_artists[0]["name"] + " (corrected)"
    stale_provenance = dict(rounds["provenance"])
    rounds["artists"] = edited_artists
    # Deliberately do NOT resync versions -- the old (unchanged) artifact_version
    # must now be reported stale, proving the new formula covers this array.
    universe["provenance"] = stale_provenance
    failures = record_routes_failures(universe, rounds)
    assert any("artifact_version" in f for f in failures)


def test_rejects_endpoint_not_in_universe() -> None:
    universe, rounds = _pair()
    universe["albums"] = [a for a in universe["albums"] if a["id"] != "master-2"]
    assert any("to_album_id not in universe" in f for f in record_routes_failures(universe, rounds))


def test_rejects_duplicate_album_id() -> None:
    universe, rounds = _pair()
    universe["albums"].append(deepcopy(universe["albums"][0]))
    assert any("duplicate album id" in f for f in record_routes_failures(universe, rounds))


def test_rejects_album_with_unexpected_keys() -> None:
    universe, rounds = _pair()
    universe["albums"][0]["extra_field"] = "nope"
    assert any("unexpected keys" in f for f in record_routes_failures(universe, rounds))


def test_rejects_hop_referencing_an_unpublished_release() -> None:
    universe, rounds = _pair()
    rounds["releases"] = [r for r in rounds["releases"] if r["release_id"] != 500]
    assert any("unpublished release" in f for f in record_routes_failures(universe, rounds))


def test_rejects_hop_referencing_an_unpublished_artist() -> None:
    universe, rounds = _pair()
    rounds["artists"] = [a for a in rounds["artists"] if a["artist_id"] != 200]
    assert any("unpublished artist" in f for f in record_routes_failures(universe, rounds))


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
    _resync_versions(universe, rounds)
    assert any("must have 2 hop(s)" in f for f in record_routes_failures(universe, rounds))


def test_rejects_one_hop_route_whose_hop_does_not_match_its_endpoints() -> None:
    universe, rounds = _pair()
    route = rounds["rounds"][0]
    route["hops"][0]["artist_a_id"] = 999  # neither endpoint
    rounds["artists"].append({"artist_id": 999, "name": "Someone Else"})
    assert any(
        "do not match its own endpoints" in f for f in record_routes_failures(universe, rounds)
    )


def test_rejects_two_hop_route_with_no_bridge() -> None:
    universe, rounds = _pair([_two_hop_route()])
    route = rounds["rounds"][0]
    # Break continuity: hop 1 no longer shares any artist with hop 0.
    route["hops"][1]["artist_a_id"] = 12345
    rounds["artists"].append({"artist_id": 12345, "name": "Disconnected"})
    assert any(
        "exactly one non-endpoint bridge artist" in f
        for f in record_routes_failures(universe, rounds)
    )


def test_rejects_two_hop_route_with_an_ambiguous_bridge() -> None:
    """Neither hop touches the route's own declared endpoints, and the two
    hops share two non-endpoint artists instead of one -- both a missing-
    endpoint failure and an ambiguous-bridge failure should fire."""
    universe, rounds = _pair([_two_hop_route()])
    route = rounds["rounds"][0]
    route["hops"] = [_hop(500, 998, 999), _hop(501, 999, 998)]
    rounds["artists"] += [
        {"artist_id": 998, "name": "Bridge A"},
        {"artist_id": 999, "name": "Bridge B"},
    ]
    failures = record_routes_failures(universe, rounds)
    assert any("exactly one non-endpoint bridge artist" in f for f in failures)
    assert any(
        "does not include from_artist_id" in f or "does not include to_artist_id" in f
        for f in failures
    )
