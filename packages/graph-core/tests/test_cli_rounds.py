from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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


@pytest.fixture
def non_performer_dataset_root(tmp_path: Path) -> Path:
    """Mirrors conftest.py's shared `dataset_root` topology (releases R1/R2/
    R3/R4/R6: Alice-Bob-Cara-Dan-Eve, real and mutually reachable) but with
    every credit's role text "Producer" instead of "Performer" -- that text
    became genuinely performer-eligible itself in the 2026-09-01 ADR 0068
    audit, so a test asserting NO eligible round exists despite real
    connectivity needs a role text that still is one."""
    from conftest import _credit, _release, write_synthetic_dataset

    def _co_credited(release_id: int, *artists: tuple[int, str]) -> list[dict[str, Any]]:
        rows = []
        for artist_id, name in artists:
            rows.append(
                _credit(
                    release_id,
                    artist_id=artist_id,
                    name=name,
                    scope="release_artist",
                    role_text="Producer",
                )
            )
            rows.append(
                _credit(
                    release_id,
                    artist_id=artist_id,
                    name=name,
                    scope="track_artist",
                    role_text=None,
                    track_index=0,
                )
            )
        return rows

    releases = [
        _release(1, "First Light"),
        _release(2, "Second Set"),
        _release(3, "Third Wave"),
        _release(4, "Large Ensemble"),
        _release(6, "Sixth Sense"),
    ]
    credits = [
        *_co_credited(1, (100, "Alice"), (200, "Bob")),
        *_co_credited(2, (200, "Bob"), (300, "Cara")),
        *_co_credited(3, (300, "Cara"), (400, "Dan")),
        *_co_credited(4, (100, "Alice"), (500, "Eve")),
        *_co_credited(6, (400, "Dan"), (500, "Eve")),
    ]
    root = tmp_path / f"snapshot={SNAPSHOT_DATE}"
    return write_synthetic_dataset(root, release_rows=releases, credit_rows=credits)


def test_build_rounds_from_dump_raises_when_no_eligible_rounds(
    non_performer_dataset_root: Path, tmp_path: Path
) -> None:
    """The fixture graph credits everyone with "Producer" -- real, mutually
    reachable connectivity, but no hop clears the performer allowlist, so no
    eligible round exists at all."""
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
                str(non_performer_dataset_root),
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
