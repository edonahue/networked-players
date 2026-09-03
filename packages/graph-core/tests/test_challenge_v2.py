from __future__ import annotations

from pathlib import Path

import pytest

from networked_players_graph_core.challenge import (
    ChallengeValidationError,
    MatchedAlbum,
    build_challenge_v2,
    build_challenge_v2_from_matched,
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
    assert artifact["provenance"]["graph_policy_version"] == 1
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


def _matched_album(
    *,
    artist_id: int,
    artist_name: str,
    title: str,
    master_id: int | None,
    main_release_id: int,
    year: int | None = 2000,
) -> MatchedAlbum:
    return MatchedAlbum(
        artist_query=artist_name,
        title_query=title,
        master_id=master_id,
        main_release_id=main_release_id,
        title=title,
        artist_id=artist_id,
        artist_name=artist_name,
        year=year,
    )


def test_candidate_album_pairs_touch_every_album_before_revisiting_any() -> None:
    """The real `challenge.v3.json` (179 albums, `--max-paths 300`) had every
    one of its 300 paths start from the same two albums and left 7 albums
    without any path, because the old `for i: for j > i` order enumerates
    every pair of album 0 before album 1 gets a second look. Per-album
    round-robin makes the first `N` candidates cover all `N` albums, so a
    `max_paths` budget of about `2N` documents the whole catalog instead of
    two corners of it. The candidate SET must stay exactly the old one --
    this is a reordering, not a filter."""
    from itertools import combinations

    from networked_players_graph_core import challenge as challenge_module

    ordered = [
        _matched_album(
            artist_id=100 + n,
            artist_name=f"Artist {n}",
            title=f"Album {n}",
            master_id=900 + n,
            main_release_id=n + 1,
        )
        for n in range(8)
    ]

    pairs = challenge_module._candidate_album_pairs(ordered)

    album_count = len(ordered)
    every_album = {a.album_id for a in ordered}
    # Round 1: each album claims one pair, in `ordered` order, so the first
    # N candidates START from albums 0..N-1 respectively and cover all N.
    first_round = pairs[:album_count]
    assert [pair[0].album_id for pair in first_round] == [a.album_id for a in ordered]
    assert {a.album_id for pair in first_round for a in pair} == every_album
    # Round 2 covers everything again.
    second_round = pairs[album_count : 2 * album_count]
    assert {a.album_id for pair in second_round for a in pair} == every_album
    # Same set as the plain i < j enumeration, no pair duplicated or lost
    # (direction is "whose turn it was", so compare unordered).
    assert sorted(sorted((a.album_id, b.album_id)) for a, b in pairs) == sorted(
        sorted((a.album_id, b.album_id)) for a, b in combinations(ordered, 2)
    )
    assert len(pairs) == len(set(frozenset((a.album_id, b.album_id)) for a, b in pairs))
    # And the old order is gone: pairs[1] no longer starts from album 0.
    assert pairs[1][0].album_id != ordered[0].album_id


def test_candidate_album_pairs_give_adjacent_same_artist_albums_their_own_turn() -> None:
    """The first, offset-stratified fix still left 2 of 179 real albums out:
    pairs are deduplicated per ARTIST pair, and the catalog holds four
    Jamiroquai masters that sort next to each other, so the first one took
    the shared artist pairs with the neighbours and the middle two never
    got a turn before `max_paths`. Per-album round-robin must hand every
    album a DISTINCT artist pair in round 1, however its siblings sort."""
    from networked_players_graph_core import challenge as challenge_module

    def album(n: int, artist_id: int) -> MatchedAlbum:
        return _matched_album(
            artist_id=artist_id,
            artist_name=f"Artist {artist_id}",
            title=f"Album {n}",
            master_id=900 + n,
            main_release_id=n + 1,
        )

    # Albums 3..6 share artist 300 and sit adjacent, like the real catalog.
    ordered = [
        album(0, 100),
        album(1, 101),
        album(2, 102),
        album(3, 300),
        album(4, 300),
        album(5, 300),
        album(6, 300),
        album(7, 107),
        album(8, 108),
        album(9, 109),
    ]

    pairs = challenge_module._candidate_album_pairs(ordered)

    first_round = pairs[: len(ordered)]
    assert {a.album_id for pair in first_round for a in pair} == {a.album_id for a in ordered}
    # Each same-artist album's round-1 pair reaches a DIFFERENT partner
    # artist -- that is what makes them distinct artist pairs.
    same_artist_partners = [b.artist_id for a, b in first_round if a.artist_id == 300]
    assert len(same_artist_partners) == 4
    assert len(set(same_artist_partners)) == 4
    # No pair ever joins two albums by the same artist, and no artist pair
    # is ever emitted twice.
    artist_pairs = [frozenset((a.artist_id, b.artist_id)) for a, b in pairs]
    assert all(len(pair) == 2 for pair in artist_pairs)
    assert len(artist_pairs) == len(set(artist_pairs))


def test_build_challenge_v2_every_album_gets_a_path_within_two_per_album(
    dataset_root: Path,
) -> None:
    """End-to-end form of the ordering guarantee on the synthetic fixture:
    with `max_paths = 2 * N`, every matched album appears in at least one
    published path."""
    with CreditGraph.open(dataset_root) as graph:
        artifact, _report = build_challenge_v2(
            graph,
            ALBUMS,
            snapshot_date="20260601",
            generated_by="test-suite",
            max_paths=2 * len(ALBUMS),
        )
    validate_challenge(artifact)
    touched = {p["from_album_id"] for p in artifact["paths"]} | {
        p["to_album_id"] for p in artifact["paths"]
    }
    assert touched == {a["id"] for a in artifact["albums"]}


def test_build_challenge_v2_skips_a_same_artist_pair_instead_of_raising(
    dataset_root: Path,
) -> None:
    """Real bug found while doing the actual Phase 7 catalog expansion:
    `--already-published-catalog` (PR #155) and Bucket A (ADR 0065) both
    deliberately allow multiple albums by the same artist in the resolved
    catalog `build-challenge-from-dump` consumes. Two DIFFERENT albums by
    the SAME artist_id (e.g. two real Jamiroquai albums) reach
    `_candidate_album_pairs` as `ordered` entries, and without an explicit
    same-artist skip, `pair = (id, id)` slipped past the `used_pairs` dedup
    (never seen before) and reached `find_path`, which raises
    `GraphError('from_artist_id and to_artist_id must differ')` -- there is
    no meaningful 'how is this artist connected to themselves' question to
    ask. This was always possible in principle but never exercised before
    Phase 7, since every earlier catalog deduped to one album per artist
    everywhere."""
    matched = [
        _matched_album(
            artist_id=100,
            artist_name="Alice",
            title="First Light",
            master_id=901,
            main_release_id=1,
        ),
        _matched_album(
            artist_id=100,
            artist_name="Alice",
            title="Second Alice Album",
            master_id=None,
            main_release_id=90001,
        ),
        _matched_album(
            artist_id=300,
            artist_name="Cara",
            title="Third Wave",
            master_id=903,
            main_release_id=3,
        ),
    ]
    with CreditGraph.open(dataset_root) as graph:
        artifact, report = build_challenge_v2_from_matched(
            graph, matched, [], snapshot_date="20260601", generated_by="test-suite"
        )
    validate_challenge(artifact)
    # Every real, distinct-artist pair is still attempted -- only the
    # same-artist (Alice, Alice) pair is skipped, not silently dropped
    # along with a real one.
    assert report["albums_matched"] == 3


def test_build_challenge_v2_concurrent_still_skips_a_same_artist_pair(
    dataset_root: Path,
) -> None:
    """The same same-artist skip must hold for the concurrent path
    (max_workers > 1), not just the sequential default -- both consume the
    same `_candidate_album_pairs` output."""
    matched = [
        _matched_album(
            artist_id=100,
            artist_name="Alice",
            title="First Light",
            master_id=901,
            main_release_id=1,
        ),
        _matched_album(
            artist_id=100,
            artist_name="Alice",
            title="Second Alice Album",
            master_id=None,
            main_release_id=90001,
        ),
        _matched_album(
            artist_id=300,
            artist_name="Cara",
            title="Third Wave",
            master_id=903,
            main_release_id=3,
        ),
    ]
    with CreditGraph.open(dataset_root) as graph:
        artifact, report = build_challenge_v2_from_matched(
            graph, matched, [], snapshot_date="20260601", generated_by="test-suite", max_workers=4
        )
    validate_challenge(artifact)
    assert report["albums_matched"] == 3


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


def test_concurrent_search_stops_early_instead_of_computing_every_candidate_pair(
    dataset_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The property the concurrent path silently lacked: it must respect the
    caller's `max_paths` early stop, not precompute every candidate pair.

    Measured on the real Phase 7 179-album catalog, the old
    precompute-everything behavior meant ~14,878 bounded BFS searches at
    tens of seconds each (a multi-day job) to fill an artifact that keeps
    only a few hundred paths -- so passing `max_workers > 1` made the build
    dramatically slower than the sequential default. This test pins the fix
    by counting real `_bounded_find_path` calls.
    """
    import networked_players_graph_core.challenge as challenge_module

    calls: list[tuple[int, int]] = []
    real_bounded_find_path = challenge_module._bounded_find_path

    def counting_bounded_find_path(graph, from_artist_id, to_artist_id, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((from_artist_id, to_artist_id))
        return real_bounded_find_path(graph, from_artist_id, to_artist_id, **kwargs)

    monkeypatch.setattr(challenge_module, "_bounded_find_path", counting_bounded_find_path)
    # Smallest possible batch, so the bound is tight and obvious.
    monkeypatch.setattr(challenge_module, "_PATH_BATCH_PER_WORKER", 1)

    with CreditGraph.open(dataset_root) as graph:
        matched, _missed = match_albums(graph, ALBUMS)
        total_candidate_pairs = len(
            challenge_module._candidate_album_pairs(sorted(matched, key=lambda m: m.album_id))
        )
        artifact, _report = build_challenge_v2(
            graph,
            ALBUMS,
            snapshot_date="20260601",
            generated_by="test-suite",
            max_paths=1,
            max_workers=2,
        )

    validate_challenge(artifact)
    assert total_candidate_pairs >= 3  # fixture sanity: there IS something to skip
    # The whole point: strictly fewer searches than the full candidate list.
    assert len(calls) < total_candidate_pairs, (
        f"computed {len(calls)} of {total_candidate_pairs} pairs -- the max_paths "
        "early stop was not respected"
    )


@pytest.mark.parametrize("max_workers", [1, 2])
def test_no_path_search_runs_after_the_max_paths_cap_is_reached(
    dataset_root: Path, monkeypatch: pytest.MonkeyPatch, max_workers: int
) -> None:
    """Review finding: a top-of-loop `max_paths` guard only fires AFTER the
    `for` has already pulled the next item, and pulling is what triggers the
    work -- one wasted bounded BFS in sequential mode (tens of seconds on the
    real catalog), or a whole wasted batch in concurrent mode when the
    satisfying result was the last of its batch.

    Pins the fix: the number of real `_bounded_find_path` calls never exceeds
    the number of pairs the report says were attempted, in either mode.
    """
    import networked_players_graph_core.challenge as challenge_module

    calls: list[tuple[int, int]] = []
    real_bounded_find_path = challenge_module._bounded_find_path

    def counting_bounded_find_path(graph, from_artist_id, to_artist_id, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((from_artist_id, to_artist_id))
        return real_bounded_find_path(graph, from_artist_id, to_artist_id, **kwargs)

    monkeypatch.setattr(challenge_module, "_bounded_find_path", counting_bounded_find_path)
    monkeypatch.setattr(challenge_module, "_PATH_BATCH_PER_WORKER", 1)

    with CreditGraph.open(dataset_root) as graph:
        _artifact, report = build_challenge_v2(
            graph,
            ALBUMS,
            snapshot_date="20260601",
            generated_by="test-suite",
            max_paths=1,
            max_workers=max_workers,
        )

    assert report["paths_found"] == 1
    if max_workers == 1:
        # Sequential: exactly the attempted pairs, not one more.
        assert len(calls) == report["paths_attempted"]
    else:
        # Concurrent: bounded by the batch the final path landed in, never
        # a further batch beyond it.
        assert len(calls) <= report["paths_attempted"] + max_workers


def test_max_paths_zero_runs_no_path_search_at_all(
    dataset_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Degenerate but real edge of the same fix: with nothing to fill, the
    iterator must never be advanced even once."""
    import networked_players_graph_core.challenge as challenge_module

    calls: list[tuple[int, int]] = []
    real_bounded_find_path = challenge_module._bounded_find_path

    def counting_bounded_find_path(graph, from_artist_id, to_artist_id, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((from_artist_id, to_artist_id))
        return real_bounded_find_path(graph, from_artist_id, to_artist_id, **kwargs)

    monkeypatch.setattr(challenge_module, "_bounded_find_path", counting_bounded_find_path)

    with CreditGraph.open(dataset_root) as graph:
        with pytest.raises(ValueError, match="no evidence paths found"):
            build_challenge_v2(
                graph, ALBUMS, snapshot_date="20260601", generated_by="test-suite", max_paths=0
            )
    assert calls == []
