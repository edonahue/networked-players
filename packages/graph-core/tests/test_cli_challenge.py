from __future__ import annotations

import json
from pathlib import Path

from networked_players_catalog.cli import main

ALBUMS = [
    {"artist": "Alice", "title": "First Light"},
    {"artist": "Cara", "title": "Third Wave"},
    {"artist": "Eve", "title": "Sixth Sense"},
]


def test_build_challenge_from_dump_cli_wiring(dataset_root: Path, tmp_path: Path, capsys) -> None:
    albums_path = tmp_path / "albums.json"
    albums_path.write_text(json.dumps({"albums": ALBUMS}))
    output_path = tmp_path / "challenge.v2.json"

    exit_code = main(
        [
            "build-challenge-from-dump",
            "--onehop-root",
            str(dataset_root),
            "--albums",
            str(albums_path),
            "--output",
            str(output_path),
        ]
    )
    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["albums_matched"] == 3
    assert report["paths_found"] >= 1

    artifact = json.loads(output_path.read_text())
    assert artifact["schema_version"] == 2
    assert artifact["provenance"]["snapshot_date"] == "20260601"


def test_validate_challenge_cli_wiring(dataset_root: Path, tmp_path: Path, capsys) -> None:
    albums_path = tmp_path / "albums.json"
    albums_path.write_text(json.dumps({"albums": ALBUMS}))
    output_path = tmp_path / "challenge.v2.json"
    main(
        [
            "build-challenge-from-dump",
            "--onehop-root",
            str(dataset_root),
            "--albums",
            str(albums_path),
            "--output",
            str(output_path),
        ]
    )
    capsys.readouterr()

    exit_code = main(["validate-challenge", "--input", str(output_path)])
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True}


def test_rank_album_candidates_cli_wiring(dataset_root: Path, tmp_path: Path, capsys) -> None:
    output_path = tmp_path / "candidates.json"
    exit_code = main(
        [
            "rank-album-candidates",
            "--dataset",
            str(dataset_root),
            "--output",
            str(output_path),
        ]
    )
    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["candidate_count"] > 0
    candidates = json.loads(output_path.read_text())
    assert len(candidates) == summary["candidate_count"]
