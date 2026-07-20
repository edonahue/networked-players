from __future__ import annotations

import json
from pathlib import Path

import pytest

from networked_players_catalog.cli import main
from test_rounds_generator import ALBUMS, CREDITS, RELEASES, SNAPSHOT_DATE


@pytest.fixture
def rounds_dataset_root(tmp_path: Path) -> Path:
    from conftest import write_synthetic_dataset

    return write_synthetic_dataset(
        tmp_path / f"snapshot={SNAPSHOT_DATE}", release_rows=RELEASES, credit_rows=CREDITS
    )


def test_build_rounds_from_dump_cli_wiring(
    rounds_dataset_root: Path, tmp_path: Path, capsys
) -> None:
    albums_path = tmp_path / "albums.json"
    albums_path.write_text(json.dumps({"albums": ALBUMS}))
    universe_path = tmp_path / "universe.v1.json"
    rounds_path = tmp_path / "rounds.v1.json"

    exit_code = main(
        [
            "build-rounds-from-dump",
            "--onehop-root",
            str(rounds_dataset_root),
            "--albums",
            str(albums_path),
            "--pool-version",
            "rounds-v1-test",
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
    summary = json.loads(capsys.readouterr().out)
    assert summary["albums_matched"] == 5
    assert summary["diagnostics"]["one_hop_selected"] == 3
    assert summary["diagnostics"]["two_hop_selected"] == 1

    universe = json.loads(universe_path.read_text())
    rounds = json.loads(rounds_path.read_text())
    assert universe["pool_version"] == "rounds-v1-test"
    assert rounds["pool_version"] == "rounds-v1-test"
    assert len(rounds["rounds"]) == 4


def test_validate_rounds_cli_wiring(rounds_dataset_root: Path, tmp_path: Path, capsys) -> None:
    albums_path = tmp_path / "albums.json"
    albums_path.write_text(json.dumps({"albums": ALBUMS}))
    universe_path = tmp_path / "universe.v1.json"
    rounds_path = tmp_path / "rounds.v1.json"
    main(
        [
            "build-rounds-from-dump",
            "--onehop-root",
            str(rounds_dataset_root),
            "--albums",
            str(albums_path),
            "--pool-version",
            "rounds-v1-test",
            "--output-universe",
            str(universe_path),
            "--output-rounds",
            str(rounds_path),
        ]
    )
    capsys.readouterr()

    exit_code = main(
        ["validate-rounds", "--universe", str(universe_path), "--rounds", str(rounds_path)]
    )
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True}


def test_build_rounds_from_dump_raises_when_no_eligible_rounds(
    dataset_root: Path, tmp_path: Path
) -> None:
    """The shared fixture graph (conftest.py) credits everyone with the
    generic role_text "Performer" -- no hop clears the performer allowlist,
    so no eligible round exists at all."""
    albums = [
        {"artist": "Alice", "title": "First Light"},
        {"artist": "Cara", "title": "Third Wave"},
        {"artist": "Eve", "title": "Sixth Sense"},
    ]
    albums_path = tmp_path / "albums.json"
    albums_path.write_text(json.dumps({"albums": albums}))

    with pytest.raises(ValueError, match="no eligible rounds"):
        main(
            [
                "build-rounds-from-dump",
                "--onehop-root",
                str(dataset_root),
                "--albums",
                str(albums_path),
                "--pool-version",
                "rounds-v1-test",
                "--output-universe",
                str(tmp_path / "universe.v1.json"),
                "--output-rounds",
                str(tmp_path / "rounds.v1.json"),
            ]
        )
