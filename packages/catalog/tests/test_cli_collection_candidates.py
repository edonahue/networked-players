"""CLI round-trip for `build-collection-candidates` (graph-expansion Phase 2,
plan section 4 / section 21.3 slice X1). The derivation itself is unit-tested
with hand-verified expectations in
packages/graph-core/tests/test_collection_candidates.py; this pins the CLI
wiring: seed reading, input loading, the local-only output guards, the
master-id sidecar, and that the sidecar round-trips into
`score-expansion-candidates --private-seed-master-ids`."""

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


def _release(release_id: int, title: str, *, master_id: int | None) -> dict[str, Any]:
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "release_id": release_id,
        "status": "Accepted",
        "title": title,
        "country": None,
        "released": "1995",
        "master_id": master_id,
        "master_is_main_release": master_id is not None,
        "data_quality": None,
        "source_url": f"https://example.invalid/release/{release_id}",
    }


def _credit(release_id: int, *, artist_id: int, name: str) -> dict[str, Any]:
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "release_id": release_id,
        "track_index": None,
        "track_path": None,
        "track_position": None,
        "track_title": None,
        "credit_scope": "release_artist",
        "artist_id": artist_id,
        "name": name,
        "anv": None,
        "join_text": None,
        "role_text": None,
        "credited_tracks_text": None,
        "is_linked": True,
        "playable_identity": True,
    }


def _write_onehop_dataset(root: Path) -> Path:
    dataset_root = root / f"snapshot={SNAPSHOT_DATE}"
    (dataset_root / "table=releases").mkdir(parents=True)
    (dataset_root / "table=credits").mkdir(parents=True)
    (dataset_root / "table=tracks").mkdir(parents=True)
    releases = [
        _release(1, "First Light", master_id=900),
        _release(2, "Second Look", master_id=901),
    ]
    credits = [
        _credit(1, artist_id=100, name="Alice"),
        _credit(2, artist_id=200, name="Bob"),
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
        json.dumps({"snapshot_date": SNAPSHOT_DATE, "counts": {}})
    )
    return dataset_root


def _write_masters_dataset(root: Path) -> Path:
    masters_root = root / f"masters-snapshot={SNAPSHOT_DATE}"
    (masters_root / "table=masters").mkdir(parents=True)
    (masters_root / "table=master_artists").mkdir(parents=True)
    master_rows = [
        {
            "snapshot_date": SNAPSHOT_DATE,
            "master_id": master_id,
            "main_release_id": release_id,
            "title": title,
            "year": 1995,
            "genres": [],
            "styles": [],
            "data_quality": None,
            "source_url": f"https://example.invalid/master/{master_id}",
        }
        for master_id, release_id, title in [(900, 1, "First Light"), (901, 2, "Second Look")]
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
        json.dumps({"snapshot_date": SNAPSHOT_DATE, "counts": {"masters": 2}})
    )
    return masters_root


def _write_release_format_policy(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "kind": "release-format-scoring-index",
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
    return path


def _write_seed(path: Path, release_ids: list[int]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "seed_version": 1,
                "source": "discogs-collection-export-csv",
                "imported_at": "2026-09-04T00:00:00+00:00",
                "release_ids": release_ids,
            }
        )
    )
    return path


def _base_args(tmp_path: Path, output: Path) -> list[str]:
    dataset = _write_onehop_dataset(tmp_path)
    masters_root = _write_masters_dataset(tmp_path)
    policy = _write_release_format_policy(tmp_path / "policy.json")
    seed = _write_seed(tmp_path / "private" / "discogs-seed.json", [1, 2])
    return [
        "build-collection-candidates",
        "--onehop-root",
        str(dataset),
        "--masters-root",
        str(masters_root),
        "--seed",
        str(seed),
        "--release-format-policy",
        str(policy),
        "--output",
        str(output),
        "--quiet",
    ]


def test_derives_candidates_from_the_seed_and_writes_local_only(tmp_path: Path) -> None:
    output = tmp_path / "local" / "analysis" / "expansion" / "round-1" / "collection.json"
    exit_code = main(_base_args(tmp_path, output))
    assert exit_code == 0

    rows = json.loads(output.read_text())
    by_master = {row["master_id"]: row for row in rows}
    assert sorted(by_master) == [900, 901]
    assert by_master[900]["eligibility"] == "eligible"
    assert by_master[900]["artist_id"] == 100
    assert by_master[900]["artist_name"] == "Alice"
    assert by_master[900]["main_release_id"] == 1
    assert by_master[900]["seed_release_count"] == 1


def test_already_published_masters_are_excluded(tmp_path: Path) -> None:
    output = tmp_path / "local" / "collection.json"
    catalog = tmp_path / "albums.v1.json"
    catalog.write_text(json.dumps({"albums": [{"master_id": 901}]}))

    exit_code = main([*_base_args(tmp_path, output), "--already-published-catalog", str(catalog)])
    assert exit_code == 0
    rows = json.loads(output.read_text())
    assert [row["master_id"] for row in rows] == [900]


def test_master_ids_sidecar_feeds_score_expansion_candidates(tmp_path: Path) -> None:
    """The sidecar exists to give `--private-seed-master-ids` the producer it
    never had -- so assert it actually round-trips into that flag and lands as
    a real `in_private_seed` flag, not just that a file was written."""
    output = tmp_path / "local" / "collection.json"
    sidecar = tmp_path / "local" / "collection-master-ids.json"
    exit_code = main([*_base_args(tmp_path, output), "--master-ids-output", str(sidecar)])
    assert exit_code == 0
    assert json.loads(sidecar.read_text()) == {"master_ids": [900, 901]}

    scored = tmp_path / "local" / "scored.json"
    candidates = tmp_path / "candidates.json"
    candidates.write_text(json.dumps([{"master_id": 900}, {"master_id": 901}]))
    graph = tmp_path / "graph.v4.json"
    graph.write_text(json.dumps({"node_ids": [100], "offsets": [0, 0], "neighbors": []}))

    exit_code = main(
        [
            "score-expansion-candidates",
            "--onehop-root",
            str(tmp_path / f"snapshot={SNAPSHOT_DATE}"),
            "--masters-root",
            str(tmp_path / f"masters-snapshot={SNAPSHOT_DATE}"),
            "--candidates",
            str(candidates),
            "--pathfinding-graph",
            str(graph),
            "--release-format-policy",
            str(tmp_path / "policy.json"),
            "--private-seed-master-ids",
            str(sidecar),
            "--output",
            str(scored),
            "--quiet",
        ]
    )
    assert exit_code == 0
    rows = json.loads(scored.read_text())["candidates"]
    assert all(row["in_private_seed"] == 1 for row in rows)


def test_refuses_to_write_outside_local(tmp_path: Path) -> None:
    output = tmp_path / "apps" / "web" / "public" / "data" / "collection.json"
    with pytest.raises(ValueError, match="refuses to write outside local/"):
        main(_base_args(tmp_path, output))
    assert not output.exists()


def test_refuses_a_sidecar_outside_local(tmp_path: Path) -> None:
    """The sidecar carries the same membership data in another shape, so it
    needs the same guard -- a public `--output` with a private sidecar path
    would otherwise leak exactly what the guard exists to stop."""
    output = tmp_path / "local" / "collection.json"
    sidecar = tmp_path / "data" / "albums" / "leaked.json"
    with pytest.raises(ValueError, match="refuses to write outside local/"):
        main([*_base_args(tmp_path, output), "--master-ids-output", str(sidecar)])
    assert not sidecar.exists()
