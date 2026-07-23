from __future__ import annotations

from pathlib import Path

import pytest

from networked_players_contracts.record_routes import (
    recomputed_route_id,
    record_routes_failures,
)
from networked_players_graph_core.challenge import match_albums
from networked_players_graph_core.graph import CreditGraph
from networked_players_graph_core.record_routes import (
    RECORD_ROUTES_MODE,
    RecordRoutesValidationError,
    build_record_routes_pool,
    record_routes_artifact_version,
    record_routes_pool_version,
    stable_route_id,
    validate_record_routes_artifact,
)

# Reuses the exact fixture graph from test_rounds_generator.py:
#   Release 1 "Alpha's Album" -- Alice(100) & Bob(200) co-billed
#   Release 2 "Bravo's Album" -- Bob(200) & Cara(300) co-billed
#   Release 4 "Cara Solo"     -- Cara(300) alone
#   Release 3 "Delta's Album" -- Dan(400) & Eve(500) co-billed
#   Release 5 "Eve Solo"      -- Eve(500) alone
# One-hop: Alice-Bob, Bob-Cara, Dan-Eve. Two-hop: Alice-Cara via bridge Bob.
SNAPSHOT_DATE = "20260601"


def _release(release_id: int, title: str) -> dict:
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "release_id": release_id,
        "status": "Accepted",
        "title": title,
        "country": None,
        "released": "1995",
        "master_id": None,
        "master_is_main_release": None,
        "data_quality": None,
        "source_url": f"https://example.invalid/release/{release_id}",
    }


def _credit(
    release_id: int,
    *,
    artist_id: int,
    name: str,
    scope: str,
    role_text: str | None,
    track_index: int | None = None,
) -> dict:
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "release_id": release_id,
        "track_index": track_index,
        "track_path": None if track_index is None else str(track_index),
        "track_position": None if track_index is None else str(track_index + 1),
        "track_title": None if track_index is None else f"Track {track_index + 1}",
        "credit_scope": scope,
        "artist_id": artist_id,
        "name": name,
        "anv": None,
        "join_text": None,
        "role_text": role_text,
        "credited_tracks_text": None,
        "is_linked": True,
        "playable_identity": True,
    }


def _co_billed(release_id: int, *, artist_id: int, name: str, role: str) -> list[dict]:
    return [
        _credit(release_id, artist_id=artist_id, name=name, scope="release_artist", role_text=None),
        _credit(
            release_id,
            artist_id=artist_id,
            name=name,
            scope="track_artist",
            role_text=role,
            track_index=0,
        ),
    ]


RELEASES = [
    _release(1, "Alpha's Album"),
    _release(2, "Bravo's Album"),
    _release(3, "Delta's Album"),
    _release(4, "Cara Solo"),
    _release(5, "Eve Solo"),
]
CREDITS = [
    *_co_billed(1, artist_id=100, name="Alice", role="Vocals"),
    *_co_billed(1, artist_id=200, name="Bob", role="Guitar"),
    *_co_billed(2, artist_id=200, name="Bob", role="Bass"),
    *_co_billed(2, artist_id=300, name="Cara", role="Drums"),
    *_co_billed(3, artist_id=400, name="Dan", role="Piano"),
    *_co_billed(3, artist_id=500, name="Eve", role="Vocals"),
    *_co_billed(4, artist_id=300, name="Cara", role="Vocals"),
    *_co_billed(5, artist_id=500, name="Eve", role="Vocals"),
]
ALBUMS = [
    {"artist": "Alice", "title": "Alpha's Album"},
    {"artist": "Bob", "title": "Bravo's Album"},
    {"artist": "Cara", "title": "Cara Solo"},
    {"artist": "Dan", "title": "Delta's Album"},
    {"artist": "Eve", "title": "Eve Solo"},
]


@pytest.fixture
def routes_dataset_root(tmp_path: Path) -> Path:
    from conftest import write_synthetic_dataset

    return write_synthetic_dataset(
        tmp_path / f"snapshot={SNAPSHOT_DATE}", release_rows=RELEASES, credit_rows=CREDITS
    )


def _build(routes_dataset_root: Path):
    with CreditGraph.open(routes_dataset_root) as graph:
        matched, missed = match_albums(graph, ALBUMS)
        assert missed == []
        return build_record_routes_pool(
            graph,
            matched,
            one_hop_target=10,
            two_hop_target=10,
            snapshot_date=SNAPSHOT_DATE,
            generated_by="test",
            catalog_version="test-catalog-v1",
            max_endpoint_share=1.0,
            max_bridge_share=1.0,
        )


def test_builds_a_valid_pool_with_content_derived_ids(routes_dataset_root: Path) -> None:
    universe, rounds, diagnostics = _build(routes_dataset_root)
    assert diagnostics["one_hop_selected"] == 3
    assert diagnostics["two_hop_selected"] == 1
    validate_record_routes_artifact(universe, rounds)  # does not raise

    for route in rounds["rounds"]:
        assert route["id"].startswith("route-")
        assert route["id"] == stable_route_id(route)
        assert route["id"] == recomputed_route_id(route)


def test_ids_are_never_ordinal(routes_dataset_root: Path) -> None:
    _universe, rounds, _diag = _build(routes_dataset_root)
    for route in rounds["rounds"]:
        assert not route["id"].startswith("round-")


def test_mode_is_set_on_both_artifacts(routes_dataset_root: Path) -> None:
    universe, rounds, _diag = _build(routes_dataset_root)
    assert universe["mode"] == RECORD_ROUTES_MODE == "record_routes"
    assert rounds["mode"] == RECORD_ROUTES_MODE


def test_albums_are_art_free(routes_dataset_root: Path) -> None:
    universe, _rounds, _diag = _build(routes_dataset_root)
    for album in universe["albums"]:
        assert "cover_image" not in album
        assert "art" not in album


def test_regeneration_is_byte_identical_except_nothing_random(
    routes_dataset_root: Path,
) -> None:
    universe_a, rounds_a, _ = _build(routes_dataset_root)
    universe_b, rounds_b, _ = _build(routes_dataset_root)
    assert universe_a == universe_b
    assert rounds_a == rounds_b


def test_two_hop_route_has_a_real_bridge_artist(routes_dataset_root: Path) -> None:
    _universe, rounds, _diag = _build(routes_dataset_root)
    two_hop = next(r for r in rounds["rounds"] if r["kind"] == "two_hop")
    hop0, hop1 = two_hop["hops"]
    bridge_candidates_0 = {hop0["artist_a_id"], hop0["artist_b_id"]}
    bridge_candidates_1 = {hop1["artist_a_id"], hop1["artist_b_id"]}
    bridge = bridge_candidates_0 & bridge_candidates_1
    assert bridge == {200}  # Bob


def test_reordering_the_rounds_array_changes_artifact_version(
    routes_dataset_root: Path,
) -> None:
    universe, rounds, _diag = _build(routes_dataset_root)
    forward = record_routes_artifact_version(
        albums=universe["albums"],
        rounds_json=rounds["rounds"],
        releases=rounds["releases"],
        artists=rounds["artists"],
        snapshot_date=SNAPSHOT_DATE,
    )
    reversed_version = record_routes_artifact_version(
        albums=universe["albums"],
        rounds_json=list(reversed(rounds["rounds"])),
        releases=rounds["releases"],
        artists=rounds["artists"],
        snapshot_date=SNAPSHOT_DATE,
    )
    assert forward != reversed_version


def test_evidence_only_change_moves_artifact_version(routes_dataset_root: Path) -> None:
    """The exact gap the redefinition closes: a silent edit to a displayed
    artist name or release title (evidentiary content living in the
    separate releases[]/artists[] arrays, not inside rounds[] itself) must
    move artifact_version, not be invisible to it."""
    universe, rounds, _diag = _build(routes_dataset_root)
    baseline = record_routes_artifact_version(
        albums=universe["albums"],
        rounds_json=rounds["rounds"],
        releases=rounds["releases"],
        artists=rounds["artists"],
        snapshot_date=SNAPSHOT_DATE,
    )

    renamed_artists = [dict(a) for a in rounds["artists"]]
    renamed_artists[0]["name"] = renamed_artists[0]["name"] + " (corrected)"
    artist_renamed = record_routes_artifact_version(
        albums=universe["albums"],
        rounds_json=rounds["rounds"],
        releases=rounds["releases"],
        artists=renamed_artists,
        snapshot_date=SNAPSHOT_DATE,
    )
    assert artist_renamed != baseline

    retitled_releases = [dict(r) for r in rounds["releases"]]
    retitled_releases[0]["title"] = retitled_releases[0]["title"] + " (reissue)"
    release_retitled = record_routes_artifact_version(
        albums=universe["albums"],
        rounds_json=rounds["rounds"],
        releases=retitled_releases,
        artists=rounds["artists"],
        snapshot_date=SNAPSHOT_DATE,
    )
    assert release_retitled != baseline

    retitled_albums = [dict(a) for a in universe["albums"]]
    retitled_albums[0]["title"] = retitled_albums[0]["title"] + " (deluxe)"
    album_retitled = record_routes_artifact_version(
        albums=retitled_albums,
        rounds_json=rounds["rounds"],
        releases=rounds["releases"],
        artists=rounds["artists"],
        snapshot_date=SNAPSHOT_DATE,
    )
    assert album_retitled != baseline


def test_reversed_orientation_is_a_different_id_by_design(
    routes_dataset_root: Path,
) -> None:
    """Pins the documented design decision (stable_route_id's docstring):
    the same conceptual two-hop path, traversed in the opposite direction
    (hops reversed), hashes to a DIFFERENT route id. This is intentional --
    from/to is tied to which album renders as sleeve A vs. B -- not
    accidental fragility."""
    _universe, rounds, _diag = _build(routes_dataset_root)
    two_hop = next(r for r in rounds["rounds"] if r["kind"] == "two_hop")
    forward_id = stable_route_id(two_hop)

    reversed_route = dict(two_hop)
    reversed_route["from_album_id"], reversed_route["to_album_id"] = (
        two_hop["to_album_id"],
        two_hop["from_album_id"],
    )
    reversed_route["from_artist_id"], reversed_route["to_artist_id"] = (
        two_hop["to_artist_id"],
        two_hop["from_artist_id"],
    )
    reversed_route["hops"] = list(reversed(two_hop["hops"]))
    reversed_id = stable_route_id(reversed_route)

    assert reversed_id != forward_id


def test_pool_version_is_membership_only(routes_dataset_root: Path) -> None:
    _universe, rounds, _diag = _build(routes_dataset_root)
    ids = [r["id"] for r in rounds["rounds"]]
    forward = record_routes_pool_version(ids, SNAPSHOT_DATE)
    shuffled = record_routes_pool_version(list(reversed(ids)), SNAPSHOT_DATE)
    assert forward == shuffled  # membership hash sorts internally


def test_validator_rejects_a_hand_edited_ordinal_id(routes_dataset_root: Path) -> None:
    universe, rounds, _diag = _build(routes_dataset_root)
    rounds["rounds"][0]["id"] = "round-000001"
    with pytest.raises(RecordRoutesValidationError, match="content-derived"):
        validate_record_routes_artifact(universe, rounds)


def test_dependency_free_mirror_agrees(routes_dataset_root: Path) -> None:
    universe, rounds, _diag = _build(routes_dataset_root)
    assert record_routes_failures(universe, rounds) == []


def test_no_eligible_routes_raises(routes_dataset_root: Path) -> None:
    with CreditGraph.open(routes_dataset_root) as graph:
        matched, _missed = match_albums(graph, [{"artist": "Alice", "title": "Alpha's Album"}])
        with pytest.raises(RecordRoutesValidationError, match="no eligible"):
            build_record_routes_pool(
                graph,
                matched,
                one_hop_target=10,
                two_hop_target=10,
                snapshot_date=SNAPSHOT_DATE,
                generated_by="test",
            )
