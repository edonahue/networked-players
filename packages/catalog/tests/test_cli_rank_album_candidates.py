"""CLI round-trip for `rank-album-candidates --exclude-published-catalog` --
the fix for a real measured gap (Phase 7 preflight, PR #144): the ranker had
no already-published exclusion, so 38% of a 200-candidate readiness report
were masters already in the catalog. Unit coverage for the underlying
`rank_album_candidates(already_published_master_ids=...)` parameter lives in
packages/graph-core/tests/test_analysis.py; this pins the CLI wiring only."""

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


def test_exclude_published_catalog_drops_the_named_master(tmp_path: Path) -> None:
    dataset = _write_full_dataset(tmp_path)
    baseline_output = tmp_path / "baseline.json"

    exit_code = main(
        [
            "rank-album-candidates",
            "--dataset",
            str(dataset),
            "--output",
            str(baseline_output),
        ]
    )
    assert exit_code == 0
    baseline = json.loads(baseline_output.read_text())
    # Release 101's master_id (501) is the fixture's only release with a
    # master_id at all -- the one real candidate this shape can produce.
    assert {c["master_id"] for c in baseline} == {501}

    fake_catalog = tmp_path / "albums.v1.json"
    fake_catalog.write_text(json.dumps({"albums": [{"master_id": 501}]}))
    filtered_output = tmp_path / "filtered.json"

    exit_code = main(
        [
            "rank-album-candidates",
            "--dataset",
            str(dataset),
            "--output",
            str(filtered_output),
            "--exclude-published-catalog",
            str(fake_catalog),
        ]
    )
    assert exit_code == 0
    filtered = json.loads(filtered_output.read_text())
    assert filtered == []


def test_exclude_published_catalog_tolerates_a_null_master_id(tmp_path: Path) -> None:
    """A published album resolved only by main_release_id, with no Discogs
    master, is valid (MatchedAlbum.master_id: int | None; the catalog
    validator does not require one) and must not crash the whole ranking
    run on int(None) -- it's simply skipped from the exclusion set, since
    there's no master_id to exclude by."""
    dataset = _write_full_dataset(tmp_path)
    catalog_with_null = tmp_path / "albums-with-null-master.json"
    catalog_with_null.write_text(json.dumps({"albums": [{"master_id": None}, {"master_id": 501}]}))
    output = tmp_path / "out.json"

    exit_code = main(
        [
            "rank-album-candidates",
            "--dataset",
            str(dataset),
            "--output",
            str(output),
            "--exclude-published-catalog",
            str(catalog_with_null),
        ]
    )
    assert exit_code == 0
    assert json.loads(output.read_text()) == []


def test_no_exclude_published_catalog_flag_behaves_exactly_as_before(tmp_path: Path) -> None:
    dataset = _write_full_dataset(tmp_path)
    output = tmp_path / "out.json"
    exit_code = main(["rank-album-candidates", "--dataset", str(dataset), "--output", str(output)])
    assert exit_code == 0
    assert {c["master_id"] for c in json.loads(output.read_text())} == {501}
