from __future__ import annotations

import json
from pathlib import Path

import pytest

from networked_players_graph_core.graph import CreditGraph, FrontierTooLargeError, GraphError


def test_neighbors_finds_co_credited_playable_artists(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        neighbors = graph.neighbors(200)  # Bob: R1 with Alice, R2 with Cara
    assert neighbors == {100: (1,), 300: (2,)}


def test_release_format_policy_excludes_non_album_evidence(
    dataset_root: Path, tmp_path: Path
) -> None:
    policy = tmp_path / "policy.json"
    policy.write_text(
        json.dumps(
            {
                "policy_name": "studio-album-v1",
                "policy_version": 1,
                "snapshot_date": "20260601",
                "kind": "release-format-scoring-index",
                "allowed_release_ids": [2, 3, 4, 5, 6, 7],
            }
        )
    )
    with CreditGraph.open(dataset_root, release_format_policy=policy) as graph:
        assert graph.neighbors(100) == {500: (4,), 501: (4,), 502: (4,)}


def test_neighbors_excludes_non_linked_names(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        neighbors = graph.neighbors(100)  # Alice: never connects to "Session Choir"
    assert all(name != "Session Choir" for name in neighbors)


def test_various_placeholder_artist_excluded_from_graph(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        assert 194 not in graph.neighbors(600)
        # Frank (600) has no other co-credit once Various is excluded.
        assert graph.neighbors(600) == {}


def test_find_path_two_hop(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        path = graph.find_path(100, 300)  # Alice -> Bob -> Cara
    assert path is not None
    assert path.from_artist_id == 100
    assert path.to_artist_id == 300
    assert len(path.hops) == 2
    assert path.hops[0].release_id == 1
    assert path.hops[1].release_id == 2


def test_find_path_none_when_max_hops_too_small(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        assert graph.find_path(100, 300, max_hops=1) is None


def test_find_path_none_for_unknown_artist(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        assert graph.find_path(100, 999_999) is None


def test_find_path_raises_for_identical_endpoints(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        with pytest.raises(GraphError):
            graph.find_path(100, 100)


def test_default_cap_uses_the_compilation_shortcut(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        path = graph.find_path(100, 500)  # Alice -> Eve
    assert path is not None
    assert len(path.hops) == 1
    assert path.hops[0].release_id == 4


def test_tight_cap_excludes_the_compilation_and_takes_the_long_path(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, max_artists_per_release=3) as graph:
        path = graph.find_path(100, 500, max_hops=4)  # Alice -> Bob -> Cara -> Dan -> Eve
    assert path is not None
    assert [h.release_id for h in path.hops] == [1, 2, 3, 6]


def test_path_finding_is_deterministic(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        first = graph.find_path(100, 500)
        second = graph.find_path(100, 500)
    assert first == second


def test_credit_rows_returns_full_evidence(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        rows = graph.credit_rows(1, {100, 200})
    # Alice and Bob each hold a release_artist row and a track_artist row.
    assert len(rows) == 4
    assert {r["artist_id"] for r in rows} == {100, 200}
    assert all(r["release_id"] == 1 for r in rows)
    assert {r["credit_scope"] for r in rows} == {"release_artist", "track_artist"}


def test_credit_rows_for_releases_batches_and_filters(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        grouped = graph.credit_rows_for_releases([1, 7])
    # One query for both releases, not one per release.
    assert set(grouped) == {1, 7}
    assert {r["artist_id"] for r in grouped[1]} == {100, 200}
    # Various(194) is a placeholder identity and must never appear, even
    # though it is a real, linked, playable_identity row in the fixture.
    assert {r["artist_id"] for r in grouped[7]} == {600}


def test_credit_rows_for_releases_empty_input_returns_empty_dict(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        assert graph.credit_rows_for_releases([]) == {}


def test_credit_rows_for_releases_excludes_non_playable_rows(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        grouped = graph.credit_rows_for_releases([5])
    # R5 has Alice (playable) plus a non-linked "Session Choir" evidence row
    # (artist_id=None, playable_identity=False) that must not surface here.
    assert {r["artist_id"] for r in grouped[5]} == {100}


def test_artist_name_returns_canonical_name(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        assert graph.artist_name(100) == "Alice"
        assert graph.artist_name(999_999) is None


def test_stats_counts_artists_and_traversable_graph(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        stats = graph.stats()
    # Alice, Bob, Cara, Dan, Eve, PlusOne, PlusTwo, Frank -- 194 is excluded.
    assert stats["artist_count"] == 8
    # Frank (R7) shares no recording with anyone; Alice's R5 has no co-credit.
    assert stats["connected_artist_count"] == 7
    # R1, R2, R3, R6 give one edge each; R4's four artists give C(4,2) = 6.
    assert stats["edge_count"] == 10
    assert stats["evidence_release_count"] == 5

    with CreditGraph.open(dataset_root, max_artists_per_release=3) as tight_graph:
        tight_stats = tight_graph.stats()
    # R4's 4 distinct artists exceed a cap of 3, so its 6 edges disappear.
    assert tight_stats["edge_count"] == 4


def test_open_raises_on_missing_manifest(tmp_path: Path) -> None:
    with pytest.raises(GraphError):
        CreditGraph.open(tmp_path / "does-not-exist")


def test_find_release_by_title_artist_matches_case_insensitively(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        found = graph.find_release_by_title_artist("first light", "ALICE")
    assert found is not None
    assert found["release_id"] == 1
    assert found["artist_id"] == 100


def test_find_release_by_id_hint_resolves_release_id(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        found = graph.find_release_by_id_hint(release_id=1)
    assert found is not None
    assert found["release_id"] == 1
    assert found["master_id"] == 901
    assert found["artist_id"] == 100  # Alice: first release-artist credit by artist_id


def test_find_release_by_id_hint_resolves_master_id(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        found = graph.find_release_by_id_hint(master_id=901)
    assert found is not None
    assert found["release_id"] == 1
    assert found["artist_id"] == 100


def test_find_release_by_id_hint_prefers_artist_hint_among_multiple_credits(
    dataset_root: Path,
) -> None:
    # Release 1 has two release-artist credits: Alice (100) and Bob (200).
    with CreditGraph.open(dataset_root) as graph:
        found = graph.find_release_by_id_hint(release_id=1, artist_hint="Bob")
    assert found is not None
    assert found["artist_id"] == 200


def test_find_release_by_id_hint_returns_none_for_unknown_id(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        assert graph.find_release_by_id_hint(release_id=999_999) is None
        assert graph.find_release_by_id_hint(master_id=999_999) is None


def test_find_release_by_id_hint_requires_an_id(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph, pytest.raises(GraphError):
        graph.find_release_by_id_hint()


def _bare_release(release_id: int, title: str, *, master_id: int, master_is_main_release: bool):
    return {
        "snapshot_date": "20260601",
        "release_id": release_id,
        "status": "Accepted",
        "title": title,
        "country": None,
        "released": "2001",
        "master_id": master_id,
        "master_is_main_release": master_is_main_release,
        "data_quality": None,
        "source_url": f"https://example.invalid/release/{release_id}",
    }


def _bare_credit(release_id: int, *, artist_id: int, name: str):
    return {
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


def test_find_release_by_id_hint_redirects_non_main_pressing_to_master_main(
    tmp_path: Path,
) -> None:
    from conftest import write_synthetic_dataset

    root = write_synthetic_dataset(
        tmp_path / "snapshot=20260601",
        release_rows=[
            _bare_release(10, "Reissue Edition", master_id=950, master_is_main_release=False),
            _bare_release(11, "Original Pressing", master_id=950, master_is_main_release=True),
        ],
        credit_rows=[
            _bare_credit(10, artist_id=700, name="Gina"),
            _bare_credit(11, artist_id=700, name="Gina"),
        ],
    )
    with CreditGraph.open(root) as graph:
        # Hinted at the non-main reissue (10) -- should resolve to the
        # master's real main release (11), not overfit to the reissue.
        found = graph.find_release_by_id_hint(release_id=10)
    assert found is not None
    assert found["release_id"] == 11


def test_master_returns_none_when_not_attached(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        assert graph.master(901) is None


def test_release_has_no_hive_partition_artifacts(dataset_root: Path) -> None:
    """Regression test: the releases view is built via `SELECT * FROM
    read_parquet('.../table=releases/*.parquet')`. Without
    hive_partitioning=false, DuckDB auto-detects `table=`/`snapshot=` path
    segments as Hive partition columns and silently injects `table`/
    `snapshot` into every row returned by release()'s own `SELECT *`."""
    with CreditGraph.open(dataset_root) as graph:
        release = graph.release(1)
    assert release is not None
    assert "table" not in release
    assert "snapshot" not in release


def test_open_sets_temp_directory_under_dataset_root_by_default(dataset_root: Path) -> None:
    """Regression test: previously neither open() nor export_graph_snapshot()
    set temp_directory, so DuckDB spilled to CWD-relative `.tmp/` -- a real
    crash on a host where CWD sits on a smaller disk than the dataset."""
    with CreditGraph.open(dataset_root) as graph:
        setting = graph._connection.execute("SELECT current_setting('temp_directory')").fetchone()
    assert setting is not None
    assert str(dataset_root / ".graph-core-tmp") in setting[0]
    assert (dataset_root / ".graph-core-tmp").is_dir()


def test_open_honors_explicit_temp_dir(dataset_root: Path, tmp_path: Path) -> None:
    custom = tmp_path / "custom-spill"
    with CreditGraph.open(dataset_root, temp_dir=custom) as graph:
        setting = graph._connection.execute("SELECT current_setting('temp_directory')").fetchone()
    assert setting is not None
    assert str(custom) in setting[0]
    assert custom.is_dir()


def test_interrupt_is_a_safe_no_op_when_no_query_is_running(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        graph.interrupt()
        # Connection must still be usable afterward.
        assert graph.neighbors(200) == {100: (1,), 300: (2,)}


def test_degree_counts_distinct_neighbors(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        # Alice (100): Bob via R1; Eve, PlusOne, PlusTwo via R4. R5 has no
        # co-credited playable artist, so it contributes no degree.
        assert graph.degree(100) == 4
        assert graph.degree(999_999) == 0


def test_degrees_matches_individual_calls(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        individual = {artist_id: graph.degree(artist_id) for artist_id in (100, 200, 300, 999_999)}
        batched = graph.degrees([100, 200, 300, 999_999])

    # An artist with zero edges is simply absent -- callers use .get(id, 0).
    assert batched == {aid: count for aid, count in individual.items() if count > 0}
    assert graph.degrees([]) == {}


def test_neighbors_batch_matches_individual_calls(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        individual = {
            artist_id: graph.neighbors(artist_id) for artist_id in (100, 200, 300, 999_999)
        }
        batched = graph.neighbors_batch([100, 200, 300, 999_999])

    assert batched == individual
    assert graph.neighbors_batch([]) == {}


def test_batched_queries_handle_large_id_lists(dataset_root: Path) -> None:
    """A real hub frontier hands these methods tens of thousands of ids at
    once (measured: 17,612 on the worst production seed's hop-1, and its
    hop-2 reaches 445k) -- the scratch-table population must survive id lists
    far larger than any fixture, including spanning multiple insert chunks."""
    many_ids = [100, 200, 300, *range(1_000_000, 1_000_000 + 120_000)]
    with CreditGraph.open(dataset_root) as graph:
        counts = graph.degrees(many_ids)
        assert counts == graph.degrees([100, 200, 300])

        neighbors = graph.neighbors_batch([*many_ids[:3], *range(2_000_000, 2_000_100)])
        assert neighbors[100] == graph.neighbors(100)
        # Unknown ids are present-but-empty, never silently missing.
        assert neighbors[2_000_000] == {}


def _hub_release(release_id: int, *, master_id: int) -> dict[str, object]:
    return {
        "snapshot_date": "20260601",
        "release_id": release_id,
        "status": "Accepted",
        "title": f"Hub Release {release_id}",
        "country": None,
        "released": "2001",
        "master_id": master_id,
        "master_is_main_release": True,
        "data_quality": None,
        "source_url": f"https://example.invalid/release/{release_id}",
    }


def _hub_credit(release_id: int, *, artist_id: int, name: str) -> list[dict[str, object]]:
    """A billed artist who also performs on the release's single track.

    Two rows, not one: since ADR 0035 an edge needs same-recording evidence,
    so a credit with no `track_index` never makes the artist adjacent to
    anyone. Splat this into a `credit_rows` list.
    """
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


def test_find_path_raises_frontier_too_large_when_only_route_needs_the_hub(
    tmp_path: Path,
) -> None:
    from conftest import write_synthetic_dataset

    # S(1000) -> H(2000) at hop 1; H is the *only* route to T(4000) at hop 2.
    # H appears on 4 releases -- above a cap of 2, so it's excluded from
    # expansion and T is never reached.
    root = write_synthetic_dataset(
        tmp_path / "snapshot=20260601",
        release_rows=[_hub_release(i, master_id=900 + i) for i in range(1, 5)],
        credit_rows=[
            *_hub_credit(1, artist_id=1000, name="S"),
            *_hub_credit(1, artist_id=2000, name="H"),
            *_hub_credit(2, artist_id=2000, name="H"),
            *_hub_credit(2, artist_id=3001, name="P1"),
            *_hub_credit(3, artist_id=2000, name="H"),
            *_hub_credit(3, artist_id=3002, name="P2"),
            *_hub_credit(4, artist_id=2000, name="H"),
            *_hub_credit(4, artist_id=4000, name="T"),
        ],
    )
    with CreditGraph.open(root) as graph:
        with pytest.raises(FrontierTooLargeError) as exc_info:
            graph.find_path(1000, 4000, max_hops=3, max_frontier_expansion=2)
    assert exc_info.value.capped_artist_ids == frozenset({2000})


def test_find_path_still_succeeds_via_an_uncapped_alternate_route(tmp_path: Path) -> None:
    from conftest import write_synthetic_dataset

    # S(1000) reaches both H(2000, a hub) and N(5000, not a hub) at hop 1.
    # T(4000) is only reachable via N at hop 2 -- capping H must not prevent
    # finding T through N in the same level.
    root = write_synthetic_dataset(
        tmp_path / "snapshot=20260601",
        release_rows=[_hub_release(i, master_id=900 + i) for i in range(1, 6)],
        credit_rows=[
            *_hub_credit(1, artist_id=1000, name="S"),
            *_hub_credit(1, artist_id=2000, name="H"),
            *_hub_credit(2, artist_id=2000, name="H"),
            *_hub_credit(2, artist_id=3001, name="P1"),
            *_hub_credit(3, artist_id=2000, name="H"),
            *_hub_credit(3, artist_id=3002, name="P2"),
            *_hub_credit(4, artist_id=1000, name="S"),
            *_hub_credit(4, artist_id=5000, name="N"),
            *_hub_credit(5, artist_id=5000, name="N"),
            *_hub_credit(5, artist_id=4000, name="T"),
        ],
    )
    with CreditGraph.open(root) as graph:
        path = graph.find_path(1000, 4000, max_hops=3, max_frontier_expansion=2)
    assert path is not None
    assert [h.release_id for h in path.hops] == [4, 5]


def test_find_path_uncapped_by_default_matches_prior_behavior(dataset_root: Path) -> None:
    """max_frontier_expansion defaults to None -- behavior for any existing
    caller (challenge.py included) must be exactly unchanged."""
    with CreditGraph.open(dataset_root) as graph:
        path = graph.find_path(100, 500)  # Alice -> Eve, same as the default-cap test above
    assert path is not None
    assert len(path.hops) == 1


# --- ADR 0035 edge semantics: regressions from the 2026-07-10 real-data audit ---
#
# Each case below is a synthetic reconstruction of a real Discogs release that
# the release-container graph turned into a false "one hop" connection. The
# artist ids are the real ones so a failure is greppable against the audit.


def _adr35_release(release_id: int, title: str) -> dict[str, object]:
    return {
        "snapshot_date": "20260601",
        "release_id": release_id,
        "status": "Accepted",
        "title": title,
        "country": None,
        "released": "2007",
        "master_id": None,
        "master_is_main_release": None,
        "data_quality": None,
        "source_url": f"https://example.invalid/release/{release_id}",
    }


def _adr35_credit(
    release_id: int,
    *,
    artist_id: int,
    name: str,
    scope: str,
    role_text: str | None = None,
    track_index: int | None = None,
    track_title: str | None = None,
) -> dict[str, object]:
    return {
        "snapshot_date": "20260601",
        "release_id": release_id,
        "track_index": track_index,
        "track_path": None if track_index is None else str(track_index),
        "track_position": None if track_index is None else str(track_index + 1),
        "track_title": (None if track_index is None else track_title or f"Track {track_index + 1}"),
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


def _adr35_graph(
    tmp_path: Path, credit_rows: list[dict[str, object]], title: str, *, variant: str = ""
) -> CreditGraph:
    from conftest import write_synthetic_dataset

    release_id = int(credit_rows[0]["release_id"])  # type: ignore[arg-type]
    root = write_synthetic_dataset(
        tmp_path / f"{variant}snapshot=20260601",
        release_rows=[_adr35_release(release_id, title)],
        credit_rows=credit_rows,
    )
    return CreditGraph.open(root)


def test_compilation_track_artists_on_different_tracks_are_not_adjacent(tmp_path: Path) -> None:
    """Discogs release 1304383, "The Music Machine!" -- a DJ mix whose 46 track
    artists include Nas on track 13 and Pink Floyd on track 23. Under the old
    release-container graph this made Pink Floyd one hop from Nas."""
    rows = [
        _adr35_credit(1304383, artist_id=986299, name="Ruckus Roboticus", scope="release_artist"),
        _adr35_credit(
            1304383,
            artist_id=986299,
            name="Ruckus Roboticus",
            scope="release_credit",
            role_text="DJ Mix",
        ),
    ]
    # Five distinct track artists makes it compilation-shaped.
    compilation_track_artists = [
        (50997, "Nas"),
        (45467, "Pink Floyd"),
        (11213, "Wu-Tang Clan"),
        (3268, "ATCQ"),
        (4480, "Massive Attack"),
    ]
    for index, (artist_id, name) in enumerate(compilation_track_artists):
        rows.append(
            _adr35_credit(
                1304383, artist_id=artist_id, name=name, scope="track_artist", track_index=index
            )
        )
    with _adr35_graph(tmp_path, rows, "The Music Machine!") as graph:
        assert 45467 not in graph.neighbors(50997)
        assert graph.find_path(50997, 45467, max_hops=3) is None
        # The compilation is not evidence for anybody.
        assert graph.stats()["edge_count"] == 0


def test_two_featuring_guests_on_one_track_do_not_connect_to_each_other(tmp_path: Path) -> None:
    """Discogs release 345788, "The Work Of Director Spike Jonze" -- a DVD whose
    single chapter carries a `Featuring` credit for Radiohead and for Massive
    Attack. They are on the same "track" but neither performed with the other;
    the disc has two billed artists, so neither inherits the track."""
    rows = [
        _adr35_credit(345788, artist_id=900001, name="Spike Jonze", scope="release_artist"),
        _adr35_credit(345788, artist_id=900002, name="Palm Pictures", scope="release_artist"),
        _adr35_credit(
            345788,
            artist_id=3840,
            name="Radiohead",
            scope="track_credit",
            role_text="Featuring",
            track_index=0,
        ),
        _adr35_credit(
            345788,
            artist_id=4480,
            name="Massive Attack",
            scope="track_credit",
            role_text="Featuring",
            track_index=0,
        ),
    ]
    with _adr35_graph(tmp_path, rows, "The Work Of Director Spike Jonze") as graph:
        assert 4480 not in graph.neighbors(3840)
        assert graph.find_path(3840, 4480, max_hops=3) is None


def test_a_sampled_artist_never_becomes_a_collaborator(tmp_path: Path) -> None:
    """Discogs release 34128775, "God Damn Fairy Tale" -- a rap track that
    samples both Pink Floyd and Nas. Same track_index, but a quotation, not a
    contribution. `Sampler [Fairlight]` on the same track is an instrument and
    must survive."""
    rows = [
        _adr35_credit(34128775, artist_id=11771564, name="Lonely Wolf YD", scope="release_artist"),
        _adr35_credit(
            34128775, artist_id=11771564, name="Lonely Wolf YD", scope="track_artist", track_index=0
        ),
        _adr35_credit(
            34128775,
            artist_id=45467,
            name="Pink Floyd",
            scope="track_credit",
            role_text="Samples",
            track_index=0,
        ),
        _adr35_credit(
            34128775,
            artist_id=50997,
            name="Nas",
            scope="track_credit",
            role_text="Performer [Sample]",
            track_index=0,
        ),
        _adr35_credit(
            34128775,
            artist_id=700001,
            name="Keys Player",
            scope="track_credit",
            role_text="Sampler [Fairlight]",
            track_index=0,
        ),
    ]
    with _adr35_graph(tmp_path, rows, "God Damn Fairy Tale") as graph:
        neighbors = graph.neighbors(11771564)
        assert 45467 not in neighbors, "a bare `Samples` credit must not create an edge"
        assert 50997 not in neighbors, "`Performer [Sample]` must not create an edge"
        assert 700001 in neighbors, "`Sampler [Fairlight]` is an instrument, not a quotation"
        assert graph.find_path(45467, 50997, max_hops=3) is None


def test_album_producer_stars_off_the_billed_artist_rather_than_forming_a_clique(
    tmp_path: Path,
) -> None:
    """Nevermind's shape: an album-wide producer, mixer and masterer all connect
    to the billed artist, but not to each other -- a 40-credit album must not
    become a 780-edge clique (that is what made Bob Ludwig a 32,054-release
    hub)."""
    rows = [
        _adr35_credit(1813006, artist_id=125246, name="Nirvana", scope="release_artist"),
        _adr35_credit(
            1813006, artist_id=125246, name="Nirvana", scope="track_artist", track_index=0
        ),
        _adr35_credit(
            1813006,
            artist_id=42640,
            name="Butch Vig",
            scope="release_credit",
            role_text="Producer, Engineer",
        ),
        _adr35_credit(
            1813006,
            artist_id=59472,
            name="Andy Wallace",
            scope="release_credit",
            role_text="Mixed By",
        ),
        _adr35_credit(
            1813006,
            artist_id=254262,
            name="Howie Weinberg",
            scope="release_credit",
            role_text="Mastered By",
        ),
    ]
    with _adr35_graph(tmp_path, rows, "Nevermind") as graph:
        assert set(graph.neighbors(125246)) == {42640, 59472, 254262}
        # The contributors star off the band; they are not adjacent to each other.
        assert graph.neighbors(42640) == {125246: (1813006,)}
        assert 254262 not in graph.neighbors(59472)


def test_writing_and_packaging_credits_never_create_edges(tmp_path: Path) -> None:
    """A cover's songwriter and a sleeve designer are on the record but did not
    contribute to the recording. `Written-By, Producer` keeps its edge -- only a
    credit whose every component is non-collaborative is dropped."""
    rows = [
        _adr35_credit(381060, artist_id=92476, name="RHCP", scope="release_artist"),
        _adr35_credit(381060, artist_id=92476, name="RHCP", scope="track_artist", track_index=0),
        _adr35_credit(
            381060,
            artist_id=18956,
            name="Stevie Wonder",
            scope="track_credit",
            role_text="Written-By",
            track_index=0,
        ),
        _adr35_credit(
            381060, artist_id=2551803, name="A Designer", scope="release_credit", role_text="Design"
        ),
        _adr35_credit(
            381060,
            artist_id=42640,
            name="A Producer",
            scope="release_credit",
            role_text="Written-By, Producer",
        ),
    ]
    with _adr35_graph(tmp_path, rows, "Sessions And Videos") as graph:
        neighbors = graph.neighbors(92476)
        assert 18956 not in neighbors, "a Written-By-only cover credit is not a collaboration"
        assert 2551803 not in neighbors, "a Design credit is not a collaboration"
        assert 42640 in neighbors, "`Written-By, Producer` has a collaborative component"


def test_a_duet_track_on_an_album_shaped_release_still_connects_its_performers(
    tmp_path: Path,
) -> None:
    """The co_performers rule: two track artists on one track of an album-shaped
    release did play together -- provided the release bills them both, which a
    real duet or split single does. This is the true-positive counterpart to the
    mashup case below."""
    rows = [
        _adr35_credit(1, artist_id=100, name="Alice", scope="release_artist"),
        _adr35_credit(1, artist_id=200, name="Bob", scope="release_artist"),
        _adr35_credit(1, artist_id=100, name="Alice", scope="track_artist", track_index=0),
        _adr35_credit(1, artist_id=200, name="Bob", scope="track_artist", track_index=0),
    ]
    with _adr35_graph(tmp_path, rows, "A Duet") as graph:
        assert graph.neighbors(100) == {200: (1,)}


def test_a_mashup_albums_co_billed_track_artists_are_not_adjacent(tmp_path: Path) -> None:
    """Discogs release 2839582, "Till Our Worlds Collide" -- a bootleg whose
    track 5 is "New Dress / The Robots", crediting Depeche Mode and Kraftwerk as
    co-track-artists. Five or more distinct track artists across the release
    marks it a compilation, so co-performer edges are withheld."""
    rows = [
        _adr35_credit(
            2839582, artist_id=2725, name="Depeche Mode", scope="track_artist", track_index=4
        ),
        _adr35_credit(
            2839582, artist_id=4654, name="Kraftwerk", scope="track_artist", track_index=4
        ),
    ]
    rows += [
        _adr35_credit(
            2839582, artist_id=800000 + i, name=f"Other {i}", scope="track_artist", track_index=i
        )
        for i in range(4)
    ]
    with _adr35_graph(tmp_path, rows, "Till Our Worlds Collide") as graph:
        assert 4654 not in graph.neighbors(2725)
        assert graph.find_path(2725, 4654, max_hops=3) is None


def test_a_small_mashup_billed_to_the_bootlegger_connects_nobody(tmp_path: Path) -> None:
    """Discogs release 1991337, "Satanik Mashups Vol I" -- billed to "Inhumanz",
    with only four distinct track artists, so the compilation guard passes it as
    album-shaped. Its track "Shoot The War Pigs" co-credits Nas and Black
    Sabbath as track artists. Neither is billed on the release, and that is what
    separates a mashup from a duet."""
    rows = [
        _adr35_credit(1991337, artist_id=249280, name="Inhumanz", scope="release_artist"),
        _adr35_credit(
            1991337, artist_id=3857, name="Nine Inch Nails", scope="track_artist", track_index=0
        ),
        _adr35_credit(
            1991337, artist_id=79578, name="50 Cent", scope="track_artist", track_index=0
        ),
        _adr35_credit(1991337, artist_id=50997, name="Nas", scope="track_artist", track_index=2),
        _adr35_credit(
            1991337, artist_id=144998, name="Black Sabbath", scope="track_artist", track_index=2
        ),
    ]
    with _adr35_graph(tmp_path, rows, "Satanik Mashups Vol I") as graph:
        assert 144998 not in graph.neighbors(50997)
        assert 79578 not in graph.neighbors(3857)
        assert graph.find_path(50997, 144998, max_hops=3) is None


def test_a_container_track_naming_many_acts_creates_no_edges(tmp_path: Path) -> None:
    """Discogs release 23988572, "Glastonbury" -- a documentary DVD billed to
    Julien Temple, whose single chapter carries a `Featuring` credit for 19
    acts and NO `track_artist` rows at all.

    The track-artist compilation guard cannot see this (zero track artists reads
    as a one-artist album), so `max_artists_per_track` has to: without it, the
    single billed director inherits the chapter and stars out to every act on
    the bill, and the acts' pairwise distance collapses to two hops through him.
    """
    rows = [_adr35_credit(23988572, artist_id=270964, name="Julien Temple", scope="release_artist")]
    rows.append(
        _adr35_credit(
            23988572,
            artist_id=270964,
            name="Julien Temple",
            scope="release_credit",
            role_text="Film Director",
        )
    )
    festival_acts = [
        (3840, "Radiohead"),
        (4480, "Massive Attack"),
        (28972, "The Cure"),
        (45467, "Pink Floyd"),
    ]
    festival_acts += [(910000 + i, f"Act {i}") for i in range(15)]  # 19 acts on one chapter
    rows += [
        _adr35_credit(
            23988572,
            artist_id=artist_id,
            name=name,
            scope="track_credit",
            role_text="Featuring",
            track_index=0,
        )
        for artist_id, name in festival_acts
    ]
    with _adr35_graph(tmp_path, rows, "Glastonbury") as graph:
        assert graph.stats()["edge_count"] == 0
        assert graph.neighbors(270964) == {}, "the billed director inherits nothing"
        assert graph.find_path(3840, 4480, max_hops=3) is None


def test_a_well_credited_session_just_under_the_cap_still_creates_edges(tmp_path: Path) -> None:
    """The guard is a cap, not a ban: a big session -- one performer plus 15
    credited players on one track, 16 artists in all, above the corpus p99 of
    14 -- still stars off the performer."""
    rows = [
        _adr35_credit(1, artist_id=100, name="The Band", scope="release_artist"),
        _adr35_credit(1, artist_id=100, name="The Band", scope="track_artist", track_index=0),
    ]
    rows += [
        _adr35_credit(
            1,
            artist_id=200 + i,
            name=f"Player {i}",
            scope="track_credit",
            role_text="Cello",
            track_index=0,
        )
        for i in range(15)
    ]
    with _adr35_graph(tmp_path, rows, "A Big Session") as graph:
        # A star, not a clique: the band connects to 15 players, who do not
        # connect to each other.
        assert graph.stats()["edge_count"] == 15
        assert len(graph.neighbors(100)) == 15
        assert graph.neighbors(200) == {100: (1,)}

    rows.append(
        _adr35_credit(
            1,
            artist_id=999,
            name="One Too Many",
            scope="track_credit",
            role_text="Cello",
            track_index=0,
        )
    )
    with _adr35_graph(tmp_path, rows, "A Big Session", variant="over-cap-") as graph:
        assert graph.stats()["edge_count"] == 0, "17 artists on one track is a container"


def test_placeholder_exclusion_is_by_artist_id_never_by_name(tmp_path: Path) -> None:
    """A real band named "Anonymous" whose artist_id is not on the exclusion
    list must keep its edges -- the name pattern only proposes candidates for
    human review, it never filters. Conversely, artist 194 is excluded even
    when its name row says something else entirely."""
    rows = [
        # A real band that happens to be called "Anonymous". Not an excluded id.
        _adr35_credit(1, artist_id=777001, name="Anonymous", scope="release_artist"),
        _adr35_credit(1, artist_id=777001, name="Anonymous", scope="track_artist", track_index=0),
        _adr35_credit(
            1,
            artist_id=777002,
            name="Real Drummer",
            scope="track_credit",
            role_text="Drums",
            track_index=0,
        ),
        # An excluded id carrying a perfectly ordinary-looking name.
        _adr35_credit(
            1,
            artist_id=194,
            name="The Various Band",
            scope="track_credit",
            role_text="Guitar",
            track_index=0,
        ),
    ]
    with _adr35_graph(tmp_path, rows, "Anonymous Debut") as graph:
        neighbors = graph.neighbors(777001)
        assert 777002 in neighbors, "a band named 'Anonymous' is not a placeholder"
        assert 194 not in neighbors, "artist 194 is excluded by id, whatever it is named"


def test_placeholder_artist_candidates_reports_the_whole_exclusion_list(tmp_path: Path) -> None:
    """The maintenance helper must re-find identities already excluded (so a
    snapshot audit can diff against the list) and flag unknown ones."""
    rows = [
        _adr35_credit(1, artist_id=194, name="Various", scope="track_artist", track_index=0),
        _adr35_credit(1, artist_id=967691, name="Anonymous", scope="track_artist", track_index=0),
        _adr35_credit(
            1, artist_id=888888, name="Unknown Artist", scope="track_artist", track_index=0
        ),
        _adr35_credit(1, artist_id=777001, name="A Real Band", scope="track_artist", track_index=0),
    ]
    with _adr35_graph(tmp_path, rows, "Placeholder Audit") as graph:
        found = {c["artist_id"]: c for c in graph.placeholder_artist_candidates()}

    assert 777001 not in found, "an ordinary name is never a candidate"
    assert found[194]["already_excluded"] is True
    assert found[967691]["already_excluded"] is True
    # A placeholder-looking id we have never seen: surfaced for a human, not
    # silently excluded.
    assert found[888888]["already_excluded"] is False


def test_placeholder_config_is_the_source_of_truth_and_supports_both_policies() -> None:
    """The exclusion list is data, not code. Every entry parses, is keyed by a
    numeric artist_id, and carries a policy that decides whether the identity is
    removed from the graph outright or merely flagged for review."""
    import json
    from importlib import resources

    from networked_players_graph_core import graph as graph_module

    raw = json.loads(
        resources.files("networked_players_graph_core")
        .joinpath(graph_module.PLACEHOLDER_ARTISTS_CONFIG)
        .read_text("utf-8")
    )
    entries = raw["artists"]
    assert entries, "the config must not be empty"
    assert all(isinstance(e["artist_id"], int) for e in entries), "ids are numeric"
    assert len({e["artist_id"] for e in entries}) == len(entries), "no duplicate ids"

    excluded = {e["artist_id"] for e in entries if e.get("policy", "exclude") == "exclude"}
    flagged = {e["artist_id"] for e in entries if e.get("policy", "exclude") == "flag"}
    assert graph_module.NON_INDIVIDUAL_ARTIST_IDS == excluded
    assert graph_module.FLAGGED_PLACEHOLDER_ARTIST_IDS == flagged
    assert graph_module.PLACEHOLDER_ARTIST_IDS == excluded | flagged
    # Pending Erich's hard-vs-soft review, everything is a hard exclusion.
    assert flagged == set()
    assert 194 in excluded and 151641 in excluded and 355 in excluded


def test_a_flag_policy_keeps_the_identity_traversable(tmp_path: Path, monkeypatch) -> None:
    """Soft filtering, so the config's `flag` policy is not vapourware: a
    flagged identity still forms edges (and `cohort_connectivity` will tag the
    hop `placeholder_artist_hop`), whereas an excluded one never does."""
    from networked_players_graph_core import graph as graph_module

    rows = [
        _adr35_credit(1, artist_id=100, name="Alice", scope="release_artist"),
        _adr35_credit(1, artist_id=100, name="Alice", scope="track_artist", track_index=0),
        _adr35_credit(
            1,
            artist_id=194,
            name="Various",
            scope="track_credit",
            role_text="Guitar",
            track_index=0,
        ),
    ]
    with _adr35_graph(tmp_path, rows, "Excluded") as graph:
        assert graph.neighbors(100) == {}

    monkeypatch.setattr(graph_module, "NON_INDIVIDUAL_ARTIST_IDS", frozenset())
    with _adr35_graph(tmp_path, rows, "Flagged", variant="flag-") as graph:
        assert 194 in graph.neighbors(100)


def test_a_remixer_never_connects_the_artists_they_remixed(tmp_path: Path) -> None:
    """Aaron Scofield remixed a Strokes track and edited a Cure track on two
    different compilations, which made The Strokes two hops from The Cure. A
    rework credit is not a collaboration.

    "Mixed By" is a different thing entirely -- studio mixing of the original
    session -- and must survive.
    """
    rows = [
        _adr35_credit(1, artist_id=55980, name="The Strokes", scope="release_artist"),
        _adr35_credit(1, artist_id=55980, name="The Strokes", scope="track_artist", track_index=0),
        _adr35_credit(
            1,
            artist_id=900100,
            name="Aaron Scofield",
            scope="track_credit",
            role_text="Remix",
            track_index=0,
        ),
        _adr35_credit(
            1,
            artist_id=900101,
            name="Another Reworker",
            scope="track_credit",
            role_text="Edited By",
            track_index=0,
        ),
        _adr35_credit(
            1,
            artist_id=900102,
            name="A Mix DJ",
            scope="track_credit",
            role_text="DJ Mix",
            track_index=0,
        ),
        # Studio mixing of the session itself: a real contributor.
        _adr35_credit(
            1,
            artist_id=59472,
            name="Andy Wallace",
            scope="track_credit",
            role_text="Mixed By",
            track_index=0,
        ),
        # A compound role keeps its edge -- an unlisted component always wins.
        _adr35_credit(
            1,
            artist_id=900103,
            name="Remixing Producer",
            scope="track_credit",
            role_text="Remix, Producer",
            track_index=0,
        ),
    ]
    with _adr35_graph(tmp_path, rows, "Culture Shock Volume Fifteen") as graph:
        neighbors = graph.neighbors(55980)
        assert 900100 not in neighbors, "a Remix credit is a rework, not a collaboration"
        assert 900101 not in neighbors, "Edited By is a rework"
        assert 900102 not in neighbors, "DJ Mix is a rework"
        assert 59472 in neighbors, "Mixed By is studio mixing of the original session"
        assert 900103 in neighbors, "'Remix, Producer' has a collaborative component"


ROLE_PARITY_CASES = [
    None,
    "Producer",
    "Producer, Engineer",
    "Written-By",
    "Written-By, Producer",
    "Written-By [Sample]",
    "Performer [Sample]",
    "Featuring [Samples From]",
    "Samples",
    "Sampled By",
    "Sampler",
    "Sampler [Fairlight]",
    "Synthesizer, Sampler",
    "Guitar [Sample]",
    "Written-By [Interpolation]",
    "Performer [Excerpts]",
    "Remix",
    "Remix, Producer",
    "Edited By",
    "DJ Mix",
    "Mixed By",
    "Mastered By",
    "Design",
    "Art Direction",
    "Executive-Producer",
    "Coordinator [Photo Coordination]",
    "Songwriter [Songs By]",
    "Vocals",
    "Backing Band [Uncredited]",
    "",
]


def test_edge_ineligible_role_matches_the_sql(tmp_path: Path) -> None:
    """`edge_ineligible_role` and `_edge_ineligible_role_sql` must agree on
    every role, or the curator's "which credit justifies this hop" annotation
    would disagree with the graph that built the hop."""
    import duckdb

    from networked_players_graph_core.graph import (
        _edge_ineligible_role_sql,
        edge_ineligible_role,
    )

    connection = duckdb.connect()
    connection.execute("CREATE TABLE roles (role_text VARCHAR)")
    connection.executemany("INSERT INTO roles VALUES (?)", [[r] for r in ROLE_PARITY_CASES])
    sql = _edge_ineligible_role_sql("role_text")
    rows = connection.execute(f"SELECT role_text, {sql} FROM roles").fetchall()
    connection.close()

    mismatches = [
        (role, bool(sql_result), edge_ineligible_role(role))
        for role, sql_result in rows
        if bool(sql_result) != edge_ineligible_role(role)
    ]
    assert not mismatches, f"SQL and Python disagree on: {mismatches}"

    # Spot-check the semantics the parity test alone would not pin down.
    assert edge_ineligible_role("Remix") is True
    assert edge_ineligible_role("Remix, Producer") is False
    assert edge_ineligible_role("Mixed By") is False
    assert edge_ineligible_role("Sampler [Fairlight]") is False
    assert edge_ineligible_role("Performer [Sample]") is True
    assert edge_ineligible_role(None) is False


def test_a_dj_sampler_track_connects_nobody_when_neither_artist_is_billed(tmp_path: Path) -> None:
    """Discogs release 5846846, "2 Worlds Collide" -- billed to DJ KO, whose
    track "Last Real Nigga Alive Remix" co-credits Nas (track artist) and Red
    Hot Chili Peppers (track artist + Co-producer). same_recording used to fire
    Nas <-> RHCP through RHCP's Co-producer credit, even though neither is the
    artist the record is by. The billed-anchor blocks it: the only billed
    artist is the DJ.
    """
    rows = [
        _adr35_credit(5846846, artist_id=431797, name="DJ KO", scope="release_artist"),
        _adr35_credit(5846846, artist_id=50997, name="Nas", scope="track_artist", track_index=0),
        _adr35_credit(5846846, artist_id=92476, name="RHCP", scope="track_artist", track_index=0),
        _adr35_credit(
            5846846,
            artist_id=92476,
            name="RHCP",
            scope="track_credit",
            role_text="Co-producer",
            track_index=0,
        ),
    ]
    with _adr35_graph(tmp_path, rows, "2 Worlds Collide") as graph:
        assert 92476 not in graph.neighbors(50997)
        assert graph.find_path(50997, 92476, max_hops=3) is None
        # The billed DJ connecting to a track credit is not the concern here;
        # what matters is the two sampled artists never touch.


def test_a_feature_survives_when_the_billed_artist_is_one_endpoint(tmp_path: Path) -> None:
    """The billed-anchor keeps a genuine guest spot: on Wu-Tang's own "The W",
    the track "Let My Niggas Live" has no track_artist row, so the single-billed
    fallback makes Wu-Tang (the billed act) the performer, and Nas is a
    `Featuring` guest. Wu-Tang is billed, so the edge holds.
    """
    rows = [
        _adr35_credit(6479699, artist_id=11213, name="Wu-Tang Clan", scope="release_artist"),
        # A couple of ordinary album tracks give it album shape without tipping
        # into compilation territory.
        _adr35_credit(
            6479699, artist_id=11213, name="Wu-Tang Clan", scope="track_artist", track_index=0
        ),
        _adr35_credit(
            6479699, artist_id=11213, name="Wu-Tang Clan", scope="track_artist", track_index=1
        ),
        # The guest track: no track_artist, so the fallback anchors it to Wu-Tang.
        _adr35_credit(
            6479699,
            artist_id=50997,
            name="Nas",
            scope="track_credit",
            role_text="Featuring",
            track_index=2,
        ),
    ]
    with _adr35_graph(tmp_path, rows, "The W") as graph:
        assert 50997 in graph.neighbors(11213), "billed Wu-Tang <-> guest Nas must survive"


def test_live_b_side_feature_does_not_create_a_curated_edge(tmp_path: Path) -> None:
    """A single's live B-side must not connect its billed artist to the guest.

    Synthetic reconstruction of The Strokes' ``Taken For A Fool`` release:
    Elvis Costello appears only on the live B-side, not on the studio track or
    release credits. The first public cohort should not route through it.
    """
    rows = [
        _adr35_credit(3056804, artist_id=55980, name="The Strokes", scope="release_artist"),
        _adr35_credit(
            3056804,
            artist_id=55029,
            name="Elvis Costello",
            scope="track_credit",
            role_text="Featuring",
            track_index=1,
            track_title="Taken For A Fool (Live From Madison Square Garden)",
        ),
    ]
    with _adr35_graph(tmp_path, rows, "Taken For A Fool") as graph:
        assert 55029 not in graph.neighbors(55980)


def test_obvious_compilation_title_does_not_create_curated_edges(tmp_path: Path) -> None:
    """The interim title guard blocks an otherwise album-shaped sampler."""
    rows = [
        _adr35_credit(4001, artist_id=100, name="Alice", scope="release_artist"),
        _adr35_credit(4001, artist_id=100, name="Alice", scope="track_artist", track_index=0),
        _adr35_credit(4001, artist_id=200, name="Bob", scope="release_artist"),
        _adr35_credit(4001, artist_id=200, name="Bob", scope="track_artist", track_index=0),
    ]
    with _adr35_graph(tmp_path, rows, "Greatest Hits") as graph:
        assert graph.neighbors(100) == {}
        assert graph.neighbors(200) == {}
