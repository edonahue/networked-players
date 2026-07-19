import json
from pathlib import Path

import pytest

pytest.importorskip("duckdb")

from networked_players_catalog.cli import main
from networked_players_catalog.discogs.artist_family import (
    build_artist_family_exclusions,
    is_family_excluded_pair,
    write_artist_family_exclusions,
)
from networked_players_catalog.discogs.artists import iter_artist_relations
from networked_players_catalog.discogs.parquet import write_artist_relations_dataset

FIXTURE = Path(__file__).parent / "fixtures" / "artists.xml"
SNAPSHOT = "20260501"
SOURCE_URL = "https://example.test/discogs_20260501_artists.xml.gz"


@pytest.fixture
def relations_dataset(tmp_path: Path) -> Path:
    records = iter_artist_relations(FIXTURE, snapshot_date=SNAPSHOT, source_url=SOURCE_URL)
    write_artist_relations_dataset(records, tmp_path, snapshot_date=SNAPSHOT, source_url=SOURCE_URL)
    return tmp_path / f"snapshot={SNAPSHOT}"


def test_unions_both_mirror_directions(relations_dataset: Path) -> None:
    # Fixture: artist 2 (group) has_member 26/27 (only mirrored one direction:
    # artist 26 also carries member_of -> 2, but 27 has no reverse record at
    # all). Both member IDs must still resolve to group_act_ids = [2].
    exclusions = build_artist_family_exclusions(
        relations_dataset, artist_ids=[2, 26, 27, 50], snapshot_date=SNAPSHOT
    )
    by_person = {entry["person_id"]: entry["group_act_ids"] for entry in exclusions["entries"]}
    assert by_person[26] == [2]
    assert by_person[27] == [2]
    # Artist 50 has no relations at all -- no entry, not an empty-list entry.
    assert 50 not in by_person
    assert all(entry["source"] == "dump" for entry in exclusions["entries"])


def test_scoping_omits_unrequested_artists(relations_dataset: Path) -> None:
    exclusions = build_artist_family_exclusions(
        relations_dataset, artist_ids=[26], snapshot_date=SNAPSHOT
    )
    person_ids = {entry["person_id"] for entry in exclusions["entries"]}
    assert person_ids == {26}


def test_empty_artist_ids_raises(relations_dataset: Path) -> None:
    with pytest.raises(ValueError, match="artist_ids must be non-empty"):
        build_artist_family_exclusions(relations_dataset, artist_ids=[], snapshot_date=SNAPSHOT)


def test_is_family_excluded_pair(relations_dataset: Path) -> None:
    exclusions = build_artist_family_exclusions(
        relations_dataset, artist_ids=[2, 26, 27], snapshot_date=SNAPSHOT
    )
    # Member vs. their own group.
    assert is_family_excluded_pair(26, 2, exclusions) is True
    assert is_family_excluded_pair(2, 26, exclusions) is True
    # Bandmates (share group_act_id 2).
    assert is_family_excluded_pair(26, 27, exclusions) is True
    # Unrelated artist not in the scoped set at all.
    assert is_family_excluded_pair(26, 999, exclusions) is False
    # Same artist twice is trivially excluded.
    assert is_family_excluded_pair(26, 26, exclusions) is True


def test_write_and_cli_wiring(relations_dataset: Path, tmp_path: Path) -> None:
    output = tmp_path / "artist-family-exclusions-v1.json"
    exclusions = build_artist_family_exclusions(
        relations_dataset, artist_ids=[2, 26, 27], snapshot_date=SNAPSHOT
    )
    write_artist_family_exclusions(exclusions, output)
    reloaded = json.loads(output.read_text())
    assert reloaded == exclusions

    artist_ids_file = tmp_path / "ids.json"
    artist_ids_file.write_text(json.dumps([2, 26, 27]))
    cli_output = tmp_path / "cli-output.json"
    exit_code = main(
        [
            "build-artist-family-exclusions",
            "--dataset",
            str(relations_dataset),
            "--artist-ids-file",
            str(artist_ids_file),
            "--snapshot",
            SNAPSHOT,
            "--output",
            str(cli_output),
        ]
    )
    assert exit_code == 0
    assert json.loads(cli_output.read_text())["entries"]
