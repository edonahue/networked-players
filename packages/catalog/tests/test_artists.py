import gzip
import json
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")

from lxml import etree

from networked_players_catalog.cli import main
from networked_players_catalog.discogs.artists import iter_artist_relations
from networked_players_catalog.discogs.parquet import write_artist_relations_dataset

FIXTURE = Path(__file__).parent / "fixtures" / "artists.xml"
SNAPSHOT = "20260501"
SOURCE_URL = "https://example.test/discogs_20260501_artists.xml.gz"


def test_stream_parser_extracts_group_and_member_relations(tmp_path: Path) -> None:
    compressed = tmp_path / "artists.xml.gz"
    with gzip.open(compressed, "wb") as output:
        output.write(FIXTURE.read_bytes())

    records = list(iter_artist_relations(compressed, snapshot_date=SNAPSHOT, source_url=SOURCE_URL))
    assert [record.artist_id for record in records] == [2, 26, 50]

    group_record = records[0]
    assert group_record.relations == [
        {
            "snapshot_date": SNAPSHOT,
            "artist_id": 2,
            "related_artist_id": 26,
            "related_name": "Alexi Delano",
            "relation": "has_member",
            "source_url": SOURCE_URL,
        },
        {
            "snapshot_date": SNAPSHOT,
            "artist_id": 2,
            "related_artist_id": 27,
            "related_name": "Cari Lekebusch",
            "relation": "has_member",
            "source_url": SOURCE_URL,
        },
    ]

    member_record = records[1]
    assert member_record.relations == [
        {
            "snapshot_date": SNAPSHOT,
            "artist_id": 26,
            "related_artist_id": 2,
            "related_name": "Mr. James Barth & A.D.",
            "relation": "member_of",
            "source_url": SOURCE_URL,
        },
    ]

    # Most artist records have neither <groups> nor <members> -- zero rows,
    # not an error and not a skipped record.
    solo_record = records[2]
    assert solo_record.relations == []


def test_bounded_early_termination() -> None:
    records = list(
        iter_artist_relations(FIXTURE, snapshot_date=SNAPSHOT, source_url=SOURCE_URL, max_artists=1)
    )
    assert len(records) == 1
    assert records[0].artist_id == 2


def test_malformed_input_fails_loudly(tmp_path: Path) -> None:
    broken = tmp_path / "broken.xml"
    broken.write_text("<artists><artist><id>1</id><name>Unclosed")
    with pytest.raises(etree.XMLSyntaxError):
        list(iter_artist_relations(broken, snapshot_date=SNAPSHOT, source_url=SOURCE_URL))


def test_parquet_round_trip(tmp_path: Path) -> None:
    records = iter_artist_relations(FIXTURE, snapshot_date=SNAPSHOT, source_url=SOURCE_URL)
    manifest = write_artist_relations_dataset(
        records, tmp_path, snapshot_date=SNAPSHOT, source_url=SOURCE_URL, chunk_artists=1
    )
    dataset = tmp_path / f"snapshot={SNAPSHOT}"
    assert manifest["counts"] == {"artists_seen": 3, "artist_relations": 3}
    assert manifest["schema_version"] == 1
    assert (dataset / "table=artist_relations").exists()

    import duckdb

    total = duckdb.sql(
        f"SELECT count(*) FROM read_parquet('{dataset}/table=artist_relations/*.parquet')"
    ).fetchone()[0]
    assert total == 3
    has_member_pairs = duckdb.sql(
        f"SELECT artist_id, related_artist_id FROM "
        f"read_parquet('{dataset}/table=artist_relations/*.parquet') "
        "WHERE relation = 'has_member' ORDER BY related_artist_id"
    ).fetchall()
    assert has_member_pairs == [(2, 26), (2, 27)]


def test_empty_dump_raises(tmp_path: Path) -> None:
    source = tmp_path / "empty.xml"
    source.write_text("<?xml version='1.0'?><artists></artists>")
    records = iter_artist_relations(source, snapshot_date=SNAPSHOT, source_url=SOURCE_URL)
    with pytest.raises(ValueError, match="no artist records"):
        write_artist_relations_dataset(
            records, tmp_path / "out", snapshot_date=SNAPSHOT, source_url=SOURCE_URL
        )


def test_immutable_without_overwrite(tmp_path: Path) -> None:
    records = iter_artist_relations(FIXTURE, snapshot_date=SNAPSHOT, source_url=SOURCE_URL)
    write_artist_relations_dataset(records, tmp_path, snapshot_date=SNAPSHOT, source_url=SOURCE_URL)
    with pytest.raises(FileExistsError):
        write_artist_relations_dataset(
            iter_artist_relations(FIXTURE, snapshot_date=SNAPSHOT, source_url=SOURCE_URL),
            tmp_path,
            snapshot_date=SNAPSHOT,
            source_url=SOURCE_URL,
        )


def test_cli_wiring(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(
        [
            "parse-artist-relations",
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
    assert printed["counts"] == {"artists_seen": 3, "artist_relations": 3}
