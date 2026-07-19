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


def test_build_challenge_from_dump_applies_artist_family_exclusions_cli_wiring(
    dataset_root: Path, tmp_path: Path, capsys
) -> None:
    albums_path = tmp_path / "albums.json"
    albums_path.write_text(json.dumps({"albums": ALBUMS}))
    exclusions_path = tmp_path / "exclusions.json"
    exclusions_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "artist-family-exclusions",
                "snapshot_date": "20260601",
                "generated_at": "2026-07-19T00:00:00+00:00",
                # Alice(100) and Eve(500) treated as the same family --
                # a one-hop path exists between them (release 4) and must
                # not appear once this exclusion is applied.
                "entries": [{"person_id": 100, "group_act_ids": [500], "source": "dump"}],
            }
        )
    )
    output_path = tmp_path / "challenge.v2.json"

    exit_code = main(
        [
            "build-challenge-from-dump",
            "--onehop-root",
            str(dataset_root),
            "--albums",
            str(albums_path),
            "--artist-family-exclusions",
            str(exclusions_path),
            "--output",
            str(output_path),
        ]
    )
    assert exit_code == 0
    capsys.readouterr()
    artifact = json.loads(output_path.read_text())
    excluded_pair_ids = {(100, 500), (500, 100)}
    for path in artifact["paths"]:
        assert (path["from_artist_id"], path["to_artist_id"]) not in excluded_pair_ids


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


def test_build_album_catalog_cli_wiring(dataset_root: Path, tmp_path: Path, capsys) -> None:
    candidates_path = tmp_path / "candidates.json"
    main(
        [
            "rank-album-candidates",
            "--dataset",
            str(dataset_root),
            "--output",
            str(candidates_path),
        ]
    )
    capsys.readouterr()

    editorial_path = tmp_path / "editorial.json"
    editorial_path.write_text(json.dumps({"albums": [{"artist": "Alice", "title": "First Light"}]}))
    catalog_path = tmp_path / "catalog.json"

    exit_code = main(
        [
            "build-album-catalog",
            "--onehop-root",
            str(dataset_root),
            "--editorial-albums",
            str(editorial_path),
            "--candidates",
            str(candidates_path),
            "--target-count",
            "3",
            "--output",
            str(catalog_path),
        ]
    )
    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["editorial_count"] == 1
    assert summary["total_albums"] == 3

    catalog = json.loads(catalog_path.read_text())
    # ID-resolved (artist_id/main_release_id), not a re-queryable name pair.
    assert catalog["albums"][0]["artist_id"] == 100
    assert catalog["albums"][0]["artist"] == "Alice"
    assert catalog["albums"][0]["title"] == "First Light"
    assert len(catalog["albums"]) == 3

    # The generated catalog is a valid --albums input for build-challenge-from-dump.
    output_path = tmp_path / "challenge.v2.json"
    exit_code = main(
        [
            "build-challenge-from-dump",
            "--onehop-root",
            str(dataset_root),
            "--albums",
            str(catalog_path),
            "--output",
            str(output_path),
        ]
    )
    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["albums_matched"] == 3
