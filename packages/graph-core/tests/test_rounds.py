from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from networked_players_graph_core.graph import CreditGraph
from networked_players_graph_core.rounds import (
    ROUNDS_SCHEMA_VERSION,
    RoundsValidationError,
    build_round_from_path,
    build_round_hop,
    validate_rounds_artifact,
)

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


@pytest.fixture
def performer_dataset_root(tmp_path: Path) -> Path:
    """One release: Alice (Vocals) and Bob (Guitar), both explicitly
    performer-eligible -- a real one-hop round's happy path."""
    from conftest import write_synthetic_dataset

    root = tmp_path / f"snapshot={SNAPSHOT_DATE}"
    return write_synthetic_dataset(
        root,
        release_rows=[_release(1, "First Light")],
        credit_rows=[
            _credit(1, artist_id=100, name="Alice", scope="release_artist", role_text=None),
            _credit(
                1,
                artist_id=100,
                name="Alice",
                scope="track_artist",
                role_text="Vocals",
                track_index=0,
            ),
            _credit(1, artist_id=200, name="Bob", scope="release_artist", role_text=None),
            _credit(
                1,
                artist_id=200,
                name="Bob",
                scope="track_artist",
                role_text="Guitar",
                track_index=0,
            ),
        ],
    )


def test_build_round_hop_succeeds_with_explicit_performer_roles(
    performer_dataset_root: Path,
) -> None:
    with CreditGraph.open(performer_dataset_root) as graph:
        path = graph.find_path(100, 200, max_hops=1)
        assert path is not None
        hop = build_round_hop(graph, path.hops[0])
    assert hop is not None
    assert hop["role_a"] == "Vocals"
    assert hop["role_b"] == "Guitar"
    assert "same_recording" in hop["quality_flags"]


def test_build_round_hop_rejects_bare_release_artist_billing(dataset_root: Path) -> None:
    """The shared fixture graph (conftest.py) credits everyone with the
    generic role_text "Performer" -- real evidence of collaboration, but not
    an explicit instrument/vocal role, so it must fail the game's allowlist
    even though it is perfectly valid challenge.v2/cohort evidence."""
    with CreditGraph.open(dataset_root) as graph:
        path = graph.find_path(100, 200, max_hops=1)
        assert path is not None
        hop = build_round_hop(graph, path.hops[0])
    assert hop is None


def test_build_round_from_path_one_hop(performer_dataset_root: Path) -> None:
    with CreditGraph.open(performer_dataset_root) as graph:
        path = graph.find_path(100, 200, max_hops=1)
        assert path is not None
        round_json = build_round_from_path(
            graph,
            path,
            round_id="round-000001",
            from_album_id="release-1",
            to_album_id="release-1",
        )
    assert round_json is not None
    assert round_json["kind"] == "one_hop"
    # Both Alice and Bob are release-billed on the same recording -- the
    # strongest evidence tier (`co_billed_release_artists`), hence "easy".
    assert round_json["difficulty"] == "easy"
    assert len(round_json["hops"]) == 1
    assert round_json["distractors"] == []


def test_build_round_from_path_returns_none_when_any_hop_is_ineligible(
    dataset_root: Path,
) -> None:
    with CreditGraph.open(dataset_root) as graph:
        path = graph.find_path(100, 200, max_hops=1)
        assert path is not None
        round_json = build_round_from_path(
            graph,
            path,
            round_id="round-000001",
            from_album_id="release-1",
            to_album_id="release-2",
        )
    assert round_json is None


def test_build_round_from_path_rejects_unsupported_hop_counts(
    performer_dataset_root: Path,
) -> None:
    from networked_players_graph_core.graph import EvidencePath, Hop

    fake_path = EvidencePath(
        from_artist_id=100,
        to_artist_id=999,
        hops=(
            Hop(release_id=1, artist_a_id=100, artist_b_id=200),
            Hop(release_id=1, artist_a_id=200, artist_b_id=300),
            Hop(release_id=1, artist_a_id=300, artist_b_id=999),
        ),
    )
    with CreditGraph.open(performer_dataset_root) as graph:
        with pytest.raises(ValueError, match="only support 1- or 2-hop paths"):
            build_round_from_path(
                graph, fake_path, round_id="round-000001", from_album_id="a", to_album_id="b"
            )


def _valid_universe(pool_version: str = "rounds-v1-20260719") -> dict[str, Any]:
    return {
        "schema_version": ROUNDS_SCHEMA_VERSION,
        "pool_version": pool_version,
        "provenance": {
            "source": "Discogs monthly data dump (CC0), one-hop working set",
            "license": "See docs/DATA_AND_RIGHTS.md.",
            "snapshot_date": SNAPSHOT_DATE,
            "generated_by": "networked-players-catalog build-rounds-from-dump 0.1.0",
            "graph_core_version": "0.1.0",
            "note": "Real evidence, performer-only.",
        },
        "counts": {"one_hop": 1, "two_hop": 0, "daily_eligible": 1},
        "albums": [
            {
                "id": "release-1",
                "master_id": None,
                "main_release_id": 1,
                "title": "First Light",
                "artist_id": 100,
                "artist": "Alice",
                "year": 1995,
                "cover_image": None,
            },
            {
                "id": "release-2",
                "master_id": None,
                "main_release_id": 2,
                "title": "Second Set",
                "artist_id": 200,
                "artist": "Bob",
                "year": 1995,
                "cover_image": None,
            },
        ],
    }


def _valid_rounds(pool_version: str = "rounds-v1-20260719") -> dict[str, Any]:
    return {
        "schema_version": ROUNDS_SCHEMA_VERSION,
        "pool_version": pool_version,
        "provenance": _valid_universe(pool_version)["provenance"],
        "rounds": [
            {
                "id": "round-000001",
                "kind": "one_hop",
                "difficulty": "medium",
                "from_album_id": "release-1",
                "to_album_id": "release-2",
                "from_artist_id": 100,
                "to_artist_id": 200,
                "hops": [
                    {
                        "release_id": 1,
                        "artist_a_id": 100,
                        "artist_b_id": 200,
                        "role_a": "Vocals",
                        "role_b": "Guitar",
                        "quality_flags": ["performer_credit", "same_recording"],
                    }
                ],
                "distractors": [],
            }
        ],
        "releases": [
            {
                "snapshot_date": SNAPSHOT_DATE,
                "release_id": 1,
                "status": "Accepted",
                "title": "First Light",
                "country": None,
                "released": "1995",
                "master_id": None,
                "master_is_main_release": None,
                "data_quality": None,
                "source_url": "https://example.invalid/release/1",
                "credits": [],
            }
        ],
        "artists": [
            {"artist_id": 100, "name": "Alice"},
            {"artist_id": 200, "name": "Bob"},
        ],
    }


def test_validate_rounds_artifact_accepts_a_valid_pair() -> None:
    validate_rounds_artifact(_valid_universe(), _valid_rounds())


def test_validate_rounds_artifact_rejects_pool_version_mismatch() -> None:
    with pytest.raises(RoundsValidationError, match="pool_version must match"):
        validate_rounds_artifact(_valid_universe("a"), _valid_rounds("b"))


def test_validate_rounds_artifact_rejects_hop_count_kind_mismatch() -> None:
    rounds = _valid_rounds()
    rounds["rounds"][0]["kind"] = "two_hop"
    with pytest.raises(RoundsValidationError, match="must have 2 hop"):
        validate_rounds_artifact(_valid_universe(), rounds)


def test_validate_rounds_artifact_rejects_dangling_album_reference() -> None:
    rounds = _valid_rounds()
    rounds["rounds"][0]["to_album_id"] = "release-999"
    with pytest.raises(RoundsValidationError, match="unpublished album"):
        validate_rounds_artifact(_valid_universe(), rounds)


def test_validate_rounds_artifact_rejects_missing_role() -> None:
    rounds = _valid_rounds()
    rounds["rounds"][0]["hops"][0]["role_a"] = None
    with pytest.raises(RoundsValidationError, match="missing an explicit role_a/role_b"):
        validate_rounds_artifact(_valid_universe(), rounds)


def test_validate_rounds_artifact_rejects_seed_key() -> None:
    universe = _valid_universe()
    universe["provenance"]["seed"] = "leak"
    with pytest.raises(RoundsValidationError, match="must not have a 'seed' key"):
        validate_rounds_artifact(universe, _valid_rounds())


def test_validate_rounds_artifact_rejects_forbidden_substring() -> None:
    universe = _valid_universe()
    universe["provenance"]["note"] = "see /home/erich/notes"
    with pytest.raises(RoundsValidationError, match="forbidden substring"):
        validate_rounds_artifact(universe, _valid_rounds())


def test_validate_rounds_artifact_rejects_forbidden_phrase() -> None:
    universe = _valid_universe()
    universe["provenance"]["note"] = "Alice worked with Bob"
    with pytest.raises(RoundsValidationError, match="forbidden phrase"):
        validate_rounds_artifact(universe, _valid_rounds())
