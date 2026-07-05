import json
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")
pytest.importorskip("duckdb")

import duckdb

from networked_players_catalog.cli import main
from networked_players_catalog.discogs.onehop import OneHopError, expand_one_hop
from networked_players_catalog.discogs.parquet import write_release_dataset
from networked_players_catalog.discogs.releases import iter_releases
from networked_players_catalog.discogs.seed import SeedManifest
from networked_players_catalog.discogs.validation import validate_dataset

FIXTURE = Path(__file__).parent / "fixtures" / "onehop_releases.xml"
SNAPSHOT = "20260501"


def _write_source_dataset(tmp_path: Path) -> Path:
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


def _write_seed(tmp_path: Path, release_ids: list[int]) -> Path:
    seed_path = tmp_path / "seed.json"
    SeedManifest(
        seed_version=1,
        source="synthetic-test-seed",
        imported_at="2026-07-04T00:00:00+00:00",
        release_ids=release_ids,
    ).write(seed_path)
    return seed_path


def _column(dataset: Path, table: str, column: str) -> list[object]:
    glob = str(dataset / f"table={table}" / "*.parquet")
    rows = (
        duckdb.connect()
        .execute(f"SELECT {column} FROM read_parquet('{glob}') ORDER BY 1")
        .fetchall()
    )
    return [row[0] for row in rows]


def test_frontier_retention_and_evidence(tmp_path: Path) -> None:
    dataset = _write_source_dataset(tmp_path)
    seed_path = _write_seed(tmp_path, [101])

    manifest = expand_one_hop(seed_path, dataset, tmp_path / "onehop")
    output = tmp_path / "onehop" / f"snapshot={SNAPSHOT}"

    # Frontier: every playable credited artist on the seed release with a
    # performer-caliber credit -- nothing from the unlinked names (Unlinked
    # Orchestra, Anonymous Choir), and not artist 21 (Pat Producer), whose
    # only credit is "Producer, Engineer" -- a pure non-performer role.
    assert _column(output, "frontier_artists", "artist_id") == [11, 12, 31, 32]

    # Retention: the seed release plus the one-hop release sharing artist 11.
    # 104 (unrelated artist) and 105 (only a *non-linked* name overlaps the
    # seed) must both be excluded -- non-linked names never drive retention.
    assert _column(output, "releases", "release_id") == [101, 103]
    assert _column(output, "seed_releases", "release_id") == [101]

    # Evidence: ALL credit rows of retained releases survive, including the
    # non-linked evidence rows on the seed release AND artist 21's
    # non-performer credit -- excluded from the frontier, not from evidence.
    credit_names = _column(output, "credits", "name")
    assert "Unlinked Orchestra" in credit_names
    assert "Anonymous Choir" in credit_names
    assert "Pat Producer" in credit_names
    counts = manifest["counts"]
    assert counts == {
        "releases": 2,
        "tracks": 4,
        "credits": 10,
        "frontier_artists": 4,
        "seed_releases": 1,
    }

    expansion = manifest["expansion"]
    assert isinstance(expansion, dict)
    assert expansion["kind"] == "one-hop"
    assert expansion["frontier_artist_count"] == 4
    assert expansion["retained_release_count"] == 2
    assert expansion["seed_release_count"] == 1
    assert expansion["seed_releases_missing_from_snapshot"] == 0
    # The manifest carries seed aggregates only -- never the ID list itself.
    assert "release_ids" not in json.dumps(manifest)


def test_placeholder_hub_artists_excluded_from_frontier(tmp_path: Path) -> None:
    dataset = _write_source_dataset(tmp_path)
    seed_path = _write_seed(tmp_path, [110])

    manifest = expand_one_hop(seed_path, dataset, tmp_path / "onehop")
    output = tmp_path / "onehop" / f"snapshot={SNAPSHOT}"

    # Release 110 is credited to both artist 40 (real) and artist 194
    # ("Various Artists", a Discogs placeholder) -- only 40 should join the
    # frontier.
    assert _column(output, "frontier_artists", "artist_id") == [40]

    # Release 111 is credited ONLY to artist 194. If the placeholder weren't
    # excluded, it would join the frontier and retain 111 too -- it must not.
    assert _column(output, "releases", "release_id") == [110]

    expansion = manifest["expansion"]
    assert isinstance(expansion, dict)
    assert expansion["frontier_artist_count"] == 1


def test_pure_non_performer_role_excluded_from_frontier(tmp_path: Path) -> None:
    dataset = _write_source_dataset(tmp_path)
    seed_path = _write_seed(tmp_path, [112])

    manifest = expand_one_hop(seed_path, dataset, tmp_path / "onehop")
    output = tmp_path / "onehop" / f"snapshot={SNAPSHOT}"

    # Release 112 credits artist 41 (main artist, real) and artist 42 (Master
    # Ray, "Mastered By" only -- a pure non-performer role). Only 41 joins
    # the frontier.
    assert _column(output, "frontier_artists", "artist_id") == [41]

    # Release 113 is credited ONLY to artist 42 via "Mastered By" (plus an
    # unrelated artist 99). If the role filter weren't applied, artist 42
    # would join the frontier and retain 113 too -- it must not.
    assert _column(output, "releases", "release_id") == [112]

    # Evidence: artist 42's credit still survives on the retained release.
    assert "Master Ray" in _column(output, "credits", "name")

    expansion = manifest["expansion"]
    assert isinstance(expansion, dict)
    assert expansion["frontier_artist_count"] == 1


def test_output_columns_are_not_contaminated_by_hive_partition_inference(
    tmp_path: Path,
) -> None:
    """Regression test: the staging path is literally .../snapshot=X/table=Y/,
    which DuckDB's read_parquet() auto-detects as Hive partition columns
    unless hive_partitioning=false is passed -- confirmed to silently inject
    spurious `snapshot`/`table` columns into any `SELECT *`/`r.*` result
    (and therefore into the written output, since expand_one_hop's COPY
    statements select r.*/t.*/c.*). This asserts the real on-disk schema
    (via pq.ParquetFile, which reads the file's own embedded schema with no
    glob/hive inference of its own) contains exactly the expected columns.
    """
    import pyarrow.parquet as pq

    dataset = _write_source_dataset(tmp_path)
    seed_path = _write_seed(tmp_path, [101])
    expand_one_hop(seed_path, dataset, tmp_path / "onehop")
    output = tmp_path / "onehop" / f"snapshot={SNAPSHOT}"

    for table in ("releases", "tracks", "credits"):
        part = next((output / f"table={table}").glob("*.parquet"))
        columns = set(pq.ParquetFile(part).schema.names)
        assert "table" not in columns
        assert "snapshot" not in columns


def test_expansion_is_deterministic(tmp_path: Path) -> None:
    dataset = _write_source_dataset(tmp_path)
    seed_path = _write_seed(tmp_path, [101])

    first = expand_one_hop(seed_path, dataset, tmp_path / "run-a")
    second = expand_one_hop(seed_path, dataset, tmp_path / "run-b")

    assert first["counts"] == second["counts"]
    hashes_a = {f["path"]: f["sha256"] for f in first["files"]}  # type: ignore[union-attr,index]
    hashes_b = {f["path"]: f["sha256"] for f in second["files"]}  # type: ignore[union-attr,index]
    assert hashes_a == hashes_b


def test_boundedness_guard_writes_nothing(tmp_path: Path) -> None:
    dataset = _write_source_dataset(tmp_path)
    seed_path = _write_seed(tmp_path, [101])

    with pytest.raises(OneHopError, match="exceeds"):
        expand_one_hop(seed_path, dataset, tmp_path / "onehop", max_retained_releases=1)
    output_root = tmp_path / "onehop"
    assert not (output_root / f"snapshot={SNAPSHOT}").exists()
    if output_root.exists():
        assert list(output_root.glob(".snapshot=*")) == []  # staging cleaned up


def test_empty_frontier_raises(tmp_path: Path) -> None:
    dataset = _write_source_dataset(tmp_path)
    seed_path = _write_seed(tmp_path, [999_999])

    with pytest.raises(OneHopError, match="empty frontier"):
        expand_one_hop(seed_path, dataset, tmp_path / "onehop")


def test_missing_seed_release_is_reported_not_fatal(tmp_path: Path) -> None:
    dataset = _write_source_dataset(tmp_path)
    seed_path = _write_seed(tmp_path, [101, 888_888])

    manifest = expand_one_hop(seed_path, dataset, tmp_path / "onehop")
    expansion = manifest["expansion"]
    assert isinstance(expansion, dict)
    assert expansion["seed_releases_missing_from_snapshot"] == 1
    output = tmp_path / "onehop" / f"snapshot={SNAPSHOT}"
    assert _column(output, "seed_releases", "release_id") == [101]


def test_immutable_without_overwrite(tmp_path: Path) -> None:
    dataset = _write_source_dataset(tmp_path)
    seed_path = _write_seed(tmp_path, [101])

    expand_one_hop(seed_path, dataset, tmp_path / "onehop")
    with pytest.raises(FileExistsError):
        expand_one_hop(seed_path, dataset, tmp_path / "onehop")
    expand_one_hop(seed_path, dataset, tmp_path / "onehop", overwrite=True)


def test_generic_validation_passes_on_output(tmp_path: Path) -> None:
    dataset = _write_source_dataset(tmp_path)
    seed_path = _write_seed(tmp_path, [101])

    expand_one_hop(seed_path, dataset, tmp_path / "onehop")
    metrics = validate_dataset(tmp_path / "onehop" / f"snapshot={SNAPSHOT}")
    assert metrics["release_rows"] == 2
    assert metrics["orphan_tracks"] == 0
    assert metrics["orphan_credits"] == 0


def test_cli_wiring(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dataset = _write_source_dataset(tmp_path)
    seed_path = _write_seed(tmp_path, [101])

    exit_code = main(
        [
            "expand-one-hop",
            "--seed",
            str(seed_path),
            "--dataset",
            str(dataset),
            "--output-root",
            str(tmp_path / "onehop"),
        ]
    )
    assert exit_code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["expansion"]["retained_release_count"] == 2
