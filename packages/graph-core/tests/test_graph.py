from __future__ import annotations

from pathlib import Path

import pytest

from networked_players_graph_core.graph import CreditGraph, GraphError


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
