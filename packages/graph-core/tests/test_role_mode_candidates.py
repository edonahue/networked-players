from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from networked_players_graph_core.graph import CreditGraph
from networked_players_graph_core.role_mode_candidates import measure_candidates

SNAPSHOT_DATE = "20260601"


def _credit(
    release_id: int,
    artist_id: int,
    name: str,
    role_text: str | None,
) -> dict[str, Any]:
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "release_id": release_id,
        "track_index": None,
        "track_path": None,
        "track_position": None,
        "track_title": None,
        "credit_scope": "release_artist",
        "artist_id": artist_id,
        "name": name,
        "anv": None,
        "join_text": None,
        "role_text": role_text,
        "credited_tracks_text": None,
        "is_linked": True,
        "playable_identity": True,
    }


def _release(release_id: int, title: str) -> dict[str, Any]:
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "release_id": release_id,
        "status": "Accepted",
        "title": title,
        "country": None,
        "released": None,
        "master_id": release_id,
        "master_is_main_release": True,
        "data_quality": None,
        "source_url": f"https://example.invalid/release/{release_id}",
    }


@pytest.fixture
def dataset_root(tmp_path: Path) -> Path:
    """Three albums: 1<->2 share an engineer (Behind the Glass candidate),
    2<->3 share a drummer (Rhythm Section candidate), 1<->3 share nothing
    directly -- but bridge through album 2 for both modes (a real two-hop
    candidate for each)."""
    from conftest import write_synthetic_dataset

    releases = [_release(1, "Album One"), _release(2, "Album Two"), _release(3, "Album Three")]
    credits = [
        _credit(1, 100, "Alice", "Vocals"),
        _credit(1, 200, "Bob", "Mixed By"),
        _credit(2, 200, "Bob", "Mixed By"),
        _credit(2, 300, "Cara", "Drums"),
        _credit(3, 300, "Cara", "Drums"),
        _credit(3, 400, "Dan", "Vocals"),
    ]
    return write_synthetic_dataset(
        tmp_path / f"snapshot={SNAPSHOT_DATE}", release_rows=releases, credit_rows=credits
    )


def _albums() -> list[dict[str, Any]]:
    return [
        {
            "id": "master-1",
            "main_release_id": 1,
            "artist_id": 100,
            "artist": "Alice",
            "title": "Album One",
            "year": 1990,
        },
        {
            "id": "master-2",
            "main_release_id": 2,
            "artist_id": 200,
            "artist": "Bob",
            "title": "Album Two",
            "year": 1991,
        },
        {
            "id": "master-3",
            "main_release_id": 3,
            "artist_id": 400,
            "artist": "Dan",
            "title": "Album Three",
            "year": 1992,
        },
    ]


def test_behind_the_glass_finds_the_real_shared_engineer(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        report = measure_candidates(graph, _albums())

    behind_the_glass = report["behind_the_glass"]
    assert behind_the_glass["one_hop_candidate_pairs"] == 1  # master-1 <-> master-2 (Bob, Mixed By)
    # master-3's only credits are Drums/Vocals -- no engineering/production
    # credit at all, so it can never bridge or be reached under this mode.
    assert behind_the_glass["two_hop_candidate_pairs"] == 0


def test_rhythm_section_finds_the_real_shared_drummer(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        report = measure_candidates(graph, _albums())

    rhythm_section = report["rhythm_section"]
    assert rhythm_section["one_hop_candidate_pairs"] == 1  # master-2 <-> master-3 (Cara, Drums)


def test_guitar_paths_finds_no_candidates_when_no_guitar_credit_exists(
    dataset_root: Path,
) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        report = measure_candidates(graph, _albums())

    guitar_paths = report["guitar_paths"]
    assert guitar_paths["one_hop_candidate_pairs"] == 0
    assert guitar_paths["two_hop_candidate_pairs"] == 0


@pytest.fixture
def two_hop_dataset(tmp_path: Path) -> Path:
    """Four albums, all sharing engineering/production credits: 1<->2 via
    Bob (Mixed By), 2<->3 via Cara (Producer), and 1<->3 with no direct
    link -- a genuine two-hop behind-the-glass candidate bridged by 2."""
    from conftest import write_synthetic_dataset

    releases = [_release(1, "Album One"), _release(2, "Album Two"), _release(3, "Album Three")]
    credits = [
        _credit(1, 100, "Alice", "Vocals"),
        _credit(1, 200, "Bob", "Mixed By"),
        _credit(2, 200, "Bob", "Mixed By"),
        _credit(2, 300, "Cara", "Producer"),
        _credit(3, 300, "Cara", "Producer"),
        _credit(3, 400, "Dan", "Vocals"),
    ]
    return write_synthetic_dataset(
        tmp_path / f"snapshot={SNAPSHOT_DATE}", release_rows=releases, credit_rows=credits
    )


def test_behind_the_glass_finds_a_real_two_hop_bridge(two_hop_dataset: Path) -> None:
    with CreditGraph.open(two_hop_dataset, build_edges=False) as graph:
        report = measure_candidates(graph, _albums())

    behind_the_glass = report["behind_the_glass"]
    assert behind_the_glass["one_hop_candidate_pairs"] == 2  # (1,2) via Bob, (2,3) via Cara
    assert behind_the_glass["two_hop_candidate_pairs"] == 1  # (1,3) bridged by album 2


def test_every_candidate_mode_is_reported() -> None:
    from networked_players_graph_core.role_mode_candidates import CANDIDATE_MODES

    names = {mode.name for mode in CANDIDATE_MODES}
    assert names == {"behind_the_glass", "rhythm_section", "guitar_paths"}
