import gzip
from pathlib import Path

from lxml import etree

from networked_players_catalog.discogs.releases import iter_releases, parse_release_element

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
    assert len(first.tracks) == 3
    nested_track = next(row for row in first.tracks if row["title"] == "Nested Part")
    assert nested_track["track_path"] == "1.0"
    assert nested_track["parent_track_index"] == 1

    unlinked = next(row for row in first.credits if row["name"] == "Unlinked Orchestra")
    assert unlinked["artist_id"] is None
    assert unlinked["is_linked"] is False
    assert unlinked["playable_identity"] is False
    assert unlinked["role_text"] == "Strings"
    assert unlinked["credited_tracks_text"] == "A2"

    track_credit = next(row for row in first.credits if row["name"] == "Casey Guitar")
    assert track_credit["credit_scope"] == "track_credit"
    assert track_credit["track_position"] == "A1"
    assert track_credit["track_path"] == "0"
    assert track_credit["anv"] == "C. Guitar"

    nested_credit = next(row for row in first.credits if row["name"] == "Nested Player")
    assert nested_credit["track_path"] == "1.0"
    assert nested_credit["track_position"] == "A2a"


def test_empty_status_attribute_normalizes_to_none() -> None:
    element = etree.fromstring('<release id="999" status=""><title>Untitled</title></release>')
    parsed = parse_release_element(
        element,
        snapshot_date="20260501",
        source_url="https://example.test/releases.xml.gz",
    )
    assert parsed.release["status"] is None


def test_structured_formats_preserve_rows_and_descriptions() -> None:
    element = etree.fromstring(
        """<release id="999"><title>Format Fixture</title><formats>
          <format name="Vinyl" qty="2" text="180 Gram">
            <descriptions><description>LP</description><description>Album</description></descriptions>
          </format>
          <format name="CD" qty="bad" text="">
            <descriptions><description>Compilation</description></descriptions>
          </format>
        </formats></release>"""
    )
    parsed = parse_release_element(
        element,
        snapshot_date="20260501",
        source_url="https://example.test/releases.xml.gz",
    )
    assert parsed.formats == [
        {
            "snapshot_date": "20260501",
            "release_id": 999,
            "format_index": 0,
            "format_name": "Vinyl",
            "quantity": 2,
            "format_text": "180 Gram",
            "descriptions": ["LP", "Album"],
        },
        {
            "snapshot_date": "20260501",
            "release_id": 999,
            "format_index": 1,
            "format_name": "CD",
            "quantity": None,
            "format_text": None,
            "descriptions": ["Compilation"],
        },
    ]


def test_a_quantity_too_large_for_int32_is_treated_as_unparseable_not_a_crash() -> None:
    """Real production bug (found migrating the real 20260601 dump to schema
    v3): one release's real qty attribute was large enough that even
    Python's arbitrary-precision int overflowed pyarrow's int32 quantity
    column, crashing a ~2-hour full-dump run at the write step. quantity
    isn't a barcode or catalog number -- nothing legitimate calls for a
    value outside a small pressing-count range -- so an out-of-range value
    is treated exactly like the existing qty="bad" case above: the format
    row survives with quantity=None, never a parse failure that takes down
    the whole release, let alone the whole run."""
    element = etree.fromstring(
        """<release id="1000"><title>Overflow Fixture</title><formats>
          <format name="Vinyl" qty="99999999999999999999" text="">
            <descriptions><description>LP</description></descriptions>
          </format>
        </formats></release>"""
    )
    parsed = parse_release_element(
        element,
        snapshot_date="20260501",
        source_url="https://example.test/releases.xml.gz",
    )
    assert parsed.formats == [
        {
            "snapshot_date": "20260501",
            "release_id": 1000,
            "format_index": 0,
            "format_name": "Vinyl",
            "quantity": None,
            "format_text": None,
            "descriptions": ["LP"],
        }
    ]


def test_a_quantity_exactly_at_int32_max_is_kept() -> None:
    element = etree.fromstring(
        """<release id="1001"><title>Boundary Fixture</title><formats>
          <format name="Vinyl" qty="2147483647" text="">
            <descriptions></descriptions>
          </format>
        </formats></release>"""
    )
    parsed = parse_release_element(
        element,
        snapshot_date="20260501",
        source_url="https://example.test/releases.xml.gz",
    )
    assert parsed.formats[0]["quantity"] == 2147483647


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
