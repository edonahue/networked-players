"""build-public-album-catalog: the fail-closed production catalog command
(corrective slice 4.6). Every policy input is required and cross-checked for
a matching snapshot; this file proves it refuses to run without each one,
rather than silently building an under-gated catalog."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from networked_players_catalog.cli import main
from networked_players_catalog.discogs.parquet import MASTER_SCHEMAS, SCHEMAS

SNAPSHOT_DATE = "20260601"


def _release(release_id: int, title: str, *, master_id: int | None = None) -> dict[str, Any]:
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "release_id": release_id,
        "status": "Accepted",
        "title": title,
        "country": None,
        "released": "1995",
        "master_id": master_id,
        "master_is_main_release": True if master_id else None,
        "data_quality": None,
        "source_url": f"https://example.invalid/release/{release_id}",
    }


def _credit(
    release_id: int, *, artist_id: int, name: str, track_index: int | None = None
) -> dict[str, Any]:
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "release_id": release_id,
        "track_index": track_index,
        "track_path": None if track_index is None else str(track_index),
        "track_position": None if track_index is None else str(track_index + 1),
        "track_title": None if track_index is None else f"Track {track_index + 1}",
        "credit_scope": "release_artist" if track_index is None else "track_artist",
        "artist_id": artist_id,
        "name": name,
        "anv": None,
        "join_text": None,
        "role_text": None if track_index is None else "Performer",
        "credited_tracks_text": None,
        "is_linked": True,
        "playable_identity": True,
    }


def _write_onehop_dataset(root: Path, *, snapshot_date: str = SNAPSHOT_DATE) -> Path:
    dataset_root = root / f"snapshot={snapshot_date}"
    (dataset_root / "table=releases").mkdir(parents=True)
    (dataset_root / "table=credits").mkdir(parents=True)
    (dataset_root / "table=tracks").mkdir(parents=True)

    releases = [_release(1, "First Light", master_id=901), _release(2, "Third Wave")]
    credits = [
        _credit(1, artist_id=100, name="Alice"),
        _credit(1, artist_id=100, name="Alice", track_index=0),
        _credit(2, artist_id=300, name="Cara"),
        _credit(2, artist_id=300, name="Cara", track_index=0),
    ]
    pq.write_table(
        pa.Table.from_pylist(releases, schema=SCHEMAS["releases"]),
        dataset_root / "table=releases" / "part-00000.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist(credits, schema=SCHEMAS["credits"]),
        dataset_root / "table=credits" / "part-00000.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist([], schema=SCHEMAS["tracks"]),
        dataset_root / "table=tracks" / "part-00000.parquet",
    )
    (dataset_root / "manifest.json").write_text(
        json.dumps({"snapshot_date": snapshot_date, "counts": {}})
    )
    return dataset_root


def _write_masters_dataset(root: Path, *, snapshot_date: str = SNAPSHOT_DATE) -> Path:
    masters_root = root / f"masters-snapshot={snapshot_date}"
    (masters_root / "table=masters").mkdir(parents=True)
    (masters_root / "table=master_artists").mkdir(parents=True)
    master_rows = [
        {
            "snapshot_date": snapshot_date,
            "master_id": 901,
            "main_release_id": 1,
            "title": "First Light",
            "year": 1995,
            "genres": [],
            "styles": [],
            "data_quality": None,
            "source_url": "https://example.invalid/master/901",
        }
    ]
    pq.write_table(
        pa.Table.from_pylist(master_rows, schema=MASTER_SCHEMAS["masters"]),
        masters_root / "table=masters" / "part-00000.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist([], schema=MASTER_SCHEMAS["master_artists"]),
        masters_root / "table=master_artists" / "part-00000.parquet",
    )
    (masters_root / "manifest.json").write_text(
        json.dumps({"snapshot_date": snapshot_date, "counts": {"masters": 1}})
    )
    return masters_root


def _write_release_format_policy(path: Path, *, snapshot_date: str = SNAPSHOT_DATE) -> Path:
    path.write_text(
        json.dumps(
            {
                "kind": "release-format-scoring-index",
                "policy_name": "studio-album-v1",
                "policy_version": 1,
                "schema_version": 1,
                "snapshot_date": snapshot_date,
                "allowed_release_ids": [1, 2],
                "allowed_release_count": 2,
                "source_policy_sha256": "deadbeef",
            }
        )
    )
    return path


def _write_exclusions(path: Path, *, snapshot_date: str = SNAPSHOT_DATE) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "policy": "studio-album-v1",
                "snapshot_date": snapshot_date,
                "note": "test fixture",
                "exclusions": [],
            }
        )
    )
    return path


def _write_editorial_and_candidates(tmp_path: Path) -> tuple[Path, Path]:
    editorial_path = tmp_path / "editorial.json"
    editorial_path.write_text(json.dumps({"albums": [{"artist": "Alice", "title": "First Light"}]}))
    candidates_path = tmp_path / "candidates.json"
    candidates_path.write_text(
        json.dumps(
            [
                {
                    "master_id": None,
                    "main_release_id": 2,
                    "artist_id": 300,
                    "artist_name": "Cara",
                    "sample_title": "Third Wave",
                    "year": 1996,
                    "score": 1,
                    "variant_count": 1,
                    "credit_rows": 2,
                }
            ]
        )
    )
    return editorial_path, candidates_path


def _base_args(tmp_path: Path, *, onehop_root: Path, output: Path) -> list[str]:
    editorial_path, candidates_path = _write_editorial_and_candidates(tmp_path)
    return [
        "build-public-album-catalog",
        "--onehop-root",
        str(onehop_root),
        "--editorial-albums",
        str(editorial_path),
        "--candidates",
        str(candidates_path),
        "--target-count",
        "2",
        "--output",
        str(output),
    ]


def test_succeeds_with_every_required_input_present(tmp_path: Path, capsys) -> None:
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    masters_root = _write_masters_dataset(tmp_path / "masters")
    policy_path = _write_release_format_policy(tmp_path / "policy.json")
    exclusions_path = _write_exclusions(tmp_path / "exclusions.json")
    output_path = tmp_path / "albums.v1.json"

    args = _base_args(tmp_path, onehop_root=onehop_root, output=output_path)
    args += [
        "--release-format-policy",
        str(policy_path),
        "--masters-root",
        str(masters_root),
        "--studio-album-exclusions",
        str(exclusions_path),
    ]
    assert main(args) == 0
    catalog = json.loads(output_path.read_text())
    assert catalog["catalog_version"]
    assert len(catalog["albums"]) == 2


def test_refuses_without_release_format_policy(tmp_path: Path) -> None:
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    masters_root = _write_masters_dataset(tmp_path / "masters")
    exclusions_path = _write_exclusions(tmp_path / "exclusions.json")
    output_path = tmp_path / "albums.v1.json"

    args = _base_args(tmp_path, onehop_root=onehop_root, output=output_path)
    args += [
        "--release-format-policy",
        str(tmp_path / "missing-policy.json"),
        "--masters-root",
        str(masters_root),
        "--studio-album-exclusions",
        str(exclusions_path),
    ]
    with pytest.raises(ValueError, match="release-format-policy"):
        main(args)
    assert not output_path.exists()


def test_refuses_with_malformed_empty_release_format_policy(tmp_path: Path) -> None:
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    masters_root = _write_masters_dataset(tmp_path / "masters")
    exclusions_path = _write_exclusions(tmp_path / "exclusions.json")
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps({"kind": "release-format-scoring-index"}))
    output_path = tmp_path / "albums.v1.json"

    args = _base_args(tmp_path, onehop_root=onehop_root, output=output_path)
    args += [
        "--release-format-policy",
        str(policy_path),
        "--masters-root",
        str(masters_root),
        "--studio-album-exclusions",
        str(exclusions_path),
    ]
    with pytest.raises(ValueError, match="allowed_release_ids"):
        main(args)
    assert not output_path.exists()


def test_refuses_without_masters_root(tmp_path: Path) -> None:
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    policy_path = _write_release_format_policy(tmp_path / "policy.json")
    exclusions_path = _write_exclusions(tmp_path / "exclusions.json")
    output_path = tmp_path / "albums.v1.json"

    args = _base_args(tmp_path, onehop_root=onehop_root, output=output_path)
    args += [
        "--release-format-policy",
        str(policy_path),
        "--masters-root",
        str(tmp_path / "missing-masters"),
        "--studio-album-exclusions",
        str(exclusions_path),
    ]
    with pytest.raises(ValueError, match="masters-root"):
        main(args)
    assert not output_path.exists()


def test_refuses_without_studio_album_exclusions(tmp_path: Path) -> None:
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    masters_root = _write_masters_dataset(tmp_path / "masters")
    policy_path = _write_release_format_policy(tmp_path / "policy.json")
    output_path = tmp_path / "albums.v1.json"

    args = _base_args(tmp_path, onehop_root=onehop_root, output=output_path)
    args += [
        "--release-format-policy",
        str(policy_path),
        "--masters-root",
        str(masters_root),
        "--studio-album-exclusions",
        str(tmp_path / "missing-exclusions.json"),
    ]
    with pytest.raises(ValueError, match="studio-album-exclusions"):
        main(args)
    assert not output_path.exists()


def test_refuses_mismatched_snapshot_on_release_format_policy(tmp_path: Path) -> None:
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    masters_root = _write_masters_dataset(tmp_path / "masters")
    exclusions_path = _write_exclusions(tmp_path / "exclusions.json")
    policy_path = _write_release_format_policy(tmp_path / "policy.json", snapshot_date="20250101")
    output_path = tmp_path / "albums.v1.json"

    args = _base_args(tmp_path, onehop_root=onehop_root, output=output_path)
    args += [
        "--release-format-policy",
        str(policy_path),
        "--masters-root",
        str(masters_root),
        "--studio-album-exclusions",
        str(exclusions_path),
    ]
    with pytest.raises(ValueError, match="mismatched-snapshot"):
        main(args)
    assert not output_path.exists()


def test_refuses_mismatched_snapshot_on_masters(tmp_path: Path) -> None:
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    masters_root = _write_masters_dataset(tmp_path / "masters", snapshot_date="20250101")
    policy_path = _write_release_format_policy(tmp_path / "policy.json")
    exclusions_path = _write_exclusions(tmp_path / "exclusions.json")
    output_path = tmp_path / "albums.v1.json"

    args = _base_args(tmp_path, onehop_root=onehop_root, output=output_path)
    args += [
        "--release-format-policy",
        str(policy_path),
        "--masters-root",
        str(masters_root),
        "--studio-album-exclusions",
        str(exclusions_path),
    ]
    with pytest.raises(ValueError, match="mismatched-snapshot"):
        main(args)
    assert not output_path.exists()


def test_refuses_mismatched_snapshot_on_exclusions(tmp_path: Path) -> None:
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    masters_root = _write_masters_dataset(tmp_path / "masters")
    policy_path = _write_release_format_policy(tmp_path / "policy.json")
    exclusions_path = _write_exclusions(tmp_path / "exclusions.json", snapshot_date="20250101")
    output_path = tmp_path / "albums.v1.json"

    args = _base_args(tmp_path, onehop_root=onehop_root, output=output_path)
    args += [
        "--release-format-policy",
        str(policy_path),
        "--masters-root",
        str(masters_root),
        "--studio-album-exclusions",
        str(exclusions_path),
    ]
    with pytest.raises(ValueError, match="mismatched-snapshot"):
        main(args)
    assert not output_path.exists()


def test_argparse_requires_every_policy_flag(tmp_path: Path) -> None:
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    output_path = tmp_path / "albums.v1.json"
    args = _base_args(tmp_path, onehop_root=onehop_root, output=output_path)
    # No --release-format-policy/--masters-root/--studio-album-exclusions at
    # all -- argparse itself must refuse (required=True), not just a
    # downstream check.
    with pytest.raises(SystemExit):
        main(args)
