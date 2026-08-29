"""Phase 7 PR D, Slice 3: `compare_scenes`, reusing test_compare.py's
synthetic fixture. A scene is a user-authored, labelled set of artist ids
-- most of the comparison logic here is direct reuse of _network_overlap/
_route_between at N-member scale, not new graph logic."""

from __future__ import annotations

from pathlib import Path

import pytest

from networked_players_graph_core.graph import CreditGraph
from networked_players_research.compare import (
    CompareError,
    CompareScenesRequest,
    compare_scenes,
)

from .test_compare import BOB, CAROL, DAN, EVE, FRANK, SEED_A, SEED_B, SEED_F, _build_corpus


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    return _build_corpus(tmp_path)


def test_overlap_and_separation_finds_a_real_shared_member(corpus: Path) -> None:
    scene_a = (SEED_A, CAROL)
    scene_b = (CAROL, SEED_B)
    with CreditGraph.open(corpus) as graph:
        result = compare_scenes(graph, CompareScenesRequest(corpus, scene_a, scene_b))

    assert result["overlap_and_separation"]["overlap_artist_ids"] == [CAROL]
    assert result["overlap_and_separation"]["unique_to_scene_a"] == [SEED_A]
    assert result["overlap_and_separation"]["unique_to_scene_b"] == [SEED_B]


def test_unresolved_members_are_reported_not_fatal(corpus: Path) -> None:
    scene_a = (SEED_A, 999_999)  # 999999 has no credits anywhere
    scene_b = (SEED_B,)
    with CreditGraph.open(corpus) as graph:
        result = compare_scenes(graph, CompareScenesRequest(corpus, scene_a, scene_b))

    assert result["scene_a"]["resolved_artist_ids"] == [SEED_A]
    assert result["scene_a"]["unresolved_artist_ids"] == [999_999]
    assert result["scene_a"]["member_artist_ids"] == [SEED_A, 999_999]


def test_a_scene_that_is_entirely_unresolved_raises_compare_error(corpus: Path) -> None:
    with CreditGraph.open(corpus) as graph:
        with pytest.raises(CompareError):
            compare_scenes(graph, CompareScenesRequest(corpus, (999_999, 999_998), (SEED_B,)))


def test_an_empty_scene_raises_compare_error(corpus: Path) -> None:
    with CreditGraph.open(corpus) as graph:
        with pytest.raises(CompareError):
            compare_scenes(graph, CompareScenesRequest(corpus, (), (SEED_B,)))


def test_connecting_releases_finds_a_real_direct_co_credit(corpus: Path) -> None:
    # Seed A and Bob are BOTH credited on R1 (Bob release_credit, Seed A
    # release_artist) -- a real shared release, without Bob/Seed A being
    # the SAME identity (that's overlap, tested separately above).
    scene_a = (SEED_A,)
    scene_b = (BOB,)
    with CreditGraph.open(corpus) as graph:
        result = compare_scenes(graph, CompareScenesRequest(corpus, scene_a, scene_b))

    assert result["connecting_releases"]["release_ids"] == [1]


def test_connecting_releases_is_empty_when_scenes_share_no_release(corpus: Path) -> None:
    scene_a = (SEED_F,)  # R6 only, fully isolated fixture release
    scene_b = (SEED_A,)  # R1/R4/R5
    with CreditGraph.open(corpus) as graph:
        result = compare_scenes(graph, CompareScenesRequest(corpus, scene_a, scene_b))

    assert result["connecting_releases"] == {"count": 0, "release_ids": []}


def test_shared_collaborators_reuses_network_overlap_at_scene_scale(corpus: Path) -> None:
    # Dan (R4) and Eve/Frank aren't directly related, but Carol bridges
    # Seed A's scene to Dan's scene the same way she does for two single
    # artists -- proving the reuse holds at N-member scale too.
    scene_a = (SEED_A,)
    scene_b = (DAN, EVE, FRANK)
    with CreditGraph.open(corpus) as graph:
        result = compare_scenes(graph, CompareScenesRequest(corpus, scene_a, scene_b))

    assert CAROL in result["shared_collaborators"]["artist_ids"]


def test_routes_between_sets_finds_a_real_route(corpus: Path) -> None:
    scene_a = (SEED_A,)
    scene_b = (DAN,)
    with CreditGraph.open(corpus) as graph:
        result = compare_scenes(graph, CompareScenesRequest(corpus, scene_a, scene_b))

    assert result["routes_between_sets"]["case"] == "found"


def test_role_category_counts_are_unioned_across_scene_members(corpus: Path) -> None:
    # Bob (Engineer) + Seed A (Vocals) -- both real, distinct categories,
    # neither one out-weighing the other just because they're in one scene.
    scene_a = (SEED_A, BOB)
    scene_b = (SEED_B,)
    with CreditGraph.open(corpus) as graph:
        result = compare_scenes(graph, CompareScenesRequest(corpus, scene_a, scene_b))

    counts = result["scene_a"]["role_category_counts"]
    assert counts.get("vocals") == 1
    assert counts.get("engineering") == 1
