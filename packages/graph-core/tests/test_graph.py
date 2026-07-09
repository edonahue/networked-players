from __future__ import annotations

from pathlib import Path

import pytest

from networked_players_graph_core.graph import CreditGraph, FrontierTooLargeError, GraphError


def test_neighbors_finds_co_credited_playable_artists(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        neighbors = graph.neighbors(200)  # Bob: R1 with Alice, R2 with Cara
    assert neighbors == {100: (1,), 300: (2,)}


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
    assert len(rows) == 2
    assert {r["artist_id"] for r in rows} == {100, 200}
    assert all(r["release_id"] == 1 for r in rows)


def test_artist_name_returns_canonical_name(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        assert graph.artist_name(100) == "Alice"
        assert graph.artist_name(999_999) is None


def test_stats_counts_artists_and_capped_releases(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        stats = graph.stats()
    # R5 and R7 have only 1 distinct linked artist each (below the 2-artist floor).
    assert stats["non_traversal_release_count"] == 2

    with CreditGraph.open(dataset_root, max_artists_per_release=3) as tight_graph:
        tight_stats = tight_graph.stats()
    # Additionally, R4 (Mega Compilation, 4 distinct artists) exceeds a cap of 3.
    assert tight_stats["non_traversal_release_count"] == 3


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


def test_credit_row_count_counts_linked_credit_rows(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        # Alice (100): R1, R4, R5.
        assert graph.credit_row_count(100) == 3
        assert graph.credit_row_count(999_999) == 0


def test_credit_row_counts_matches_individual_calls(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        individual = {
            artist_id: graph.credit_row_count(artist_id) for artist_id in (100, 200, 300, 999_999)
        }
        batched = graph.credit_row_counts([100, 200, 300, 999_999])

    # An artist with zero credits is simply absent -- callers use .get(id, 0).
    assert batched == {aid: count for aid, count in individual.items() if count > 0}
    assert graph.credit_row_counts([]) == {}


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
        counts = graph.credit_row_counts(many_ids)
        assert counts == graph.credit_row_counts([100, 200, 300])

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


def _hub_credit(release_id: int, *, artist_id: int, name: str) -> dict[str, object]:
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
            _hub_credit(1, artist_id=1000, name="S"),
            _hub_credit(1, artist_id=2000, name="H"),
            _hub_credit(2, artist_id=2000, name="H"),
            _hub_credit(2, artist_id=3001, name="P1"),
            _hub_credit(3, artist_id=2000, name="H"),
            _hub_credit(3, artist_id=3002, name="P2"),
            _hub_credit(4, artist_id=2000, name="H"),
            _hub_credit(4, artist_id=4000, name="T"),
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
            _hub_credit(1, artist_id=1000, name="S"),
            _hub_credit(1, artist_id=2000, name="H"),
            _hub_credit(2, artist_id=2000, name="H"),
            _hub_credit(2, artist_id=3001, name="P1"),
            _hub_credit(3, artist_id=2000, name="H"),
            _hub_credit(3, artist_id=3002, name="P2"),
            _hub_credit(4, artist_id=1000, name="S"),
            _hub_credit(4, artist_id=5000, name="N"),
            _hub_credit(5, artist_id=5000, name="N"),
            _hub_credit(5, artist_id=4000, name="T"),
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
