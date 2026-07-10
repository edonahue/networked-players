"""Tests for the private-seed import contract."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from networked_players_catalog.discogs.seed import SeedImportError, SeedManifest, import_seed_csv

FIXTURE = Path(__file__).parents[3] / "data" / "samples" / "discogs-collection-export.csv"


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_valid_seed_extracts_only_release_ids() -> None:
    seed = import_seed_csv(FIXTURE)
    assert seed.release_ids == [101, 102, 103]
    assert seed.seed_version == 1


def test_seed_never_captures_other_columns(tmp_path: Path) -> None:
    csv_path = tmp_path / "export.csv"
    _write_csv(
        csv_path,
        [
            {
                "Catalog#": "SECRET-1",
                "Artist": "Confidential Artist",
                "Title": "Private Title",
                "Label": "Sensitive Label",
                "Format": "Vinyl",
                "Rating": "5",
                "Released": "1999",
                "release_id": "123456",
                "CollectionFolder": "Wishlist",
                "Date Added": "2020-01-01",
                "Collection Media Condition": "Mint",
                "Collection Sleeve Condition": "Mint",
                "Collection Notes": "paid $500 cash, do not tell anyone",
            }
        ],
    )
    seed = import_seed_csv(csv_path)
    seed_payload = seed.to_dict()
    assert set(seed_payload) == {"seed_version", "source", "imported_at", "release_ids"}
    # imported_at is generated metadata and can coincidentally contain a numeric
    # substring from a discarded private column (for example "500" in microseconds).
    # Scan only the source-derived fields when asserting that columns were not retained.
    source_derived = {key: value for key, value in seed_payload.items() if key != "imported_at"}
    payload = json.dumps(source_derived)
    assert seed.release_ids == [123456]
    for forbidden in (
        "SECRET",
        "Confidential",
        "Private Title",
        "Sensitive",
        "500",
        "cash",
        "Wishlist",
        "Mint",
    ):
        assert forbidden not in payload


def test_malformed_seed_missing_column(tmp_path: Path) -> None:
    csv_path = tmp_path / "export.csv"
    _write_csv(csv_path, [{"Artist": "No release_id column here"}])
    with pytest.raises(SeedImportError, match="release_id"):
        import_seed_csv(csv_path)


def test_malformed_seed_non_integer_id(tmp_path: Path) -> None:
    csv_path = tmp_path / "export.csv"
    _write_csv(csv_path, [{"release_id": "not-a-number"}])
    with pytest.raises(SeedImportError, match="not an integer"):
        import_seed_csv(csv_path)


def test_empty_seed_rejected(tmp_path: Path) -> None:
    csv_path = tmp_path / "export.csv"
    _write_csv(csv_path, [{"release_id": ""}])
    with pytest.raises(SeedImportError, match="no valid release"):
        import_seed_csv(csv_path)


def test_duplicate_ids_deduplicated(tmp_path: Path) -> None:
    csv_path = tmp_path / "export.csv"
    _write_csv(csv_path, [{"release_id": "5"}, {"release_id": "5"}, {"release_id": "3"}])
    seed = import_seed_csv(csv_path)
    assert seed.release_ids == [3, 5]


def test_seed_ids_absent_from_any_dataset_still_import(tmp_path: Path) -> None:
    # import-seed is dataset-independent: it never checks existence anywhere.
    csv_path = tmp_path / "export.csv"
    _write_csv(csv_path, [{"release_id": "999999999"}])
    seed = import_seed_csv(csv_path)
    assert seed.release_ids == [999999999]


def test_manifest_round_trip(tmp_path: Path) -> None:
    seed = import_seed_csv(FIXTURE)
    out = tmp_path / "seed.json"
    seed.write(out)
    assert SeedManifest.read(out) == seed


def test_cli_import_seed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from networked_players_catalog.cli import main

    output = tmp_path / "seed.json"
    exit_code = main(["import-seed", "--input", str(FIXTURE), "--output", str(output)])
    assert exit_code == 0
    captured = json.loads(capsys.readouterr().out)
    assert captured["path"] == str(output)
    assert captured["release_id_count"] == 3
    assert output.exists()
