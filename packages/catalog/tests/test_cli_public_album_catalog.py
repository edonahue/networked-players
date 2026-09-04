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


# --- Corrective slice 5.1: fully fail-closed on unknown/malformed metadata --
# (not just mismatched metadata -- missing snapshot fields and wrong-artifact
# identity must be refused exactly like a mismatched snapshot).


def test_refuses_onehop_manifest_missing_snapshot(tmp_path: Path) -> None:
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    (onehop_root / "manifest.json").write_text(json.dumps({"counts": {}}))
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
    with pytest.raises(ValueError, match="onehop-root manifest"):
        main(args)
    assert not output_path.exists()


def test_refuses_masters_root_missing_manifest_file(tmp_path: Path) -> None:
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    masters_root = _write_masters_dataset(tmp_path / "masters")
    (masters_root / "manifest.json").unlink()
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
    with pytest.raises(ValueError, match="masters-root manifest"):
        main(args)
    assert not output_path.exists()


def test_refuses_masters_manifest_missing_snapshot(tmp_path: Path) -> None:
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    masters_root = _write_masters_dataset(tmp_path / "masters")
    (masters_root / "manifest.json").write_text(json.dumps({"counts": {"masters": 1}}))
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
    with pytest.raises(ValueError, match="masters-root manifest"):
        main(args)
    assert not output_path.exists()


def test_refuses_release_format_policy_missing_snapshot(tmp_path: Path) -> None:
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    masters_root = _write_masters_dataset(tmp_path / "masters")
    exclusions_path = _write_exclusions(tmp_path / "exclusions.json")
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "kind": "release-format-scoring-index",
                "policy_name": "studio-album-v1",
                "policy_version": 1,
                "schema_version": 1,
                "allowed_release_ids": [1, 2],
                "allowed_release_count": 2,
                "source_policy_sha256": "deadbeef",
            }
        )
    )
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
    with pytest.raises(ValueError, match="release-format-policy"):
        main(args)
    assert not output_path.exists()


def test_refuses_exclusions_missing_snapshot(tmp_path: Path) -> None:
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    masters_root = _write_masters_dataset(tmp_path / "masters")
    policy_path = _write_release_format_policy(tmp_path / "policy.json")
    exclusions_path = tmp_path / "exclusions.json"
    exclusions_path.write_text(
        json.dumps(
            {"schema_version": 1, "policy": "studio-album-v1", "note": "test", "exclusions": []}
        )
    )
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
    with pytest.raises(ValueError, match="studio-album-exclusions"):
        main(args)
    assert not output_path.exists()


def test_refuses_release_format_policy_wrong_kind(tmp_path: Path) -> None:
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    masters_root = _write_masters_dataset(tmp_path / "masters")
    exclusions_path = _write_exclusions(tmp_path / "exclusions.json")
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "kind": "some-other-artifact",
                "policy_name": "studio-album-v1",
                "policy_version": 1,
                "schema_version": 1,
                "snapshot_date": SNAPSHOT_DATE,
                "allowed_release_ids": [1, 2],
                "allowed_release_count": 2,
                "source_policy_sha256": "deadbeef",
            }
        )
    )
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
    with pytest.raises(ValueError, match="kind"):
        main(args)
    assert not output_path.exists()


def test_refuses_exclusions_wrong_policy_identity(tmp_path: Path) -> None:
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    masters_root = _write_masters_dataset(tmp_path / "masters")
    policy_path = _write_release_format_policy(tmp_path / "policy.json")
    exclusions_path = tmp_path / "exclusions.json"
    exclusions_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "policy": "some-other-policy",
                "snapshot_date": SNAPSHOT_DATE,
                "note": "test",
                "exclusions": [],
            }
        )
    )
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
    with pytest.raises(ValueError, match="policy"):
        main(args)
    assert not output_path.exists()


def test_refuses_malformed_exclusions_structure(tmp_path: Path) -> None:
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    masters_root = _write_masters_dataset(tmp_path / "masters")
    policy_path = _write_release_format_policy(tmp_path / "policy.json")
    exclusions_path = tmp_path / "exclusions.json"
    exclusions_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "policy": "studio-album-v1",
                "snapshot_date": SNAPSHOT_DATE,
                "note": "test",
                "exclusions": [{"title": "No master_id here"}],
            }
        )
    )
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
    with pytest.raises(ValueError, match="malformed"):
        main(args)
    assert not output_path.exists()


def test_refuses_exclusions_field_not_an_array(tmp_path: Path) -> None:
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    masters_root = _write_masters_dataset(tmp_path / "masters")
    policy_path = _write_release_format_policy(tmp_path / "policy.json")
    exclusions_path = tmp_path / "exclusions.json"
    exclusions_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "policy": "studio-album-v1",
                "snapshot_date": SNAPSHOT_DATE,
                "note": "test",
                "exclusions": "not-an-array",
            }
        )
    )
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
    with pytest.raises(ValueError, match="non-array"):
        main(args)
    assert not output_path.exists()


def test_accepts_a_genuinely_empty_exclusions_array(tmp_path: Path) -> None:
    """An empty exclusions array is valid (no non-studio masters known yet)
    -- only a missing/wrong-typed field is refused, not an empty one."""
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
    assert output_path.exists()


# --- Phase 7: --personal-seed (Bucket A, ADR 0065) --------------------------


def _write_personal_seed(path: Path, *, snapshot_date: str = SNAPSHOT_DATE) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "public-editorial-seed",
                "snapshot_date": snapshot_date,
                "generated_by": "test",
                "generated_at": "2026-08-27T00:00:00+00:00",
                "note": "",
                "albums": [
                    {
                        "query_artist": "Fictoquai",
                        "query_title": "Personal Pick",
                        "master_id": None,
                        "main_release_id": 3,
                        "artist_id": 700,
                        "artist": "Fictoquai",
                        "title": "Personal Pick",
                        "year": 1999,
                    }
                ],
            }
        )
    )
    return path


def test_personal_seed_adds_a_pre_resolved_album(tmp_path: Path) -> None:
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    masters_root = _write_masters_dataset(tmp_path / "masters")
    # Widened allow-list: the personal-seed fixture's main_release_id (3) is
    # a Bucket-A release that need not physically exist in this small onehop
    # fixture at all (pre-resolved entries with master_id=None skip both the
    # graph's master lookup and any existence check) -- only the policy
    # allow-list still has to admit it.
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "kind": "release-format-scoring-index",
                "policy_name": "studio-album-v1",
                "policy_version": 1,
                "schema_version": 1,
                "snapshot_date": SNAPSHOT_DATE,
                "allowed_release_ids": [1, 2, 3],
                "allowed_release_count": 3,
                "source_policy_sha256": "deadbeef",
            }
        )
    )
    exclusions_path = _write_exclusions(tmp_path / "exclusions.json")
    personal_seed_path = _write_personal_seed(tmp_path / "editorial-seed.json")
    output_path = tmp_path / "albums.v1.json"

    args = _base_args(tmp_path, onehop_root=onehop_root, output=output_path)
    args += [
        "--release-format-policy",
        str(policy_path),
        "--masters-root",
        str(masters_root),
        "--studio-album-exclusions",
        str(exclusions_path),
        "--personal-seed",
        str(personal_seed_path),
        "--target-count",
        "3",
    ]
    assert main(args) == 0
    catalog = json.loads(output_path.read_text())
    assert catalog["pre_resolved_count"] == 1
    assert catalog["pre_resolved_missed"] == []
    assert any(a["artist"] == "Fictoquai" for a in catalog["albums"])


def test_personal_seed_omitted_is_backward_compatible(tmp_path: Path) -> None:
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
    assert catalog["pre_resolved_count"] == 0
    assert catalog["pre_resolved_missed"] == []


def test_personal_seed_wrong_kind_refused(tmp_path: Path) -> None:
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    masters_root = _write_masters_dataset(tmp_path / "masters")
    policy_path = _write_release_format_policy(tmp_path / "policy.json")
    exclusions_path = _write_exclusions(tmp_path / "exclusions.json")
    personal_seed_path = tmp_path / "editorial-seed.json"
    personal_seed_path.write_text(json.dumps({"kind": "private-collection-seed", "albums": []}))
    output_path = tmp_path / "albums.v1.json"

    args = _base_args(tmp_path, onehop_root=onehop_root, output=output_path)
    args += [
        "--release-format-policy",
        str(policy_path),
        "--masters-root",
        str(masters_root),
        "--studio-album-exclusions",
        str(exclusions_path),
        "--personal-seed",
        str(personal_seed_path),
    ]
    with pytest.raises(ValueError, match="public-editorial-seed"):
        main(args)
    assert not output_path.exists()


def test_personal_seed_mismatched_snapshot_refused(tmp_path: Path) -> None:
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    masters_root = _write_masters_dataset(tmp_path / "masters")
    policy_path = _write_release_format_policy(tmp_path / "policy.json")
    exclusions_path = _write_exclusions(tmp_path / "exclusions.json")
    personal_seed_path = _write_personal_seed(
        tmp_path / "editorial-seed.json", snapshot_date="20200101"
    )
    output_path = tmp_path / "albums.v1.json"

    args = _base_args(tmp_path, onehop_root=onehop_root, output=output_path)
    args += [
        "--release-format-policy",
        str(policy_path),
        "--masters-root",
        str(masters_root),
        "--studio-album-exclusions",
        str(exclusions_path),
        "--personal-seed",
        str(personal_seed_path),
    ]
    with pytest.raises(ValueError, match="mismatched-snapshot"):
        main(args)
    assert not output_path.exists()


def test_personal_seed_missing_snapshot_refused(tmp_path: Path) -> None:
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    masters_root = _write_masters_dataset(tmp_path / "masters")
    policy_path = _write_release_format_policy(tmp_path / "policy.json")
    exclusions_path = _write_exclusions(tmp_path / "exclusions.json")
    personal_seed_path = tmp_path / "editorial-seed.json"
    personal_seed_path.write_text(json.dumps({"kind": "public-editorial-seed", "albums": []}))
    output_path = tmp_path / "albums.v1.json"

    args = _base_args(tmp_path, onehop_root=onehop_root, output=output_path)
    args += [
        "--release-format-policy",
        str(policy_path),
        "--masters-root",
        str(masters_root),
        "--studio-album-exclusions",
        str(exclusions_path),
        "--personal-seed",
        str(personal_seed_path),
    ]
    with pytest.raises(ValueError, match="personal-seed"):
        main(args)
    assert not output_path.exists()


def test_personal_seed_full_contract_validation_rejects_a_leaked_field(tmp_path: Path) -> None:
    """Real gap found in review: the CLI previously only checked `kind` and
    `snapshot_date`, never the seed's full contract (exact key set, no
    forbidden substrings/phrases). A same-kind, same-snapshot seed carrying
    an out-of-contract field must still be refused outright, not silently
    accepted and left to `pre_resolved_missed`'s own field whitelist as the
    only defense."""
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    masters_root = _write_masters_dataset(tmp_path / "masters")
    policy_path = _write_release_format_policy(tmp_path / "policy.json")
    exclusions_path = _write_exclusions(tmp_path / "exclusions.json")
    personal_seed_path = tmp_path / "editorial-seed.json"
    personal_seed_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "public-editorial-seed",
                "snapshot_date": SNAPSHOT_DATE,
                "generated_by": "test",
                "generated_at": "2026-08-27T00:00:00+00:00",
                "note": "",
                "albums": [
                    {
                        "query_artist": "Fictoquai",
                        "query_title": "Personal Pick",
                        "master_id": None,
                        "main_release_id": 3,
                        "artist_id": 700,
                        "artist": "Fictoquai",
                        "title": "Personal Pick",
                        "year": 1999,
                        "eligibility": {"curated_exclusion": False},  # not a documented field
                    }
                ],
            }
        )
    )
    output_path = tmp_path / "albums.v1.json"

    args = _base_args(tmp_path, onehop_root=onehop_root, output=output_path)
    args += [
        "--release-format-policy",
        str(policy_path),
        "--masters-root",
        str(masters_root),
        "--studio-album-exclusions",
        str(exclusions_path),
        "--personal-seed",
        str(personal_seed_path),
    ]
    with pytest.raises(ValueError, match="failed contract validation"):
        main(args)
    assert not output_path.exists()


# --- Phase 7: --graph-rich-selection / --coverage-gap-candidates (Buckets B/C) ----


def _widened_policy(path: Path, *, snapshot_date: str = SNAPSHOT_DATE) -> Path:
    path.write_text(
        json.dumps(
            {
                "kind": "release-format-scoring-index",
                "policy_name": "studio-album-v1",
                "policy_version": 1,
                "schema_version": 1,
                "snapshot_date": snapshot_date,
                "allowed_release_ids": [1, 2, 9501, 9601],
                "allowed_release_count": 4,
                "source_policy_sha256": "deadbeef",
            }
        )
    )
    return path


def _write_graph_rich_selection(path: Path, *, snapshot_date: str = SNAPSHOT_DATE) -> Path:
    path.write_text(
        json.dumps(
            {
                "baseline_artist_count": 2,
                "baseline_release_count": 2,
                "finalist_count": 1,
                "requested_count": 1,
                "selected_count": 1,
                "snapshot_date": snapshot_date,
                "selected": [
                    {
                        "master_id": None,
                        "main_release_id": 9501,
                        "artist_id": 750,
                        "artist_name": "Graph Rich Artist",
                        "sample_title": "Graph Rich Pick",
                        "year": 2001,
                        "score": 12345,
                        "marginal_new_edges": 6,
                        "marginal_new_contributors": 3,
                        "variant_count": 4,
                        "credit_rows": 10,
                    }
                ],
            }
        )
    )
    return path


def _write_coverage_gap_candidates(path: Path, *, snapshot_date: str = SNAPSHOT_DATE) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "coverage-gap-selection",
                "snapshot_date": snapshot_date,
                "measured_against": "test",
                "candidates": [
                    {
                        "master_id": None,
                        "main_release_id": 9601,
                        "artist_id": 760,
                        "artist_name": "Coverage Gap Artist",
                        "sample_title": "Coverage Gap Pick",
                        "year": 2002,
                        "score": 6789,
                        "gap_dimension": "genres",
                        "gap_bucket": "Reggae",
                        "gap_rationale": "test rationale",
                    }
                ],
            }
        )
    )
    return path


def test_graph_rich_selection_adds_a_pre_resolved_album_labeled_graph_rich(tmp_path: Path) -> None:
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    masters_root = _write_masters_dataset(tmp_path / "masters")
    policy_path = _widened_policy(tmp_path / "policy.json")
    exclusions_path = _write_exclusions(tmp_path / "exclusions.json")
    graph_rich_path = _write_graph_rich_selection(tmp_path / "graph-rich.json")
    output_path = tmp_path / "albums.v1.json"

    args = _base_args(tmp_path, onehop_root=onehop_root, output=output_path)
    args += [
        "--release-format-policy",
        str(policy_path),
        "--masters-root",
        str(masters_root),
        "--studio-album-exclusions",
        str(exclusions_path),
        "--graph-rich-selection",
        str(graph_rich_path),
        "--target-count",
        "3",
    ]
    assert main(args) == 0
    catalog = json.loads(output_path.read_text())
    assert catalog["pre_resolved_count"] == 1
    assert catalog["pre_resolved_buckets"] == [{"label": "graph_rich", "count": 1}]
    added = next(a for a in catalog["albums"] if a["artist"] == "Graph Rich Artist")
    assert added["title"] == "Graph Rich Pick"
    # Bucket-B-specific fields must never leak into the committed catalog.
    assert "score" not in added
    assert "marginal_new_edges" not in added


def test_coverage_gap_candidates_adds_a_pre_resolved_album_labeled_coverage_gap(
    tmp_path: Path,
) -> None:
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    masters_root = _write_masters_dataset(tmp_path / "masters")
    policy_path = _widened_policy(tmp_path / "policy.json")
    exclusions_path = _write_exclusions(tmp_path / "exclusions.json")
    coverage_gap_path = _write_coverage_gap_candidates(tmp_path / "coverage-gap.json")
    output_path = tmp_path / "albums.v1.json"

    args = _base_args(tmp_path, onehop_root=onehop_root, output=output_path)
    args += [
        "--release-format-policy",
        str(policy_path),
        "--masters-root",
        str(masters_root),
        "--studio-album-exclusions",
        str(exclusions_path),
        "--coverage-gap-candidates",
        str(coverage_gap_path),
        "--target-count",
        "3",
    ]
    assert main(args) == 0
    catalog = json.loads(output_path.read_text())
    assert catalog["pre_resolved_count"] == 1
    assert catalog["pre_resolved_buckets"] == [{"label": "coverage_gap", "count": 1}]
    added = next(a for a in catalog["albums"] if a["artist"] == "Coverage Gap Artist")
    assert added["title"] == "Coverage Gap Pick"
    assert "gap_rationale" not in added
    assert "gap_dimension" not in added


def test_graph_rich_selection_and_coverage_gap_candidates_combine_with_personal_seed(
    tmp_path: Path,
) -> None:
    """All three Phase 7 pre-resolved lanes together, in order, each
    labeled and counted separately -- the real shape the eventual 179-album
    catalog build uses."""
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    masters_root = _write_masters_dataset(tmp_path / "masters")
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "kind": "release-format-scoring-index",
                "policy_name": "studio-album-v1",
                "policy_version": 1,
                "schema_version": 1,
                "snapshot_date": SNAPSHOT_DATE,
                "allowed_release_ids": [1, 2, 3, 9501, 9601],
                "allowed_release_count": 5,
                "source_policy_sha256": "deadbeef",
            }
        )
    )
    exclusions_path = _write_exclusions(tmp_path / "exclusions.json")
    personal_seed_path = _write_personal_seed(tmp_path / "editorial-seed.json")
    graph_rich_path = _write_graph_rich_selection(tmp_path / "graph-rich.json")
    coverage_gap_path = _write_coverage_gap_candidates(tmp_path / "coverage-gap.json")
    output_path = tmp_path / "albums.v1.json"

    args = _base_args(tmp_path, onehop_root=onehop_root, output=output_path)
    args += [
        "--release-format-policy",
        str(policy_path),
        "--masters-root",
        str(masters_root),
        "--studio-album-exclusions",
        str(exclusions_path),
        "--personal-seed",
        str(personal_seed_path),
        "--graph-rich-selection",
        str(graph_rich_path),
        "--coverage-gap-candidates",
        str(coverage_gap_path),
        "--target-count",
        "5",
    ]
    assert main(args) == 0
    catalog = json.loads(output_path.read_text())
    assert catalog["pre_resolved_count"] == 3
    assert catalog["pre_resolved_buckets"] == [
        {"label": "personal_editorial", "count": 1},
        {"label": "graph_rich", "count": 1},
        {"label": "coverage_gap", "count": 1},
    ]


def test_graph_rich_selection_mismatched_snapshot_refused(tmp_path: Path) -> None:
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    masters_root = _write_masters_dataset(tmp_path / "masters")
    policy_path = _write_release_format_policy(tmp_path / "policy.json")
    exclusions_path = _write_exclusions(tmp_path / "exclusions.json")
    graph_rich_path = _write_graph_rich_selection(
        tmp_path / "graph-rich.json", snapshot_date="20200101"
    )
    output_path = tmp_path / "albums.v1.json"

    args = _base_args(tmp_path, onehop_root=onehop_root, output=output_path)
    args += [
        "--release-format-policy",
        str(policy_path),
        "--masters-root",
        str(masters_root),
        "--studio-album-exclusions",
        str(exclusions_path),
        "--graph-rich-selection",
        str(graph_rich_path),
    ]
    with pytest.raises(ValueError, match="mismatched-snapshot"):
        main(args)
    assert not output_path.exists()


def test_coverage_gap_candidates_mismatched_snapshot_refused(tmp_path: Path) -> None:
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    masters_root = _write_masters_dataset(tmp_path / "masters")
    policy_path = _write_release_format_policy(tmp_path / "policy.json")
    exclusions_path = _write_exclusions(tmp_path / "exclusions.json")
    coverage_gap_path = _write_coverage_gap_candidates(
        tmp_path / "coverage-gap.json", snapshot_date="20200101"
    )
    output_path = tmp_path / "albums.v1.json"

    args = _base_args(tmp_path, onehop_root=onehop_root, output=output_path)
    args += [
        "--release-format-policy",
        str(policy_path),
        "--masters-root",
        str(masters_root),
        "--studio-album-exclusions",
        str(exclusions_path),
        "--coverage-gap-candidates",
        str(coverage_gap_path),
    ]
    with pytest.raises(ValueError, match="mismatched-snapshot"):
        main(args)
    assert not output_path.exists()


def test_graph_rich_selection_missing_selected_array_refused(tmp_path: Path) -> None:
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    masters_root = _write_masters_dataset(tmp_path / "masters")
    policy_path = _write_release_format_policy(tmp_path / "policy.json")
    exclusions_path = _write_exclusions(tmp_path / "exclusions.json")
    graph_rich_path = tmp_path / "graph-rich.json"
    graph_rich_path.write_text(json.dumps({"snapshot_date": SNAPSHOT_DATE}))
    output_path = tmp_path / "albums.v1.json"

    args = _base_args(tmp_path, onehop_root=onehop_root, output=output_path)
    args += [
        "--release-format-policy",
        str(policy_path),
        "--masters-root",
        str(masters_root),
        "--studio-album-exclusions",
        str(exclusions_path),
        "--graph-rich-selection",
        str(graph_rich_path),
    ]
    with pytest.raises(ValueError, match="'selected' array"):
        main(args)
    assert not output_path.exists()


def test_coverage_gap_candidates_missing_candidates_array_refused(tmp_path: Path) -> None:
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    masters_root = _write_masters_dataset(tmp_path / "masters")
    policy_path = _write_release_format_policy(tmp_path / "policy.json")
    exclusions_path = _write_exclusions(tmp_path / "exclusions.json")
    coverage_gap_path = tmp_path / "coverage-gap.json"
    coverage_gap_path.write_text(json.dumps({"snapshot_date": SNAPSHOT_DATE}))
    output_path = tmp_path / "albums.v1.json"

    args = _base_args(tmp_path, onehop_root=onehop_root, output=output_path)
    args += [
        "--release-format-policy",
        str(policy_path),
        "--masters-root",
        str(masters_root),
        "--studio-album-exclusions",
        str(exclusions_path),
        "--coverage-gap-candidates",
        str(coverage_gap_path),
    ]
    with pytest.raises(ValueError, match="'candidates' array"):
        main(args)
    assert not output_path.exists()


def test_graph_rich_selection_missing_artist_field_refused(tmp_path: Path) -> None:
    """Real Codex finding: a same-snapshot, valid-ID entry that omits both
    `artist` and `artist_name` must fail closed here, not become the
    literal string "None" in the committed public catalog."""
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    masters_root = _write_masters_dataset(tmp_path / "masters")
    policy_path = _widened_policy(tmp_path / "policy.json")
    exclusions_path = _write_exclusions(tmp_path / "exclusions.json")
    graph_rich_path = tmp_path / "graph-rich.json"
    graph_rich_path.write_text(
        json.dumps(
            {
                "snapshot_date": SNAPSHOT_DATE,
                "selected": [
                    {
                        "master_id": None,
                        "main_release_id": 9501,
                        "artist_id": 750,
                        "sample_title": "Graph Rich Pick",
                        "year": 2001,
                    }
                ],
            }
        )
    )
    output_path = tmp_path / "albums.v1.json"

    args = _base_args(tmp_path, onehop_root=onehop_root, output=output_path)
    args += [
        "--release-format-policy",
        str(policy_path),
        "--masters-root",
        str(masters_root),
        "--studio-album-exclusions",
        str(exclusions_path),
        "--graph-rich-selection",
        str(graph_rich_path),
    ]
    with pytest.raises(ValueError, match="'artist'/'artist_name'"):
        main(args)
    assert not output_path.exists()


def test_coverage_gap_candidates_missing_title_field_refused(tmp_path: Path) -> None:
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    masters_root = _write_masters_dataset(tmp_path / "masters")
    policy_path = _widened_policy(tmp_path / "policy.json")
    exclusions_path = _write_exclusions(tmp_path / "exclusions.json")
    coverage_gap_path = tmp_path / "coverage-gap.json"
    coverage_gap_path.write_text(
        json.dumps(
            {
                "snapshot_date": SNAPSHOT_DATE,
                "candidates": [
                    {
                        "master_id": None,
                        "main_release_id": 9601,
                        "artist_id": 760,
                        "artist_name": "Coverage Gap Artist",
                        "year": 2002,
                    }
                ],
            }
        )
    )
    output_path = tmp_path / "albums.v1.json"

    args = _base_args(tmp_path, onehop_root=onehop_root, output=output_path)
    args += [
        "--release-format-policy",
        str(policy_path),
        "--masters-root",
        str(masters_root),
        "--studio-album-exclusions",
        str(exclusions_path),
        "--coverage-gap-candidates",
        str(coverage_gap_path),
    ]
    with pytest.raises(ValueError, match="'title'/'sample_title'"):
        main(args)
    assert not output_path.exists()


# --- Phase 7: --already-published-catalog (preserving a prior build's albums) ----


def _write_already_published_catalog(path: Path) -> Path:
    """A prior build's own committed-catalog shape: real per-album fields
    (id/artist_id/artist/master_id/main_release_id/title/year), no
    snapshot_date requirement -- this lane preserves content resolved from
    a PAST snapshot generation, on purpose."""
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "catalog_version": "catalog-v1-20200101-priorbuild",
                "snapshot_date": "20200101",
                "generated_by": "test",
                "albums": [
                    {
                        "id": "master-901",
                        "artist_id": 100,
                        "artist": "Alice",
                        "master_id": 901,
                        "main_release_id": 1,
                        "title": "First Light",
                        "year": 1995,
                    }
                ],
            }
        )
    )
    return path


def test_already_published_catalog_preserves_existing_albums_labeled_already_published(
    tmp_path: Path,
) -> None:
    """Real bug found while doing the actual Phase 7 catalog expansion: a
    naive rebuild against a widened one-hop corpus does NOT reproduce the
    same editorial match set or the same score-ranked candidate fill, and
    silently drops/replaces already-published albums. --already-published-
    catalog is the fix -- its entries are preserved verbatim, never
    re-derived."""
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    masters_root = _write_masters_dataset(tmp_path / "masters")
    policy_path = _write_release_format_policy(tmp_path / "policy.json")  # allows [1, 2]
    exclusions_path = _write_exclusions(tmp_path / "exclusions.json")
    already_published_path = _write_already_published_catalog(tmp_path / "prior-catalog.json")
    output_path = tmp_path / "albums.v1.json"

    # No --editorial-albums/--candidates contribution needed to prove
    # preservation -- pass empty editorial and no candidates at all.
    empty_editorial_path = tmp_path / "empty-editorial.json"
    empty_editorial_path.write_text(json.dumps({"albums": []}))
    empty_candidates_path = tmp_path / "empty-candidates.json"
    empty_candidates_path.write_text(json.dumps([]))

    args = [
        "build-public-album-catalog",
        "--onehop-root",
        str(onehop_root),
        "--editorial-albums",
        str(empty_editorial_path),
        "--already-published-catalog",
        str(already_published_path),
        "--candidates",
        str(empty_candidates_path),
        "--target-count",
        "1",
        "--output",
        str(output_path),
        "--release-format-policy",
        str(policy_path),
        "--masters-root",
        str(masters_root),
        "--studio-album-exclusions",
        str(exclusions_path),
    ]
    assert main(args) == 0
    catalog = json.loads(output_path.read_text())
    assert catalog["pre_resolved_count"] == 1
    assert catalog["pre_resolved_buckets"] == [{"label": "already_published", "count": 1}]
    assert len(catalog["albums"]) == 1
    preserved = catalog["albums"][0]
    assert preserved["artist"] == "Alice"
    assert preserved["title"] == "First Light"
    assert preserved["master_id"] == 901


def test_already_published_catalog_blocks_a_duplicate_artist_from_another_lane(
    tmp_path: Path,
) -> None:
    """An already-published artist locks out a later lane's pick for that
    same artist, the same one-album-per-artist rule every additional lane
    enforces against every earlier one."""
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    masters_root = _write_masters_dataset(tmp_path / "masters")
    policy_path = _widened_policy(tmp_path / "policy.json")
    exclusions_path = _write_exclusions(tmp_path / "exclusions.json")
    already_published_path = tmp_path / "prior-catalog.json"
    already_published_path.write_text(
        json.dumps(
            {
                "albums": [
                    {
                        "id": "master-1",
                        "artist_id": 750,
                        "artist": "Graph Rich Artist",
                        "master_id": 1,
                        "main_release_id": 1,
                        "title": "Already Published Album",
                        "year": 1990,
                    }
                ]
            }
        )
    )
    graph_rich_path = _write_graph_rich_selection(tmp_path / "graph-rich.json")
    empty_editorial_path = tmp_path / "empty-editorial.json"
    empty_editorial_path.write_text(json.dumps({"albums": []}))
    empty_candidates_path = tmp_path / "empty-candidates.json"
    empty_candidates_path.write_text(json.dumps([]))
    output_path = tmp_path / "albums.v1.json"

    args = [
        "build-public-album-catalog",
        "--onehop-root",
        str(onehop_root),
        "--editorial-albums",
        str(empty_editorial_path),
        "--already-published-catalog",
        str(already_published_path),
        "--graph-rich-selection",
        str(graph_rich_path),
        "--candidates",
        str(empty_candidates_path),
        "--target-count",
        "2",
        "--output",
        str(output_path),
        "--release-format-policy",
        str(policy_path),
        "--masters-root",
        str(masters_root),
        "--studio-album-exclusions",
        str(exclusions_path),
    ]
    assert main(args) == 0
    catalog = json.loads(output_path.read_text())
    assert catalog["pre_resolved_buckets"] == [
        {"label": "already_published", "count": 1},
        {"label": "graph_rich", "count": 0},
    ]
    assert len(catalog["albums"]) == 1
    assert catalog["albums"][0]["title"] == "Already Published Album"


def test_already_published_catalog_survives_a_personal_seed_entry_for_the_same_artist(
    tmp_path: Path,
) -> None:
    """The exact real bug found in review: a --personal-seed (Bucket A)
    entry deliberately adding a second album by an artist who already has
    a DIFFERENT album in --already-published-catalog must never cause the
    already-published album to be rejected. Modeled directly on the real
    Phase 7 data: the committed editorial seed's "Revolver" (The Beatles)
    alongside the live catalog's "Abbey Road" (The Beatles)."""
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    masters_root = _write_masters_dataset(tmp_path / "masters")
    policy_path = _widened_policy(tmp_path / "policy.json")
    exclusions_path = _write_exclusions(tmp_path / "exclusions.json")
    already_published_path = tmp_path / "prior-catalog.json"
    already_published_path.write_text(
        json.dumps(
            {
                "albums": [
                    {
                        "id": "master-1",
                        "artist_id": 82730,
                        "artist": "The Beatles",
                        "master_id": 1,
                        "main_release_id": 1,
                        "title": "Abbey Road",
                        "year": 1969,
                    }
                ]
            }
        )
    )
    personal_seed_path = tmp_path / "editorial-seed.json"
    personal_seed_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "public-editorial-seed",
                "snapshot_date": SNAPSHOT_DATE,
                "generated_by": "test",
                "generated_at": "2026-08-27T00:00:00+00:00",
                "note": "",
                "albums": [
                    {
                        "query_artist": "The Beatles",
                        "query_title": "Revolver",
                        "master_id": None,
                        "main_release_id": 9501,
                        "artist_id": 82730,
                        "artist": "The Beatles",
                        "title": "Revolver",
                        "year": 1966,
                    }
                ],
            }
        )
    )
    empty_editorial_path = tmp_path / "empty-editorial.json"
    empty_editorial_path.write_text(json.dumps({"albums": []}))
    empty_candidates_path = tmp_path / "empty-candidates.json"
    empty_candidates_path.write_text(json.dumps([]))
    output_path = tmp_path / "albums.v1.json"

    args = [
        "build-public-album-catalog",
        "--onehop-root",
        str(onehop_root),
        "--editorial-albums",
        str(empty_editorial_path),
        "--already-published-catalog",
        str(already_published_path),
        "--personal-seed",
        str(personal_seed_path),
        "--candidates",
        str(empty_candidates_path),
        "--target-count",
        "2",
        "--output",
        str(output_path),
        "--release-format-policy",
        str(policy_path),
        "--masters-root",
        str(masters_root),
        "--studio-album-exclusions",
        str(exclusions_path),
    ]
    assert main(args) == 0
    catalog = json.loads(output_path.read_text())
    assert catalog["pre_resolved_count"] == 2
    assert catalog["pre_resolved_missed"] == []
    titles = {a["title"] for a in catalog["albums"]}
    assert titles == {"Abbey Road", "Revolver"}


def test_already_published_catalog_omitted_is_backward_compatible(tmp_path: Path) -> None:
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
    assert catalog["pre_resolved_count"] == 0
    assert catalog["pre_resolved_buckets"] == []


def test_already_published_catalog_missing_albums_array_refused(tmp_path: Path) -> None:
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    masters_root = _write_masters_dataset(tmp_path / "masters")
    policy_path = _write_release_format_policy(tmp_path / "policy.json")
    exclusions_path = _write_exclusions(tmp_path / "exclusions.json")
    already_published_path = tmp_path / "prior-catalog.json"
    already_published_path.write_text(json.dumps({"not_albums": []}))
    output_path = tmp_path / "albums.v1.json"

    args = _base_args(tmp_path, onehop_root=onehop_root, output=output_path)
    args += [
        "--release-format-policy",
        str(policy_path),
        "--masters-root",
        str(masters_root),
        "--studio-album-exclusions",
        str(exclusions_path),
        "--already-published-catalog",
        str(already_published_path),
    ]
    with pytest.raises(ValueError, match="'albums' array"):
        main(args)
    assert not output_path.exists()


def test_featured_albums_activates_catalog_schema_v2(tmp_path: Path) -> None:
    """--featured-albums (Round 1 prep, plan section 20.4) is purely
    additive: given, the catalog gains catalog_schema_version=2 and every
    album gains featured/selection_source/expansion_round -- pinned "First
    Light" (master_id 901, the editorial entry) is featured; the graph-rich
    candidate ("Third Wave") is not."""
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    masters_root = _write_masters_dataset(tmp_path / "masters")
    policy_path = _write_release_format_policy(tmp_path / "policy.json")
    exclusions_path = _write_exclusions(tmp_path / "exclusions.json")
    featured_path = tmp_path / "featured-v1.json"
    featured_path.write_text(json.dumps({"entries": [{"master_id": 901}]}))
    output_path = tmp_path / "albums.v1.json"

    args = _base_args(tmp_path, onehop_root=onehop_root, output=output_path)
    args += [
        "--release-format-policy",
        str(policy_path),
        "--masters-root",
        str(masters_root),
        "--studio-album-exclusions",
        str(exclusions_path),
        "--featured-albums",
        str(featured_path),
        "--expansion-round",
        "1",
    ]
    assert main(args) == 0
    catalog = json.loads(output_path.read_text())
    assert catalog["catalog_schema_version"] == 2
    by_master = {a["master_id"]: a for a in catalog["albums"]}
    assert by_master[901]["featured"] is True
    assert by_master[901]["expansion_round"] == 1
    assert by_master[901]["selection_source"] == "editorial"


def test_omitting_featured_albums_stays_v1_shaped(tmp_path: Path) -> None:
    """The new flags are opt-in -- a caller that never passes
    --featured-albums must see byte-for-byte the same v1 shape as before
    this change (no catalog_schema_version, no per-album featured/
    selection_source/expansion_round)."""
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
    assert "catalog_schema_version" not in catalog
    for album in catalog["albums"]:
        assert "featured" not in album
        assert "selection_source" not in album
        assert "expansion_round" not in album
