import gzip
import json
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")
pytest.importorskip("duckdb")

from lxml import etree

from networked_players_catalog.cli import main
from networked_players_catalog.discogs.masters import iter_masters
from networked_players_catalog.discogs.parquet import write_master_dataset
from networked_players_catalog.discogs.validation import ValidationError, validate_master_dataset

FIXTURE = Path(__file__).parent / "fixtures" / "masters.xml"
SNAPSHOT = "20260501"
SOURCE_URL = "https://example.test/discogs_20260501_masters.xml.gz"


def test_stream_parser_preserves_album_fields_and_identity(tmp_path: Path) -> None:
    compressed = tmp_path / "masters.xml.gz"
    with gzip.open(compressed, "wb") as output:
        output.write(FIXTURE.read_bytes())

    records = list(iter_masters(compressed, snapshot_date=SNAPSHOT, source_url=SOURCE_URL))
    assert [record.master["master_id"] for record in records] == [501, 502]

    first = records[0]
    assert first.master["main_release_id"] == 101
    assert first.master["title"] == "Connected Album"
    assert first.master["year"] == 2001
    assert first.master["genres"] == ["Rock", "Funk / Soul"]
    assert first.master["styles"] == ["Psychedelic Rock"]

    linked = next(row for row in first.artists if row["name"] == "Alpha Group")
    assert linked["artist_id"] == 11
    assert linked["anv"] == "Alpha"
    assert linked["playable_identity"] is True

    unlinked = next(row for row in first.artists if row["name"] == "Unlinked Collective")
    assert unlinked["artist_id"] is None
    assert unlinked["is_linked"] is False
    assert unlinked["playable_identity"] is False

    # <year>0</year> is not a real year -- normalized to null like other
    # non-positive integers, never a fake playable value.
    sparse = records[1]
    assert sparse.master["year"] is None
    assert sparse.master["genres"] == []


def test_bounded_early_termination() -> None:
    records = list(
        iter_masters(FIXTURE, snapshot_date=SNAPSHOT, source_url=SOURCE_URL, max_masters=1)
    )
    assert len(records) == 1
    assert records[0].master["master_id"] == 501


def test_malformed_input_fails_loudly(tmp_path: Path) -> None:
    broken = tmp_path / "broken.xml"
    broken.write_text("<masters><master id='1'><title>Unclosed")
    with pytest.raises(etree.XMLSyntaxError):
        list(iter_masters(broken, snapshot_date=SNAPSHOT, source_url=SOURCE_URL))


def test_parquet_round_trip_and_validation(tmp_path: Path) -> None:
    records = iter_masters(FIXTURE, snapshot_date=SNAPSHOT, source_url=SOURCE_URL)
    manifest = write_master_dataset(
        records, tmp_path, snapshot_date=SNAPSHOT, source_url=SOURCE_URL, chunk_masters=1
    )
    dataset = tmp_path / f"snapshot={SNAPSHOT}"
    assert manifest["counts"] == {"masters": 2, "master_artists": 4}
    assert manifest["schema_version"] == 1
    assert len(list(dataset.glob("table=masters/*.parquet"))) == 2

    metrics = validate_master_dataset(dataset)
    assert metrics["master_rows"] == 2
    assert metrics["master_artist_rows"] == 4
    assert metrics["orphan_master_artists"] == 0
    assert metrics["invalid_linked_artist_ids"] == 0
    assert metrics["masters_missing_main_release"] == 0


def test_validation_rejects_manifest_count_mismatch(tmp_path: Path) -> None:
    records = iter_masters(FIXTURE, snapshot_date=SNAPSHOT, source_url=SOURCE_URL)
    write_master_dataset(records, tmp_path, snapshot_date=SNAPSHOT, source_url=SOURCE_URL)
    dataset = tmp_path / f"snapshot={SNAPSHOT}"
    manifest_path = dataset / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["counts"]["master_artists"] += 1
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    with pytest.raises(ValidationError, match="manifest_master_artists_count_mismatch"):
        validate_master_dataset(dataset)


def test_empty_dump_raises(tmp_path: Path) -> None:
    source = tmp_path / "empty.xml"
    source.write_text("<?xml version='1.0'?><masters></masters>")
    records = iter_masters(source, snapshot_date=SNAPSHOT, source_url=SOURCE_URL)
    with pytest.raises(ValueError, match="no master records"):
        write_master_dataset(
            records, tmp_path / "out", snapshot_date=SNAPSHOT, source_url=SOURCE_URL
        )


def test_immutable_without_overwrite(tmp_path: Path) -> None:
    records = iter_masters(FIXTURE, snapshot_date=SNAPSHOT, source_url=SOURCE_URL)
    write_master_dataset(records, tmp_path, snapshot_date=SNAPSHOT, source_url=SOURCE_URL)
    with pytest.raises(FileExistsError):
        write_master_dataset(
            iter_masters(FIXTURE, snapshot_date=SNAPSHOT, source_url=SOURCE_URL),
            tmp_path,
            snapshot_date=SNAPSHOT,
            source_url=SOURCE_URL,
        )


def test_cli_wiring(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(
        [
            "parse-masters",
            "--input",
            str(FIXTURE),
            "--snapshot",
            SNAPSHOT,
            "--source-url",
            SOURCE_URL,
            "--output-root",
            str(tmp_path),
        ]
    )
    assert exit_code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["counts"] == {"masters": 2, "master_artists": 4}

    exit_code = main(["validate-masters", "--dataset", str(tmp_path / f"snapshot={SNAPSHOT}")])
    assert exit_code == 0
    metrics = json.loads(capsys.readouterr().out)
    assert metrics["master_rows"] == 2
