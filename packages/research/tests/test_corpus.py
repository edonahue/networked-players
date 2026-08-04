from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from networked_players_research.corpus import (
    AmbiguousSeedError,
    NoSeedMatchError,
    SeedResolution,
    TopicCorpusError,
    build_topic_corpus,
    resolve_artist_seed,
)


def _credits_view(dataset_root: Path) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(database=":memory:")
    glob = str(dataset_root / "table=credits" / "*.parquet")
    connection.execute(f"CREATE VIEW credits AS SELECT * FROM read_parquet('{glob}')")
    return connection


def test_resolve_artist_seed_matches_a_real_name(dataset_root: Path) -> None:
    connection = _credits_view(dataset_root)
    try:
        resolution = resolve_artist_seed(connection, "Jane")
    finally:
        connection.close()
    # Jane has 2 credit rows (release_artist + track_artist) on each of her
    # two releases -- 4 total.
    assert resolution == SeedResolution(artist_id=100, name="Jane", matched_credits=4)


def test_resolve_artist_seed_is_case_and_whitespace_insensitive(dataset_root: Path) -> None:
    connection = _credits_view(dataset_root)
    try:
        resolution = resolve_artist_seed(connection, "  jANE  ")
    finally:
        connection.close()
    assert resolution.artist_id == 100


def test_resolve_artist_seed_raises_on_no_match(dataset_root: Path) -> None:
    connection = _credits_view(dataset_root)
    try:
        with pytest.raises(NoSeedMatchError):
            resolve_artist_seed(connection, "Nobody")
    finally:
        connection.close()


def test_resolve_artist_seed_raises_on_ambiguous_match(dataset_root: Path) -> None:
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(
            "CREATE VIEW credits AS SELECT * FROM (VALUES "
            "(100, 'Same Name'), (200, 'Same Name')) AS t(artist_id, name)"
        )
        with pytest.raises(AmbiguousSeedError):
            resolve_artist_seed(connection, "Same Name")
    finally:
        connection.close()


def test_build_topic_corpus_retains_janes_releases_and_shared_personnel(
    dataset_root: Path, tmp_path: Path
) -> None:
    output_root = tmp_path / "corpus"
    manifest = build_topic_corpus([100], dataset_root, output_root, topic="Jane", hop_tier=1)
    assert manifest["topic"]["frontier_artist_count"] == 1
    # Jane appears on releases 1 and 2; Bob (on release 1) and Cara (on
    # release 2) are NOT retained themselves, since retention is driven by
    # the seed artist's own credits, not their collaborators' -- a genuine
    # 1-hop-from-artist expansion, not a 2-hop one.
    assert manifest["topic"]["retained_release_count"] == 2
    assert manifest["counts"]["releases"] == 2

    snapshot_root = output_root / "snapshot=20260601"
    assert snapshot_root.is_dir()
    connection = duckdb.connect(database=":memory:")
    try:
        titles = connection.execute(
            f"SELECT title FROM read_parquet('{snapshot_root}/table=releases/*.parquet') "
            "ORDER BY title"
        ).fetchall()
    finally:
        connection.close()
    assert titles == [("Jane's First Album",), ("Jane's Second Album",)]


def test_build_topic_corpus_rejects_hop_tier_above_one(dataset_root: Path, tmp_path: Path) -> None:
    with pytest.raises(TopicCorpusError):
        build_topic_corpus([100], dataset_root, tmp_path / "corpus", topic="Jane", hop_tier=2)


def test_build_topic_corpus_rejects_empty_seed(dataset_root: Path, tmp_path: Path) -> None:
    with pytest.raises(TopicCorpusError):
        build_topic_corpus([], dataset_root, tmp_path / "corpus", topic="Jane")


def test_build_topic_corpus_refuses_to_overwrite_without_flag(
    dataset_root: Path, tmp_path: Path
) -> None:
    output_root = tmp_path / "corpus"
    build_topic_corpus([100], dataset_root, output_root, topic="Jane")
    with pytest.raises(FileExistsError):
        build_topic_corpus([100], dataset_root, output_root, topic="Jane")
    # overwrite=True succeeds
    build_topic_corpus([100], dataset_root, output_root, topic="Jane", overwrite=True)


def test_build_topic_corpus_is_content_hash_versioned(dataset_root: Path, tmp_path: Path) -> None:
    manifest_a = build_topic_corpus(
        [100], dataset_root, tmp_path / "corpus-a", topic="Jane", hop_tier=1
    )
    manifest_b = build_topic_corpus(
        [100], dataset_root, tmp_path / "corpus-b", topic="Jane", hop_tier=1
    )
    assert manifest_a["topic"]["corpus_version"] == manifest_b["topic"]["corpus_version"]

    manifest_c = build_topic_corpus(
        [200], dataset_root, tmp_path / "corpus-c", topic="Bob", hop_tier=1
    )
    assert manifest_c["topic"]["corpus_version"] != manifest_a["topic"]["corpus_version"]
