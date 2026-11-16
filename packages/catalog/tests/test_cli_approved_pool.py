"""build-public-album-catalog --approved-pool (ADR 0072 section 2).

Reuses the synthetic one-hop/masters fixtures of test_cli_public_album_catalog.py:
master 901 (Alice, "First Light") is the editorial album; Cara's "Third Wave"
has no master and is only reachable through the --candidates auto-fill.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from networked_players_catalog.cli import main
from test_cli_public_album_catalog import (
    _base_args,
    _write_exclusions,
    _write_masters_dataset,
    _write_onehop_dataset,
    _write_release_format_policy,
)


def _full_args(tmp_path: Path, output: Path) -> list[str]:
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    masters_root = _write_masters_dataset(tmp_path / "masters")
    args = _base_args(tmp_path, onehop_root=onehop_root, output=output)
    return [
        *args,
        "--release-format-policy",
        str(_write_release_format_policy(tmp_path / "policy.json")),
        "--masters-root",
        str(masters_root),
        "--studio-album-exclusions",
        str(_write_exclusions(tmp_path / "exclusions.json")),
    ]


def _write_pool(path: Path, master_ids: list[int]) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "note": "synthetic",
                "albums": [
                    {"master_id": m, "round": 0, "selection_source": "editorial"}
                    for m in sorted(master_ids)
                ],
            }
        )
    )
    return path


def test_without_an_approved_pool_the_build_warns_that_it_is_unchecked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "albums.v1.json"
    assert main(_full_args(tmp_path, output)) == 0
    assert "UNCHECKED" in capsys.readouterr().err
    assert len(json.loads(output.read_text())["albums"]) == 2  # auto-fill still on


def test_a_pool_disables_auto_fill_and_passes_when_it_matches(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "albums.v1.json"
    pool = _write_pool(tmp_path / "pool.json", [901])
    assert main([*_full_args(tmp_path, output), "--approved-pool", str(pool)]) == 0
    assert "UNCHECKED" not in capsys.readouterr().err
    albums = json.loads(output.read_text())["albums"]
    assert [a["master_id"] for a in albums] == [901]  # Cara was NOT auto-filled


def test_a_pool_with_an_unsupplied_album_fails_the_build(tmp_path: Path) -> None:
    output = tmp_path / "albums.v1.json"
    pool = _write_pool(tmp_path / "pool.json", [901, 777])
    with pytest.raises(ValueError, match="777"):
        main([*_full_args(tmp_path, output), "--approved-pool", str(pool)])
    assert not output.exists()


def test_a_pool_rejects_an_unapproved_published_album(tmp_path: Path) -> None:
    output = tmp_path / "albums.v1.json"
    pool = _write_pool(tmp_path / "pool.json", [123])
    with pytest.raises(ValueError, match="not approved"):
        main([*_full_args(tmp_path, output), "--approved-pool", str(pool)])


def test_with_a_pool_the_editorial_default_fallback_does_not_apply(tmp_path: Path) -> None:
    """Dropping the explicit --editorial-albums: without a pool the historical
    default (top-albums-v1.json) would be read; with one no editorial lane
    runs, so a pool listing the editorial album reports it as unsupplied."""
    output = tmp_path / "albums.v1.json"
    args = _full_args(tmp_path, output)
    index = args.index("--editorial-albums")
    del args[index : index + 2]
    pool = _write_pool(tmp_path / "pool.json", [901])
    with pytest.raises(ValueError, match="901"):
        main([*args, "--approved-pool", str(pool)])
