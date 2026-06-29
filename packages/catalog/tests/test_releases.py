import gzip
from pathlib import Path

from networked_players_catalog.discogs.releases import iter_releases

FIXTURE = Path(__file__).parent / "fixtures" / "releases.xml"


def test_stream_parser_preserves_credit_scope_and_identity(tmp_path: Path) -> None:
    compressed = tmp_path / "releases.xml.gz"
    with gzip.open(compressed, "wb") as output:
        output.write(FIXTURE.read_bytes())

    records = list(
        iter_releases(
            compressed,
            snapshot_date="20260501",
            source_url="https://example.test/releases.xml.gz",
        )
    )
    assert [record.release["release_id"] for record in records] == [101, 102]
    first = records[0]
    assert first.release["master_id"] == 501
    assert first.release["master_is_main_release"] is True
    assert len(first.tracks) == 2

    unlinked = [row for row in first.credits if row["name"] == "Unlinked Orchestra"][0]
    assert unlinked["artist_id"] is None
    assert unlinked["is_linked"] is False
    assert unlinked["playable_identity"] is False
    assert unlinked["role_text"] == "Strings"
    assert unlinked["credited_tracks_text"] == "A2"

    track_credit = [row for row in first.credits if row["name"] == "Casey Guitar"][0]
    assert track_credit["credit_scope"] == "track_credit"
    assert track_credit["track_position"] == "A1"
    assert track_credit["anv"] == "C. Guitar"


def test_stream_parser_can_stop_after_a_bounded_slice() -> None:
    records = list(
        iter_releases(
            FIXTURE,
            snapshot_date="20260501",
            source_url="https://example.test/releases.xml.gz",
            max_releases=1,
        )
    )
    assert len(records) == 1
    assert records[0].release["release_id"] == 101
