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
    assert manifest["counts"] == {"releases": 2, "tracks": 3, "credits": 8}
    assert len(list(dataset.glob("table=releases/*.parquet"))) == 2
    metrics = validate_dataset(dataset)
    assert metrics["release_rows"] == 2
    assert metrics["orphan_credits"] == 0
