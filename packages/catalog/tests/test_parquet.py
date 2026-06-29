from pathlib import Path

import pytest

pytest.importorskip("pyarrow")
pytest.importorskip("duckdb")

from networked_players_catalog.discogs.parquet import write_release_dataset
from networked_players_catalog.discogs.releases import iter_releases
from networked_players_catalog.discogs.validation import validate_dataset

FIXTURE = Path(__file__).parent / "fixtures" / "releases.xml"


def test_parquet_round_trip_and_duckdb_validation(tmp_path: Path) -> None:
    source_url = "https://example.test/discogs_20260501_releases.xml.gz"
    records = iter_releases(FIXTURE, snapshot_date="20260501", source_url=source_url)
    manifest = write_release_dataset(
        records,
        tmp_path,
        snapshot_date="20260501",
        source_url=source_url,
        chunk_releases=1,
    )
    dataset = tmp_path / "snapshot=20260501"
    assert manifest["counts"] == {"releases": 2, "tracks": 4, "credits": 9}
    assert len(list(dataset.glob("table=releases/*.parquet"))) == 2
    metrics = validate_dataset(dataset)
    assert metrics["release_rows"] == 2
    assert metrics["orphan_credits"] == 0


def test_empty_optional_tables_remain_queryable(tmp_path: Path) -> None:
    source = tmp_path / "minimal.xml"
    source.write_text(
        "<?xml version='1.0'?><releases>"
        "<release id='999' status='Accepted'><title>No Credits</title>"
        "<data_quality>Correct</data_quality></release></releases>"
    )
    source_url = "https://example.test/minimal.xml.gz"
    records = iter_releases(source, snapshot_date="20260501", source_url=source_url)
    manifest = write_release_dataset(
        records,
        tmp_path / "output",
        snapshot_date="20260501",
        source_url=source_url,
    )
    dataset = tmp_path / "output" / "snapshot=20260501"
    assert manifest["counts"] == {"releases": 1, "tracks": 0, "credits": 0}
    assert len(list(dataset.glob("table=tracks/*.parquet"))) == 1
    assert len(list(dataset.glob("table=credits/*.parquet"))) == 1
    metrics = validate_dataset(dataset)
    assert metrics["release_rows"] == 1
    assert metrics["orphan_tracks"] == 0
    assert metrics["orphan_credits"] == 0
