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


def _credit(artist_id: int, role_text: str) -> dict[str, Any]:
    return {
        "release_id": 501,
        "credit_scope": "release_artist",
        "artist_id": artist_id,
        "name": f"Artist {artist_id}",
        "anv": None,
        "role_text": role_text,
        "is_linked": True,
        "playable_identity": True,
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
                # Alice (100): Guitar only -- real substantive work, never
                # listed. Bob (200): Mastered By only -- background-only.
                "credits": [_credit(100, "Guitar"), _credit(200, "Mastered By")],
            }
        ],
    }


def _routes_rounds() -> dict[str, Any]:
    return {
        "provenance": {"catalog_version": _CATALOG_VERSION},
        "artists": [],
        "rounds": [],
        "releases": [],
    }


def _contributor_index() -> dict[str, Any]:
    # Deliberately a minimal, hand-built stand-in rather than a real
    # build_contributor_index() call -- this CLI command reads an
    # already-published index (never rebuilds one), so the test should
    # exercise exactly that contract: only artist_id needs to be real.
    return {"contributors": [{"artist_id": 100}, {"artist_id": 200}]}


@pytest.fixture
def artifact_paths(tmp_path: Path) -> dict[str, Path]:
    paths = {
        "catalog": tmp_path / "catalog.json",
        "challenge": tmp_path / "challenge.json",
        "routes_rounds": tmp_path / "routes-rounds.json",
        "contributor_index": tmp_path / "contributors" / "index.v1.json",
        "output": tmp_path / "contributors" / "background-only-profiles.v1.json",
    }
    paths["catalog"].write_text(json.dumps(_catalog()))
    paths["challenge"].write_text(json.dumps(_challenge()))
    paths["routes_rounds"].write_text(json.dumps(_routes_rounds()))
    paths["contributor_index"].parent.mkdir(parents=True, exist_ok=True)
    paths["contributor_index"].write_text(json.dumps(_contributor_index()))
    return paths


def test_build_background_only_profiles_cli_wiring(
    artifact_paths: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [
            "build-background-only-profiles",
            "--challenge",
            str(artifact_paths["challenge"]),
            "--routes-rounds",
            str(artifact_paths["routes_rounds"]),
            "--catalog",
            str(artifact_paths["catalog"]),
            "--contributor-index",
            str(artifact_paths["contributor_index"]),
            "--output",
            str(artifact_paths["output"]),
            "--generated-at",
            "2026-08-31T00:00:00+00:00",
        ]
    )
    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["artist_ids"] == 1
    assert summary["catalog_version"] == _CATALOG_VERSION

    written = json.loads(artifact_paths["output"].read_text())
    assert written["artist_ids"] == [200]


def test_validate_background_only_profiles_cli_wiring(
    artifact_paths: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    main(
        [
            "build-background-only-profiles",
            "--challenge",
            str(artifact_paths["challenge"]),
            "--routes-rounds",
            str(artifact_paths["routes_rounds"]),
            "--catalog",
            str(artifact_paths["catalog"]),
            "--contributor-index",
            str(artifact_paths["contributor_index"]),
            "--output",
            str(artifact_paths["output"]),
            "--generated-at",
            "2026-08-31T00:00:00+00:00",
        ]
    )
    capsys.readouterr()

    exit_code = main(
        [
            "validate-background-only-profiles",
            "--artifact",
            str(artifact_paths["output"]),
            "--catalog",
            str(artifact_paths["catalog"]),
            "--contributor-index",
            str(artifact_paths["contributor_index"]),
        ]
    )
    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    assert result == {"ok": True, "artist_ids": 1}


def test_build_refuses_to_write_when_validation_fails(
    artifact_paths: dict[str, Path],
) -> None:
    # A contributor index that doesn't actually contain artist 200 -- the
    # sole background-only artist_id fails the "published contributor"
    # check, so the build must refuse to write rather than emit an invalid
    # artifact.
    artifact_paths["contributor_index"].write_text(
        json.dumps({"contributors": [{"artist_id": 100}]})
    )
    with pytest.raises(ValueError, match="not a published contributor"):
        main(
            [
                "build-background-only-profiles",
                "--challenge",
                str(artifact_paths["challenge"]),
                "--routes-rounds",
                str(artifact_paths["routes_rounds"]),
                "--catalog",
                str(artifact_paths["catalog"]),
                "--contributor-index",
                str(artifact_paths["contributor_index"]),
                "--output",
                str(artifact_paths["output"]),
                "--generated-at",
                "2026-08-31T00:00:00+00:00",
            ]
        )
    assert not artifact_paths["output"].exists()
