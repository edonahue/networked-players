from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from networked_players_graph_core.challenge import match_albums
from networked_players_graph_core.graph import CreditGraph
from networked_players_graph_core.rounds import (
    ROUNDS_SCHEMA_VERSION,
    build_rounds_v1,
    validate_rounds_artifact,
)
from networked_players_graph_core.rounds_generator import generate_round_pool

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
    scope: str,
    role_text: str | None,
    track_index: int | None = None,
) -> dict[str, Any]:
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


def _co_billed(release_id: int, *, artist_id: int, name: str, role: str) -> list[dict[str, Any]]:
    """A billed contributor to a release: a release_artist row (billed) plus
    a track_artist row on the same track carrying the explicit performer role
    that satisfies is_performer_role. Two artists both credited this way on
    the same release/track are what `credit_edges_sql`'s `co_performers` rule
    connects (both billed *and* both performers on the same recording) --
    a track-only guest credit alone does not qualify."""
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


# Fixture graph:
#   Release 1 "Alpha's Album" -- Alice(100, Vocals) & Bob(200, Guitar) co-billed
#   Release 2 "Bravo's Album" -- Bob(200, Bass) & Cara(300, Drums) co-billed
#   Release 4 "Cara Solo" -- Cara(300, Vocals) alone -- her own backbone album
#   Release 3 "Delta's Album" -- Dan(400, Piano) & Eve(500, Vocals) co-billed
#   Release 5 "Eve Solo" -- Eve(500, Vocals) alone -- her own backbone album
#
# One-hop pairs: Alice-Bob (release 1), Bob-Cara (release 2), Dan-Eve (release 3).
# Two-hop: Alice-Cara via bridge Bob (release 1 + release 2), no direct edge.
# Fully disconnected from the Alice/Bob/Cara/Dan/Eve cluster: nothing else.
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
def rounds_dataset_root(tmp_path: Path) -> Path:
    from conftest import write_synthetic_dataset

    return write_synthetic_dataset(
        tmp_path / f"snapshot={SNAPSHOT_DATE}", release_rows=RELEASES, credit_rows=CREDITS
    )


def test_generate_round_pool_finds_one_and_two_hop_rounds(rounds_dataset_root: Path) -> None:
    with CreditGraph.open(rounds_dataset_root) as graph:
        matched, missed = match_albums(graph, ALBUMS)
        assert missed == []
        rounds, diagnostics = generate_round_pool(
            graph,
            matched,
            one_hop_target=10,
            two_hop_target=10,
            max_endpoint_share=1.0,
            max_bridge_share=1.0,
        )

    assert diagnostics["one_hop_candidates_found"] == 3  # Alice-Bob, Bob-Cara, Dan-Eve
    assert diagnostics["two_hop_candidates_found"] == 1  # Alice-Cara via Bob
    kinds = [r["kind"] for r in rounds]
    assert kinds.count("one_hop") == 3
    assert kinds.count("two_hop") == 1

    two_hop = next(r for r in rounds if r["kind"] == "two_hop")
    endpoint_ids = {two_hop["from_artist_id"], two_hop["to_artist_id"]}
    assert endpoint_ids == {100, 300}
    bridge_hop = two_hop["hops"][0]
    assert bridge_hop["artist_b_id"] == 200  # Bob is the bridge


def test_generate_round_pool_never_pads_past_available_candidates(
    rounds_dataset_root: Path,
) -> None:
    with CreditGraph.open(rounds_dataset_root) as graph:
        matched, _ = match_albums(graph, ALBUMS)
        rounds, diagnostics = generate_round_pool(
            graph,
            matched,
            one_hop_target=100,
            two_hop_target=100,
            max_endpoint_share=1.0,
            max_bridge_share=1.0,
        )
    assert diagnostics["one_hop_selected"] == 3
    assert diagnostics["two_hop_selected"] == 1
    assert len(rounds) == 4


def test_generate_round_pool_diversity_cap_limits_endpoint_repetition(
    rounds_dataset_root: Path,
) -> None:
    """With the default max_endpoint_share, Bob (the only artist common to
    two one-hop candidates -- Alice-Bob and Bob-Cara) can't headline both;
    the cap forces a choice rather than letting one artist dominate."""
    with CreditGraph.open(rounds_dataset_root) as graph:
        matched, _ = match_albums(graph, ALBUMS)
        rounds, diagnostics = generate_round_pool(
            graph, matched, one_hop_target=10, two_hop_target=0
        )
    assert diagnostics["one_hop_candidates_found"] == 3
    assert diagnostics["one_hop_selected"] == 2
    bob_appearances = sum(1 for r in rounds if 200 in (r["from_artist_id"], r["to_artist_id"]))
    assert bob_appearances == 1


def test_generate_round_pool_respects_smaller_targets(rounds_dataset_root: Path) -> None:
    with CreditGraph.open(rounds_dataset_root) as graph:
        matched, _ = match_albums(graph, ALBUMS)
        rounds, diagnostics = generate_round_pool(
            graph, matched, one_hop_target=1, two_hop_target=0
        )
    assert diagnostics["one_hop_selected"] == 1
    assert diagnostics["two_hop_selected"] == 0
    assert len(rounds) == 1


def test_generate_round_pool_applies_family_exclusion(rounds_dataset_root: Path) -> None:
    def is_family_excluded(a: int, b: int) -> bool:
        return {a, b} == {100, 200}  # Alice and Bob treated as the same act

    with CreditGraph.open(rounds_dataset_root) as graph:
        matched, _ = match_albums(graph, ALBUMS)
        rounds, diagnostics = generate_round_pool(
            graph,
            matched,
            one_hop_target=10,
            two_hop_target=10,
            is_family_excluded=is_family_excluded,
        )

    pairs = {frozenset((r["from_artist_id"], r["to_artist_id"])) for r in rounds}
    assert frozenset((100, 200)) not in pairs
    # The Alice-Cara two-hop bridge depends on the excluded Alice-Bob edge
    # only for *discovery* via bob's neighbor set, not for exclusion itself --
    # excluding the endpoint pair (100,200) must not accidentally remove the
    # unrelated two-hop pair (100,300).
    assert diagnostics["one_hop_candidates_found"] == 2


def test_generate_round_pool_gates_two_hop_bridge_by_format_policy(
    rounds_dataset_root: Path,
) -> None:
    with CreditGraph.open(rounds_dataset_root) as graph:
        matched, _ = match_albums(graph, ALBUMS)
        # Release 2 (Bravo's Album, the second bridge hop for Alice-Cara) is
        # not in the allow-list -- the two-hop candidate must disappear.
        rounds, diagnostics = generate_round_pool(
            graph,
            matched,
            one_hop_target=10,
            two_hop_target=10,
            allowed_release_ids=frozenset({1, 3, 4, 5}),
        )
    assert diagnostics["two_hop_candidates_found"] == 0
    assert all(r["kind"] == "one_hop" for r in rounds)


def test_generate_round_pool_assigns_sequential_ids_and_distractors(
    rounds_dataset_root: Path,
) -> None:
    with CreditGraph.open(rounds_dataset_root) as graph:
        matched, _ = match_albums(graph, ALBUMS)
        rounds, _ = generate_round_pool(graph, matched, one_hop_target=10, two_hop_target=10)

    ids = [r["id"] for r in rounds]
    assert ids == [f"round-{i:06d}" for i in range(1, len(rounds) + 1)]
    # Dan-Eve round: Alice/Bob/Cara albums are all legitimate distractors
    # (genuinely no known path to either Dan or Eve in this fixture).
    dan_eve_round = next(
        r for r in rounds if {r["from_artist_id"], r["to_artist_id"]} == {400, 500}
    )
    assert len(dan_eve_round["distractors"]) > 0
    distractor_album_ids = {d["album_id"] for d in dan_eve_round["distractors"]}
    assert "release-3" not in distractor_album_ids  # Dan's own album never distracts itself
    assert "release-5" not in distractor_album_ids  # nor Eve's


def test_build_rounds_v1_produces_a_valid_artifact_pair(rounds_dataset_root: Path) -> None:
    with CreditGraph.open(rounds_dataset_root) as graph:
        matched, _ = match_albums(graph, ALBUMS)
        rounds_json, _ = generate_round_pool(
            graph,
            matched,
            one_hop_target=10,
            two_hop_target=10,
            max_endpoint_share=1.0,
            max_bridge_share=1.0,
        )
        universe, rounds = build_rounds_v1(
            graph,
            matched,
            rounds_json,
            snapshot_date=SNAPSHOT_DATE,
            generated_by="test-suite",
            pool_version="rounds-v1-test",
        )

    validate_rounds_artifact(universe, rounds)
    assert universe["schema_version"] == ROUNDS_SCHEMA_VERSION
    assert universe["counts"] == {"one_hop": 3, "two_hop": 1, "daily_eligible": 4}
    # All 5 backbone albums are round endpoints in this fixture.
    assert {a["id"] for a in universe["albums"]} == {a.album_id for a in matched}
    assert len(rounds["rounds"]) == 4
    # Evidence releases are deduped: release 1 and 2 each justify a one-hop
    # round AND are reused as the two-hop bridge's own hop evidence.
    release_ids = {r["release_id"] for r in rounds["releases"]}
    assert release_ids == {1, 2, 3}


def test_build_rounds_v1_only_includes_endpoints_and_real_distractors(
    rounds_dataset_root: Path,
) -> None:
    """Every album in the published universe is either a round endpoint or a
    genuine distractor of a published round -- never an album that matched
    the snapshot but has no role in the pool at all."""
    with CreditGraph.open(rounds_dataset_root) as graph:
        matched, _ = match_albums(graph, ALBUMS)
        rounds_json, _ = generate_round_pool(graph, matched, one_hop_target=1, two_hop_target=0)
        universe, rounds = build_rounds_v1(
            graph,
            matched,
            rounds_json,
            snapshot_date=SNAPSHOT_DATE,
            generated_by="test-suite",
            pool_version="rounds-v1-test",
        )

    validate_rounds_artifact(universe, rounds)
    assert len(rounds_json) == 1
    expected_ids = {rounds_json[0]["from_album_id"], rounds_json[0]["to_album_id"]}
    expected_ids |= {d["album_id"] for d in rounds_json[0]["distractors"]}
    assert {a["id"] for a in universe["albums"]} == expected_ids
    # The winning round is Alice-Bob (deterministic tie-break); Cara Solo
    # (release-4) never appears even as a distractor, since Cara *is*
    # one-hop connected to Bob -- a real connection is never mislabeled as a
    # "no known path" decoy just because it wasn't the selected round.
    assert "release-4" not in expected_ids
