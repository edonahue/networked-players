from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from networked_players_catalog.cli import main

_SNAPSHOT = "20260601"
_CATALOG_VERSION = "catalog-v1-20260601-abc123abc123"


def _catalog() -> dict[str, Any]:
    return {
        "catalog_version": _CATALOG_VERSION,
        "snapshot_date": _SNAPSHOT,
        "albums": [
            {"id": "master-1", "title": "First Light", "artist_id": 100, "year": 1995},
            {"id": "master-2", "title": "Second Wave", "artist_id": 200, "year": 2001},
        ],
    }


def _challenge() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "provenance": {"catalog_version": _CATALOG_VERSION},
        "artists": [{"artist_id": 100, "name": "Alice"}, {"artist_id": 200, "name": "Bob"}],
        "paths": [
            {
                "id": "path-1",
                "from_album_id": "master-1",
                "to_album_id": "master-2",
                "hops": [{"release_id": 501, "artist_a_id": 100, "artist_b_id": 200}],
            }
        ],
        "releases": [
            {
                "snapshot_date": _SNAPSHOT,
                "release_id": 501,
                "title": "R501",
                "credits": [
                    {
                        "release_id": 501,
                        "credit_scope": "release_artist",
                        "artist_id": 100,
                        "name": "Alice",
                        "anv": None,
                        "role_text": "Guitar",
                        "is_linked": True,
                        "playable_identity": True,
                    },
                    {
                        "release_id": 501,
                        "credit_scope": "release_artist",
                        "artist_id": 200,
                        "name": "Bob",
                        "anv": None,
                        "role_text": "Bass",
                        "is_linked": True,
                        "playable_identity": True,
                    },
                ],
            }
        ],
    }


def _evidence_release_registry() -> dict[str, Any]:
    return {"release_ids": [501], "years": [1979]}


def _routes_universe() -> dict[str, Any]:
    return {"provenance": {"catalog_version": _CATALOG_VERSION}, "albums": []}


def _routes_rounds() -> dict[str, Any]:
    return {
        "provenance": {"catalog_version": _CATALOG_VERSION},
        "artists": [],
        "rounds": [],
        "releases": [],
    }


@pytest.fixture
def artifact_paths(tmp_path: Path) -> dict[str, Path]:
    paths = {
        "catalog": tmp_path / "catalog.json",
        "challenge": tmp_path / "challenge.json",
        "routes_universe": tmp_path / "routes-universe.json",
        "routes_rounds": tmp_path / "routes-rounds.json",
        "evidence_release_registry": tmp_path / "release-registry.v1.json",
        "output": tmp_path / "contributors" / "index.v1.json",
    }
    paths["catalog"].write_text(json.dumps(_catalog()))
    paths["challenge"].write_text(json.dumps(_challenge()))
    paths["routes_universe"].write_text(json.dumps(_routes_universe()))
    paths["routes_rounds"].write_text(json.dumps(_routes_rounds()))
    paths["evidence_release_registry"].write_text(json.dumps(_evidence_release_registry()))
    return paths


def test_build_contributor_index_cli_wiring(
    artifact_paths: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [
            "build-contributor-index",
            "--challenge",
            str(artifact_paths["challenge"]),
            "--routes-universe",
            str(artifact_paths["routes_universe"]),
            "--routes-rounds",
            str(artifact_paths["routes_rounds"]),
            "--catalog",
            str(artifact_paths["catalog"]),
            "--evidence-release-registry",
            str(artifact_paths["evidence_release_registry"]),
            "--output",
            str(artifact_paths["output"]),
            "--generated-at",
            "2026-08-03T00:00:00+00:00",
        ]
    )
    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["contributors"] == 2
    assert summary["catalog_version"] == _CATALOG_VERSION

    written = json.loads(artifact_paths["output"].read_text())
    assert len(written["contributors"]) == 2


def test_validate_contributor_index_cli_wiring(
    artifact_paths: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    main(
        [
            "build-contributor-index",
            "--challenge",
            str(artifact_paths["challenge"]),
            "--routes-universe",
            str(artifact_paths["routes_universe"]),
            "--routes-rounds",
            str(artifact_paths["routes_rounds"]),
            "--catalog",
            str(artifact_paths["catalog"]),
            "--evidence-release-registry",
            str(artifact_paths["evidence_release_registry"]),
            "--output",
            str(artifact_paths["output"]),
            "--generated-at",
            "2026-08-03T00:00:00+00:00",
        ]
    )
    capsys.readouterr()

    exit_code = main(
        [
            "validate-contributor-index",
            "--index",
            str(artifact_paths["output"]),
            "--catalog",
            str(artifact_paths["catalog"]),
        ]
    )
    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    assert result == {"ok": True, "contributors": 2}
