from __future__ import annotations

from pathlib import Path

import pytest

from networked_players_graph_core.challenge import (
    ChallengeValidationError,
    build_challenge_v2,
    match_albums,
    validate_challenge,
)
from networked_players_graph_core.graph import CreditGraph

ALBUMS = [
    {"artist": "Alice", "title": "First Light"},
    {"artist": "Cara", "title": "Third Wave"},
    {"artist": "Eve", "title": "Sixth Sense"},
]


def test_match_albums_case_insensitive_and_reports_misses(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        matched, missed = match_albums(
            graph,
            [
                {"artist": "ALICE", "title": "first light"},
                {"artist": "Nobody", "title": "Nothing"},
            ],
        )
    assert len(matched) == 1
    assert matched[0].artist_id == 100
    assert matched[0].main_release_id == 1
    assert matched[0].master_id == 901
    assert missed == [{"artist": "Nobody", "title": "Nothing"}]


def test_match_albums_prefers_main_release_and_year(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        matched, _ = match_albums(graph, [{"artist": "Alice", "title": "First Light"}])
    assert matched[0].year == 1993
    assert matched[0].title == "First Light"  # masters not attached: release title used


def test_match_albums_deduplicates_by_artist(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        matched, missed = match_albums(
            graph,
            [
                {"artist": "Alice", "title": "First Light"},
                {"artist": "Alice", "title": "First Light"},
            ],
        )
    assert len(matched) == 1
    assert len(missed) == 1


def test_masters_attachment_overrides_title_and_year(
    dataset_root: Path, masters_root: Path
) -> None:
    with CreditGraph.open(dataset_root) as graph:
        graph.attach_masters(masters_root)
        matched, _ = match_albums(graph, [{"artist": "Alice", "title": "First Light"}])
    assert matched[0].title == "First Light (Deluxe)"
    assert matched[0].year == 1995


def test_build_challenge_v2_produces_a_valid_artifact(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        artifact, report = build_challenge_v2(
            graph, ALBUMS, snapshot_date="20260601", generated_by="test-suite"
        )

    validate_challenge(artifact)
    assert artifact["schema_version"] == 2
    assert report["albums_matched"] == 3
    assert report["albums_missed"] == 0
    assert report["paths_found"] >= 1


def test_build_challenge_v2_applies_family_exclusion(dataset_root: Path) -> None:
    """Alice(100) and Eve(500) are directly one-hop connected via R4 -- a
    real, trivial-looking pairing this test treats as if it were a band's own
    album vs. a member's solo release. Excluding it must remove that pair's
    path from the artifact without touching the other matched albums."""

    def is_family_excluded(artist_a_id: int, artist_b_id: int) -> bool:
        return {artist_a_id, artist_b_id} == {100, 500}

    with CreditGraph.open(dataset_root) as graph:
        artifact, report = build_challenge_v2(
            graph,
            ALBUMS,
            snapshot_date="20260601",
            generated_by="test-suite",
            is_family_excluded=is_family_excluded,
        )

    validate_challenge(artifact)
    excluded_pair_ids = {(100, 500), (500, 100)}
    for path in artifact["paths"]:
        assert (path["from_artist_id"], path["to_artist_id"]) not in excluded_pair_ids
    assert report["albums_matched"] == 3


def test_build_challenge_v2_concurrent_matches_sequential(dataset_root: Path) -> None:
    """max_workers > 1 must produce byte-for-byte the same artifact/report as
    the default sequential path -- concurrency here (each candidate pair's
    find_path spread across cursors) is purely a performance lever."""
    with CreditGraph.open(dataset_root) as graph:
        sequential_artifact, sequential_report = build_challenge_v2(
            graph, ALBUMS, snapshot_date="20260601", generated_by="test-suite"
        )
        concurrent_artifact, concurrent_report = build_challenge_v2(
            graph, ALBUMS, snapshot_date="20260601", generated_by="test-suite", max_workers=4
        )

    assert concurrent_artifact == sequential_artifact
    assert concurrent_report == sequential_report


def test_build_challenge_v2_releases_have_no_extra_columns(dataset_root: Path) -> None:
    """Regression test: CreditGraph.release() reads via `SELECT *` from a view
    over a `.../table=releases/*.parquet` glob -- without hive_partitioning=false
    on that read_parquet() call, DuckDB silently injects `table`/`snapshot`
    Hive-partition columns into every row, which used to leak straight into
    the published artifact. validate_challenge now also enforces this."""
    with CreditGraph.open(dataset_root) as graph:
        artifact, _ = build_challenge_v2(
            graph, ALBUMS, snapshot_date="20260601", generated_by="test-suite"
        )

    for release in artifact["releases"]:
        assert "table" not in release
        assert "snapshot" not in release


def test_build_challenge_v2_paths_connect_matched_album_artists(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        artifact, _ = build_challenge_v2(
            graph, ALBUMS, snapshot_date="20260601", generated_by="test-suite"
        )

    album_artist_ids = {a["artist_id"] for a in artifact["albums"]}
    for path in artifact["paths"]:
        assert path["from_artist_id"] in album_artist_ids
        assert path["to_artist_id"] in album_artist_ids


def test_build_challenge_v2_evidence_releases_only_contain_hop_endpoints(
    dataset_root: Path,
) -> None:
    with CreditGraph.open(dataset_root) as graph:
        artifact, _ = build_challenge_v2(
            graph, ALBUMS, snapshot_date="20260601", generated_by="test-suite"
        )

    hop_endpoint_ids_by_release: dict[int, set[int]] = {}
    for path in artifact["paths"]:
        for hop in path["hops"]:
            hop_endpoint_ids_by_release.setdefault(hop["release_id"], set()).update(
                (hop["artist_a_id"], hop["artist_b_id"])
            )

    for release in artifact["releases"]:
        expected = hop_endpoint_ids_by_release[release["release_id"]]
        actual = {c["artist_id"] for c in release["credits"]}
        assert actual == expected


def test_build_challenge_v2_raises_with_fewer_than_two_matches(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        with pytest.raises(ValueError):
            build_challenge_v2(
                graph,
                [{"artist": "Alice", "title": "First Light"}],
                snapshot_date="20260601",
                generated_by="test-suite",
            )


def test_validate_challenge_rejects_missing_key() -> None:
    artifact = {"schema_version": 2, "provenance": {}, "albums": [], "artists": [], "paths": []}
    with pytest.raises(ChallengeValidationError):
        validate_challenge(artifact)


def test_validate_challenge_rejects_hop_referencing_unpublished_release(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        artifact, _ = build_challenge_v2(
            graph, ALBUMS, snapshot_date="20260601", generated_by="test-suite"
        )
    artifact["paths"][0]["hops"][0]["release_id"] = 999_999
    with pytest.raises(ChallengeValidationError):
        validate_challenge(artifact)


def test_validate_challenge_rejects_tampered_artist_list(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        artifact, _ = build_challenge_v2(
            graph, ALBUMS, snapshot_date="20260601", generated_by="test-suite"
        )
    artifact["artists"] = []
    with pytest.raises(ChallengeValidationError):
        validate_challenge(artifact)


def test_validate_challenge_rejects_extra_release_key(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        artifact, _ = build_challenge_v2(
            graph, ALBUMS, snapshot_date="20260601", generated_by="test-suite"
        )
    artifact["releases"][0]["table"] = "releases"
    with pytest.raises(ChallengeValidationError):
        validate_challenge(artifact)


def test_validate_challenge_rejects_seed_key_outside_provenance(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        artifact, _ = build_challenge_v2(
            graph, ALBUMS, snapshot_date="20260601", generated_by="test-suite"
        )
    artifact["albums"][0]["seed"] = "1234"
    with pytest.raises(ChallengeValidationError):
        validate_challenge(artifact)
