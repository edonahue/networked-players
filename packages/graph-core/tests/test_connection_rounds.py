from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from networked_players_graph_core.connection_rounds import (
    ConnectionRoundsValidationError,
    build_connection_universe_and_rounds,
    generate_connection_round_pool,
    validate_connection_rounds_artifact,
)
from networked_players_graph_core.graph import CreditGraph

SNAPSHOT_DATE = "20260601"


def _release(release_id: int, title: str) -> dict[str, Any]:
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
    role_text: str | None,
    scope: str = "release_credit",
) -> dict[str, Any]:
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "release_id": release_id,
        "track_index": None,
        "track_path": None,
        "track_position": None,
        "track_title": None,
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


def _album(
    album_id: str, *, artist_id: int, artist: str, title: str, release_id: int, year: int
) -> dict[str, Any]:
    return {
        "id": album_id,
        "master_id": None,
        "main_release_id": release_id,
        "title": title,
        "artist_id": artist_id,
        "artist": artist,
        "year": year,
        "cover_image": None,
    }


# Fixture graph (album-centered, distinct from test_rounds_generator.py's
# artist-path fixture): a real performer explicitly credited on BOTH
# displayed albums is what makes a one-hop round, not a shared release with a
# third artist.
#
#   Album A "First Light"  (release 1) -- billed Alice(100); performers
#     Xavier(700, Guitar), Walt(750, Drums, distractor-only)
#   Album C "Third Wave"   (release 2) -- billed Cara(300); performers
#     Xavier(700, Guitar) [shared with A], Uma(760, Bass, distractor-only)
#   Album D "Fourth Chapter" (release 4) -- billed Dan(400); performers
#     Yara(800, Drums), Vic(770, Keys, distractor-only)
#   Album M "Second Set"   (release 3) -- billed Bob(200); performers
#     Yara(800, Drums) [shared with D], Zack(900, Organ) [shared with E]
#   Album E "Fifth Session" (release 5) -- billed Eve(500); performers
#     Zack(900, Organ) [shared with M], Tia(780, Sax, distractor-only)
#   Album N "No Shared Performer" (release 6) -- billed Ned(600); performer
#     Fully isolated -- Nea(950, Cello) shares nothing with anyone.
#
# One-hop pairs:  A<->C (Xavier), D<->M (Yara), M<->E (Zack)
# Two-hop pair:   D<->E via the unique middle M (no direct D<->E performer)
# A<->D, A<->E, C<->D, C<->E, *<->N: no shared performer at all.
RELEASES = [
    _release(1, "First Light"),
    _release(2, "Third Wave"),
    _release(3, "Second Set"),
    _release(4, "Fourth Chapter"),
    _release(5, "Fifth Session"),
    _release(6, "No Shared Performer"),
]
CREDITS = [
    _credit(1, artist_id=100, name="Alice", role_text=None, scope="release_artist"),
    _credit(1, artist_id=700, name="Xavier", role_text="Guitar"),
    _credit(1, artist_id=750, name="Walt", role_text="Drums"),
    _credit(2, artist_id=300, name="Cara", role_text=None, scope="release_artist"),
    _credit(2, artist_id=700, name="Xavier", role_text="Guitar"),
    _credit(2, artist_id=760, name="Uma", role_text="Bass"),
    _credit(3, artist_id=200, name="Bob", role_text=None, scope="release_artist"),
    _credit(3, artist_id=800, name="Yara", role_text="Drums"),
    _credit(3, artist_id=900, name="Zack", role_text="Organ"),
    _credit(4, artist_id=400, name="Dan", role_text=None, scope="release_artist"),
    _credit(4, artist_id=800, name="Yara", role_text="Drums"),
    _credit(4, artist_id=770, name="Vic", role_text="Keyboards"),
    _credit(5, artist_id=500, name="Eve", role_text=None, scope="release_artist"),
    _credit(5, artist_id=900, name="Zack", role_text="Organ"),
    _credit(5, artist_id=780, name="Tia", role_text="Saxophone"),
    _credit(6, artist_id=600, name="Ned", role_text=None, scope="release_artist"),
    _credit(6, artist_id=950, name="Nea", role_text="Cello"),
    # A non-performer credit (Producer) must never surface as an answer or a
    # distractor -- is_performer_role excludes it before it reaches the pool.
    _credit(1, artist_id=999, name="Prod Perry", role_text="Producer"),
]

ALBUMS = [
    _album("album-a", artist_id=100, artist="Alice", title="First Light", release_id=1, year=1995),
    _album("album-c", artist_id=300, artist="Cara", title="Third Wave", release_id=2, year=1996),
    _album("album-m", artist_id=200, artist="Bob", title="Second Set", release_id=3, year=1997),
    _album("album-d", artist_id=400, artist="Dan", title="Fourth Chapter", release_id=4, year=1998),
    _album("album-e", artist_id=500, artist="Eve", title="Fifth Session", release_id=5, year=1999),
    _album(
        "album-n", artist_id=600, artist="Ned", title="No Shared Performer", release_id=6, year=2000
    ),
]


@pytest.fixture
def dataset_root(tmp_path: Path) -> Path:
    from conftest import write_synthetic_dataset

    return write_synthetic_dataset(
        tmp_path / f"snapshot={SNAPSHOT_DATE}", release_rows=RELEASES, credit_rows=CREDITS
    )


def test_generate_finds_one_and_two_hop_rounds(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        # Disable diversity caps -- this 6-album fixture is far below the
        # scale those caps are meant for (matches test_rounds_generator.py's
        # own precedent), and this test wants every real candidate selected.
        rounds, diagnostics = generate_connection_round_pool(
            graph,
            ALBUMS,
            one_hop_target=10,
            two_hop_target=10,
            max_endpoint_share=1.0,
            max_bridge_share=1.0,
        )
    assert diagnostics["one_hop_candidates_found"] == 3  # A-C, D-M, M-E
    assert diagnostics["two_hop_candidates_found"] == 1  # D-E via M
    one_hop_pairs = {
        frozenset((r["endpoints"][0]["id"], r["endpoints"][1]["id"]))
        for r in rounds
        if r["kind"] == "one_hop"
    }
    assert one_hop_pairs == {
        frozenset({"album-a", "album-c"}),
        frozenset({"album-d", "album-m"}),
        frozenset({"album-m", "album-e"}),
    }
    two_hop = [r for r in rounds if r["kind"] == "two_hop"]
    assert len(two_hop) == 1
    assert {two_hop[0]["endpoints"][0]["id"], two_hop[0]["endpoints"][1]["id"]} == {
        "album-d",
        "album-e",
    }
    assert two_hop[0]["middle"]["album"]["id"] == "album-m"


def test_one_hop_answer_is_the_real_shared_performer(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        rounds, _ = generate_connection_round_pool(
            graph, ALBUMS, one_hop_target=10, two_hop_target=10
        )
    ac_round = next(
        r
        for r in rounds
        if r["kind"] == "one_hop"
        and {r["endpoints"][0]["id"], r["endpoints"][1]["id"]} == {"album-a", "album-c"}
    )
    assert [a["id"] for a in ac_round["answer_set"]] == [700]
    assert ac_round["answer_set"][0]["name"] == "Xavier"
    assert ac_round["answer_set"][0]["role_category"] == "guitar"


def test_non_performer_credit_never_surfaces(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        rounds, _ = generate_connection_round_pool(
            graph, ALBUMS, one_hop_target=10, two_hop_target=10
        )
    for round_json in rounds:
        ids = {a["id"] for a in round_json["answer_set"]} | {
            d["id"] for d in round_json["distractors"]
        }
        for bridge_set in round_json.get("bridge_answer_sets") or []:
            ids |= {a["id"] for a in bridge_set}
        assert 999 not in ids


def test_distractors_never_satisfy_the_connection(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        rounds, _ = generate_connection_round_pool(
            graph, ALBUMS, one_hop_target=10, two_hop_target=10
        )
    for round_json in rounds:
        answer_ids = {a["id"] for a in round_json["answer_set"]}
        for bridge_set in round_json.get("bridge_answer_sets") or []:
            answer_ids |= {a["id"] for a in bridge_set}
        distractor_ids = {d["id"] for d in round_json["distractors"]}
        assert not (answer_ids & distractor_ids)


def test_family_exclusion_drops_the_pair(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        rounds, diagnostics = generate_connection_round_pool(
            graph,
            ALBUMS,
            one_hop_target=10,
            two_hop_target=10,
            is_family_excluded=lambda a, b: {a, b} == {100, 300},
        )
    assert diagnostics["one_hop_candidates_found"] == 2
    pairs = {frozenset((r["endpoints"][0]["id"], r["endpoints"][1]["id"])) for r in rounds}
    assert frozenset({"album-a", "album-c"}) not in pairs


def test_isolated_album_never_becomes_a_round_endpoint(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        rounds, _ = generate_connection_round_pool(
            graph, ALBUMS, one_hop_target=10, two_hop_target=10
        )
    referenced = set()
    for r in rounds:
        referenced.add(r["endpoints"][0]["id"])
        referenced.add(r["endpoints"][1]["id"])
    assert "album-n" not in referenced


def test_build_universe_only_includes_round_referenced_albums(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        rounds_json, _ = generate_connection_round_pool(
            graph, ALBUMS, one_hop_target=10, two_hop_target=10
        )
    universe, rounds = build_connection_universe_and_rounds(
        ALBUMS, rounds_json, snapshot_date=SNAPSHOT_DATE, generated_by="test"
    )
    # The universe is built exactly from what the rounds reference (endpoint,
    # middle, or a decoy middle choice) -- never padded with every input
    # album regardless of use. album-n has no shared performer with anything
    # but can still legitimately appear as a two-hop decoy choice (any other
    # real album is a valid "not the hidden middle" option), so this checks
    # exact equality against the real reference set, not a hand-picked subset.
    referenced_ids: set[str] = set()
    for round_json in rounds_json:
        referenced_ids.add(round_json["endpoints"][0]["id"])
        referenced_ids.add(round_json["endpoints"][1]["id"])
        middle = round_json.get("middle")
        if middle:
            referenced_ids.add(middle["album"]["id"])
            referenced_ids.update(c["id"] for c in middle["choices"])
    album_ids = {a["id"] for a in universe["albums"]}
    assert album_ids == referenced_ids
    assert {"album-a", "album-c", "album-d", "album-m", "album-e"} <= album_ids
    validate_connection_rounds_artifact(universe, rounds)  # does not raise


def test_validate_rejects_answer_without_evidence(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        rounds_json, _ = generate_connection_round_pool(
            graph, ALBUMS, one_hop_target=10, two_hop_target=10
        )
    universe, rounds = build_connection_universe_and_rounds(
        ALBUMS, rounds_json, snapshot_date=SNAPSHOT_DATE, generated_by="test"
    )
    rounds["rounds"][0]["evidence"] = []
    with pytest.raises(ConnectionRoundsValidationError, match="lacks evidence"):
        validate_connection_rounds_artifact(universe, rounds)


def test_validate_rejects_wrong_pool_label(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        rounds_json, _ = generate_connection_round_pool(
            graph, ALBUMS, one_hop_target=10, two_hop_target=10
        )
    universe, rounds = build_connection_universe_and_rounds(
        ALBUMS, rounds_json, snapshot_date=SNAPSHOT_DATE, generated_by="test"
    )
    rounds["rounds"][0]["pool"] = "synthetic-universe"
    with pytest.raises(ConnectionRoundsValidationError, match="real-records"):
        validate_connection_rounds_artifact(universe, rounds)


def test_validate_rejects_forbidden_substring(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        rounds_json, _ = generate_connection_round_pool(
            graph, ALBUMS, one_hop_target=10, two_hop_target=10
        )
    universe, rounds = build_connection_universe_and_rounds(
        ALBUMS, rounds_json, snapshot_date=SNAPSHOT_DATE, generated_by="test"
    )
    universe["provenance"]["note"] += " see /home/erich/notes"
    with pytest.raises(ConnectionRoundsValidationError, match="forbidden substring"):
        validate_connection_rounds_artifact(universe, rounds)


def test_no_eligible_pairs_returns_empty_pool(tmp_path: Path) -> None:
    from conftest import write_synthetic_dataset

    root = write_synthetic_dataset(
        tmp_path / f"snapshot={SNAPSHOT_DATE}",
        release_rows=[_release(1, "Solo Album")],
        credit_rows=[
            _credit(1, artist_id=100, name="Alice", role_text=None, scope="release_artist")
        ],
    )
    solo_album = [
        _album(
            "album-a", artist_id=100, artist="Alice", title="Solo Album", release_id=1, year=1995
        )
    ]
    with CreditGraph.open(root, build_edges=False) as graph:
        rounds, diagnostics = generate_connection_round_pool(
            graph, solo_album, one_hop_target=10, two_hop_target=10
        )
    assert rounds == []
    assert diagnostics["one_hop_candidates_found"] == 0
