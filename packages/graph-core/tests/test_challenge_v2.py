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


def test_match_albums_rejects_release_outside_format_policy(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        matched, missed = match_albums(
            graph,
            [{"artist": "Alice", "title": "First Light"}],
            allowed_release_ids=frozenset({2, 3, 4, 5, 6, 7}),  # release 1 excluded
        )
    assert matched == []
    assert missed == [{"artist": "Alice", "title": "First Light"}]


def test_match_albums_allows_release_inside_format_policy(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        matched, missed = match_albums(
            graph,
            [{"artist": "Alice", "title": "First Light"}],
            allowed_release_ids=frozenset({1}),
        )
    assert len(matched) == 1
    assert missed == []


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


def test_validate_challenge_rejects_a_catalog_version_disagreeing_with_the_given_catalog(
    dataset_root: Path,
) -> None:
    """Proves the graph-core delegation to
    networked_players_contracts.challenge::challenge_failures actually
    reaches the new catalog_version cross-check, not just the
    contracts-level unit test."""
    with CreditGraph.open(dataset_root) as graph:
        artifact, _report = build_challenge_v2(
            graph,
            ALBUMS,
            snapshot_date="20260601",
            generated_by="test-suite",
            catalog_version="catalog-v1-20260601-realvalue",
        )

    validate_challenge(artifact)  # no catalog given: does not raise
    with pytest.raises(ChallengeValidationError, match="catalog_version"):
        validate_challenge(artifact, catalog={"catalog_version": "catalog-v1-20260601-different"})


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


def _hub_release(release_id: int, *, master_id: int) -> dict[str, object]:
    return {
        "snapshot_date": "20260601",
        "release_id": release_id,
        "status": "Accepted",
        "title": f"Hub Release {release_id}",
        "country": None,
        "released": "1995",
        "master_id": master_id,
        "master_is_main_release": True,
        "data_quality": None,
        "source_url": f"https://example.invalid/release/{release_id}",
    }


def _hub_credit(release_id: int, *, artist_id: int, name: str) -> list[dict[str, object]]:
    base = {
        "snapshot_date": "20260601",
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
        "role_text": "Performer",
        "credited_tracks_text": None,
        "is_linked": True,
        "playable_identity": True,
    }
    track = {
        **base,
        "track_index": 0,
        "track_path": "0",
        "track_position": "1",
        "track_title": "Track 1",
        "credit_scope": "track_artist",
        "role_text": None,
    }
    return [base, track]


def test_build_challenge_v2_reports_capped_searches_without_crashing(tmp_path: Path) -> None:
    """S(1000) and T(4000) can only reach anything through hub H(2000), whose
    degree (4) exceeds a deliberately low max_frontier_expansion (2) -- every
    search touching S or T is inconclusive (FrontierTooLargeError), not a
    confirmed no-path. A(9000)/B(9001) are a normal, uncapped direct pair.
    The whole build must still succeed (real evidence exists for A-B) and
    report the capped searches honestly rather than crash or silently count
    them as confirmed no-path."""
    from conftest import write_synthetic_dataset

    releases = [_hub_release(i, master_id=900 + i) for i in range(1, 5)] + [
        _hub_release(5, master_id=905)
    ]
    credits = [
        *_hub_credit(1, artist_id=1000, name="S"),
        *_hub_credit(1, artist_id=2000, name="H"),
        *_hub_credit(2, artist_id=2000, name="H"),
        *_hub_credit(2, artist_id=3001, name="P1"),
        *_hub_credit(3, artist_id=2000, name="H"),
        *_hub_credit(3, artist_id=3002, name="P2"),
        *_hub_credit(4, artist_id=2000, name="H"),
        *_hub_credit(4, artist_id=4000, name="T"),
        *_hub_credit(5, artist_id=9000, name="A"),
        *_hub_credit(5, artist_id=9001, name="B"),
    ]
    root = write_synthetic_dataset(
        tmp_path / "snapshot=20260601", release_rows=releases, credit_rows=credits
    )
    albums = [
        {"artist": "S", "title": "Hub Release 1"},
        {"artist": "T", "title": "Hub Release 4"},
        {"artist": "A", "title": "Hub Release 5"},
        {"artist": "B", "title": "Hub Release 5"},
    ]

    with CreditGraph.open(root) as graph:
        artifact, report = build_challenge_v2(
            graph,
            albums,
            snapshot_date="20260601",
            generated_by="test-suite",
            max_hops=3,
            max_frontier_expansion=2,
        )

    assert report["paths_capped"] >= 1
    assert report["paths_found"] >= 1
    validate_challenge(artifact)
