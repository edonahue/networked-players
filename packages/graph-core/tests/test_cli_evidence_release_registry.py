from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from networked_players_catalog.cli import main

_SNAPSHOT = "20260601"
_CATALOG_VERSION = "catalog-v1-20260601-abc123abc123"


def _credit(release_id: int, artist_id: int, name: str) -> dict[str, Any]:
    return {
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


def _release(release_id: int, title: str) -> dict[str, Any]:
    return {
        "release_id": release_id,
        "status": "Accepted",
        "title": title,
        "country": None,
        "released": "1995",
        "master_id": release_id,
        "master_is_main_release": True,
        "data_quality": None,
        "source_url": f"https://example.invalid/release/{release_id}",
    }


@pytest.fixture
def onehop_dataset(tmp_path: Path) -> Path:
    from conftest import write_synthetic_dataset

    releases = [_release(1, "R1"), _release(2, "R2")]
    credits = [_credit(1, 100, "Alice"), _credit(2, 200, "Bob")]
    return write_synthetic_dataset(
        tmp_path / f"snapshot={_SNAPSHOT}", release_rows=releases, credit_rows=credits
    )


@pytest.fixture
def artifact_paths(tmp_path: Path) -> dict[str, Path]:
    catalog = {
        "catalog_version": _CATALOG_VERSION,
        "snapshot_date": _SNAPSHOT,
        "albums": [
            {"id": "master-1", "title": "First Light", "artist_id": 100, "main_release_id": 1}
        ],
    }
    challenge = {
        "releases": [
            {
                "release_id": 1,
                "title": "R1",
                "country": None,
                "released": "1995",
                "master_id": 1,
                "source_url": "https://data.discogs.com/?download=fake",
            }
        ]
    }
    routes_rounds = {"releases": []}
    pathfinding_graph = {"evidence_release_ids": [1, 2]}
    album_art = {
        "albums": [
            {
                "album_id": "master-1",
                "main_release_id": 1,
                "uri150": "https://i.discogs.com/thumb.jpg",
                "uri": "https://i.discogs.com/full.jpg",
                "width": 600,
                "height": 600,
            }
        ]
    }

    paths = {}
    for name, payload in (
        ("catalog", catalog),
        ("challenge", challenge),
        ("routes_rounds", routes_rounds),
        ("pathfinding_graph", pathfinding_graph),
        ("album_art", album_art),
    ):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(payload))
        paths[name] = path
    return paths


def test_build_evidence_release_registry_cli_wiring(
    onehop_dataset: Path,
    artifact_paths: dict[str, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "release-registry.v1.json"
    exit_code = main(
        [
            "build-evidence-release-registry",
            "--onehop-root",
            str(onehop_dataset),
            "--catalog",
            str(artifact_paths["catalog"]),
            "--challenge",
            str(artifact_paths["challenge"]),
            "--routes-rounds",
            str(artifact_paths["routes_rounds"]),
            "--pathfinding-graph",
            str(artifact_paths["pathfinding_graph"]),
            "--album-art",
            str(artifact_paths["album_art"]),
            "--output",
            str(output_path),
            "--generated-at",
            "2026-08-07T00:00:00+00:00",
        ]
    )
    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["release_ids"] == 2
    assert summary["catalog_version"] == _CATALOG_VERSION

    written = json.loads(output_path.read_text())
    assert written["release_ids"] == [1, 2]


def test_validate_evidence_release_registry_cli_wiring(
    onehop_dataset: Path,
    artifact_paths: dict[str, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "release-registry.v1.json"
    main(
        [
            "build-evidence-release-registry",
            "--onehop-root",
            str(onehop_dataset),
            "--catalog",
            str(artifact_paths["catalog"]),
            "--challenge",
            str(artifact_paths["challenge"]),
            "--routes-rounds",
            str(artifact_paths["routes_rounds"]),
            "--pathfinding-graph",
            str(artifact_paths["pathfinding_graph"]),
            "--album-art",
            str(artifact_paths["album_art"]),
            "--output",
            str(output_path),
            "--generated-at",
            "2026-08-07T00:00:00+00:00",
        ]
    )
    capsys.readouterr()

    exit_code = main(
        [
            "validate-evidence-release-registry",
            "--registry",
            str(output_path),
            "--catalog",
            str(artifact_paths["catalog"]),
        ]
    )
    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    assert result == {"ok": True, "release_ids": 2}
