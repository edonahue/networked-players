"""build-record-routes / validate-record-routes CLI wiring (ADR 0046)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from networked_players_catalog.cli import main
from networked_players_catalog.discogs.parquet import SCHEMAS

SNAPSHOT_DATE = "20260601"


def _release(release_id: int, title: str) -> dict[str, Any]:
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "release_id": release_id,
        "status": "Accepted",
        "title": title,
        "country": None,
        "released": "1995",
        "master_id": None,
        "master_is_main_release": None,
        "data_quality": None,
        "source_url": f"https://example.invalid/release/{release_id}",
    }


def _credit(
    release_id: int,
    *,
    artist_id: int,
    name: str,
    scope: str,
    role_text: str | None,
    track_index: int | None = None,
) -> dict[str, Any]:
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "release_id": release_id,
        "track_index": track_index,
        "track_path": None if track_index is None else str(track_index),
        "track_position": None if track_index is None else str(track_index + 1),
        "track_title": None if track_index is None else f"Track {track_index + 1}",
        "credit_scope": scope,
        "artist_id": artist_id,
        "name": name,
        "anv": None,
        "join_text": None,
        "role_text": role_text,
        "credited_tracks_text": None,
        "is_linked": True,
        "playable_identity": True,
    }


def _co_billed(release_id: int, *, artist_id: int, name: str, role: str) -> list[dict[str, Any]]:
    return [
        _credit(release_id, artist_id=artist_id, name=name, scope="release_artist", role_text=None),
        _credit(
            release_id,
            artist_id=artist_id,
            name=name,
            scope="track_artist",
            role_text=role,
            track_index=0,
        ),
    ]


def _write_onehop_dataset(root: Path) -> Path:
    dataset_root = root / f"snapshot={SNAPSHOT_DATE}"
    (dataset_root / "table=releases").mkdir(parents=True)
    (dataset_root / "table=credits").mkdir(parents=True)
    (dataset_root / "table=tracks").mkdir(parents=True)

    releases = [_release(1, "Alpha's Album"), _release(2, "Bravo's Album")]
    credits = [
        *_co_billed(1, artist_id=100, name="Alice", role="Vocals"),
        *_co_billed(1, artist_id=200, name="Bob", role="Guitar"),
        *_co_billed(2, artist_id=200, name="Bob", role="Bass"),
        *_co_billed(2, artist_id=300, name="Cara", role="Drums"),
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


def _write_catalog(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "catalog_version": "catalog-v1-20260601-test",
                "snapshot_date": SNAPSHOT_DATE,
                "albums": [
                    {
                        "id": "master-1",
                        "master_id": None,
                        "main_release_id": 1,
                        "title": "Alpha's Album",
                        "artist_id": 100,
                        "artist": "Alice",
                        "year": 1995,
                    },
                    {
                        "id": "master-2",
                        "master_id": None,
                        "main_release_id": 2,
                        "title": "Bravo's Album",
                        "artist_id": 200,
                        "artist": "Bob",
                        "year": 1995,
                    },
                ],
            }
        )
    )
    return path


def test_build_and_validate_record_routes_cli_wiring(tmp_path: Path, capsys) -> None:
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    catalog_path = _write_catalog(tmp_path / "catalog.json")
    universe_path = tmp_path / "universe.v1.json"
    rounds_path = tmp_path / "rounds.v1.json"

    exit_code = main(
        [
            "build-record-routes",
            "--onehop-root",
            str(onehop_root),
            "--albums",
            str(catalog_path),
            "--one-hop-target",
            "10",
            "--two-hop-target",
            "10",
            "--max-endpoint-share",
            "1.0",
            "--max-bridge-share",
            "1.0",
            "--output-universe",
            str(universe_path),
            "--output-rounds",
            str(rounds_path),
        ]
    )
    assert exit_code == 0
    diagnostics = json.loads(capsys.readouterr().out)
    assert diagnostics["one_hop_selected"] == 1  # Alice-Bob via release 1

    universe = json.loads(universe_path.read_text())
    rounds = json.loads(rounds_path.read_text())
    assert universe["mode"] == "record_routes"
    assert rounds["mode"] == "record_routes"
    assert rounds["rounds"][0]["id"].startswith("route-")
    assert not rounds["rounds"][0]["id"].startswith("round-")
    for album in universe["albums"]:
        assert "cover_image" not in album

    exit_code = main(
        [
            "validate-record-routes",
            "--universe",
            str(universe_path),
            "--rounds",
            str(rounds_path),
        ]
    )
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True}
