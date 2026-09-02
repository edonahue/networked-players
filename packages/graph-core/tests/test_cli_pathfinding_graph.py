from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from networked_players_catalog.cli import main

_SNAPSHOT = "20260601"
_CATALOG_VERSION = "catalog-v1-20260601-abc123abc123"


def _credit(
    release_id: int,
    artist_id: int,
    name: str,
    *,
    credit_scope: str = "release_artist",
    track_index: int | None = None,
    role_text: str | None = None,
) -> dict[str, Any]:
    return {
        "release_id": release_id,
        "track_index": track_index,
        "track_path": str(track_index) if track_index is not None else None,
        "track_position": "1" if track_index is not None else None,
        "track_title": "Take" if track_index is not None else None,
        "credit_scope": credit_scope,
        "artist_id": artist_id,
        "name": name,
        "anv": None,
        "join_text": None,
        "role_text": role_text,
        "credited_tracks_text": None,
        "is_linked": True,
        "playable_identity": True,
    }


def _release(release_id: int, title: str) -> dict[str, Any]:
    return {
        "release_id": release_id,
        "status": "Accepted",
        "title": title,
        "country": None,
        "released": None,
        "master_id": release_id,
        "master_is_main_release": True,
        "data_quality": None,
        "source_url": f"https://example.invalid/release/{release_id}",
    }


@pytest.fixture
def onehop_dataset(tmp_path: Path) -> Path:
    from conftest import write_synthetic_dataset

    releases = [_release(1, "R1")]
    credits = [
        _credit(1, 100, "Alice", credit_scope="release_artist"),
        _credit(1, 100, "Alice", credit_scope="track_artist", track_index=0, role_text="Guitar"),
        _credit(1, 200, "Bob", credit_scope="release_artist"),
        _credit(1, 200, "Bob", credit_scope="track_artist", track_index=0, role_text="Bass"),
    ]
    return write_synthetic_dataset(
        tmp_path / f"snapshot={_SNAPSHOT}", release_rows=releases, credit_rows=credits
    )


@pytest.fixture
def catalog_path(tmp_path: Path) -> Path:
    path = tmp_path / "catalog.json"
    path.write_text(
        json.dumps(
            {
                "catalog_version": _CATALOG_VERSION,
                "snapshot_date": _SNAPSHOT,
                "albums": [
                    {
                        "id": "master-1",
                        "title": "First Light",
                        "artist_id": 100,
                        "main_release_id": 1,
                        "year": 1995,
                    }
                ],
            }
        )
    )
    return path


@pytest.fixture
def album_credit_membership_path(tmp_path: Path) -> Path:
    path = tmp_path / "credit-membership.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "catalog_version": _CATALOG_VERSION,
                "album_credit_membership_version": "album-credit-membership-v1-test",
                "generated_at": "2026-08-08T00:00:00+00:00",
                "source": "test",
                "license": "test",
                "albums": [
                    {
                        "album_id": "master-1",
                        "main_release_id": 1,
                        "credits": [
                            {
                                "artist_id": 100,
                                "name": "Alice",
                                "anv": None,
                                "role_text": "Guitar",
                                "credit_scope": "release_artist",
                                "track_position": None,
                                "track_title": None,
                            }
                        ],
                    }
                ],
            }
        )
    )
    return path


def test_build_pathfinding_graph_cli_wiring(
    onehop_dataset: Path,
    catalog_path: Path,
    album_credit_membership_path: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "graph.v3.json"
    exit_code = main(
        [
            "build-pathfinding-graph",
            "--onehop-root",
            str(onehop_dataset),
            "--catalog",
            str(catalog_path),
            "--album-credit-membership",
            str(album_credit_membership_path),
            "--output",
            str(output_path),
            "--generated-at",
            "2026-08-03T00:00:00+00:00",
        ]
    )
    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["nodes"] == 3  # Alice (100), Bob (200), master-1's virtual anchor
    assert summary["catalog_version"] == _CATALOG_VERSION
    assert summary["album_virtual_nodes"] == 1

    written = json.loads(output_path.read_text())
    assert set(n for n in written["node_ids"] if n > 0) == {100, 200}
    assert written["schema_version"] == 3
    assert written["graph_policy_version"] == 1


def test_validate_pathfinding_graph_cli_wiring(
    onehop_dataset: Path,
    catalog_path: Path,
    album_credit_membership_path: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "graph.v3.json"
    main(
        [
            "build-pathfinding-graph",
            "--onehop-root",
            str(onehop_dataset),
            "--catalog",
            str(catalog_path),
            "--album-credit-membership",
            str(album_credit_membership_path),
            "--output",
            str(output_path),
            "--generated-at",
            "2026-08-03T00:00:00+00:00",
        ]
    )
    capsys.readouterr()

    exit_code = main(
        [
            "validate-pathfinding-graph",
            "--graph",
            str(output_path),
            "--catalog",
            str(catalog_path),
        ]
    )
    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    assert result == {"ok": True, "nodes": 3}
