"""CLI round-trip for `resolve-editorial-albums` -- the command that turns a
human-curated query list into the committed, public
`data/albums/editorial-seed-v1.json`. See
data/contracts/editorial-seed-v1.md and
packages/graph-core/tests/test_editorial_seed.py for the resolution-logic
unit tests this wraps."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")
pytest.importorskip("duckdb")

from networked_players_catalog.cli import main
from networked_players_catalog.discogs.parquet import write_release_dataset
from networked_players_catalog.discogs.releases import iter_releases

FIXTURE = Path(__file__).parent / "fixtures" / "onehop_releases.xml"
SNAPSHOT = "20260501"


def _write_full_dataset(tmp_path: Path) -> Path:
    source_url = "https://example.test/discogs_20260501_releases.xml.gz"
    records = iter_releases(FIXTURE, snapshot_date=SNAPSHOT, source_url=source_url)
    write_release_dataset(
        records,
        tmp_path / "full",
        snapshot_date=SNAPSHOT,
        source_url=source_url,
        chunk_releases=2,
    )
    return tmp_path / "full" / f"snapshot={SNAPSHOT}"


def _write_queries(tmp_path: Path, queries: list[dict]) -> Path:
    path = tmp_path / "queries.json"
    path.write_text(json.dumps({"queries": queries}))
    return path


def test_resolves_a_real_query_into_a_committed_shaped_seed(tmp_path: Path) -> None:
    dataset = _write_full_dataset(tmp_path)
    queries_path = _write_queries(
        tmp_path,
        [
            {"artist": "Alpha Group", "title": "Seed Record"},
            {"artist": "Nobody", "title": "Nothing"},
        ],
    )
    output = tmp_path / "editorial-seed.json"
    unresolved_output = tmp_path / "unresolved.json"

    exit_code = main(
        [
            "resolve-editorial-albums",
            "--dataset",
            str(dataset),
            "--queries",
            str(queries_path),
            "--output",
            str(output),
            "--unresolved-output",
            str(unresolved_output),
            "--note",
            "test fixture resolution",
        ]
    )
    assert exit_code == 0

    payload = json.loads(output.read_text())
    assert payload["schema_version"] == 1
    assert payload["kind"] == "public-editorial-seed"
    assert payload["snapshot_date"] == SNAPSHOT
    assert payload["note"] == "test fixture resolution"
    assert len(payload["albums"]) == 1
    album = payload["albums"][0]
    assert album["main_release_id"] == 101
    assert album["artist_id"] == 11
    # The committed contract's exact key set -- no eligibility dict leaked in.
    assert set(album.keys()) == {
        "query_artist",
        "query_title",
        "master_id",
        "main_release_id",
        "artist_id",
        "artist",
        "title",
        "year",
    }

    unresolved = json.loads(unresolved_output.read_text())["unresolved"]
    assert unresolved == [
        {
            "artist": "Nobody",
            "title": "Nothing",
            "reason": "no matching release in this snapshot",
        }
    ]


def test_unresolved_output_is_optional(tmp_path: Path) -> None:
    dataset = _write_full_dataset(tmp_path)
    queries_path = _write_queries(tmp_path, [{"artist": "Alpha Group", "title": "Seed Record"}])
    output = tmp_path / "editorial-seed.json"

    exit_code = main(
        [
            "resolve-editorial-albums",
            "--dataset",
            str(dataset),
            "--queries",
            str(queries_path),
            "--output",
            str(output),
        ]
    )
    assert exit_code == 0
    assert output.exists()
