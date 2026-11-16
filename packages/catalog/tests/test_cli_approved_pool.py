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


def test_with_a_pool_the_editorial_default_fallback_does_not_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dropping the explicit --editorial-albums: without a pool the historical
    default (data/albums/top-albums-v1.json, resolved against the working
    directory) is read; with a pool no editorial lane runs.

    The working directory is given a default file that DOES match master 901,
    so this only passes if the fallback is genuinely skipped: were it
    re-enabled, the build would publish 901 and succeed."""
    output = tmp_path / "albums.v1.json"
    args = _full_args(tmp_path, output)
    index = args.index("--editorial-albums")
    explicit_editorial = Path(args[index + 1])
    del args[index : index + 2]
    default_dir = tmp_path / "cwd" / "data" / "albums"
    default_dir.mkdir(parents=True)
    (default_dir / "top-albums-v1.json").write_text(explicit_editorial.read_text())
    monkeypatch.chdir(tmp_path / "cwd")
    pool = _write_pool(tmp_path / "pool.json", [901])
    with pytest.raises(ValueError, match="901"):
        main([*args, "--approved-pool", str(pool)])
    assert not output.exists()

    # Control: the same arguments without a pool DO take the fallback and
    # publish 901, proving the default file above is the one being skipped.
    assert main(args) == 0
    assert 901 in [a["master_id"] for a in json.loads(output.read_text())["albums"]]


@pytest.mark.parametrize("contents", ["null", "[]", '"pool"', "{}"])
def test_a_pool_file_that_is_not_a_valid_pool_fails_instead_of_disabling_the_check(
    tmp_path: Path, contents: str
) -> None:
    """`null` must never be read as "no pool": that would re-enable auto-fill
    while skipping the UNCHECKED warning."""
    output = tmp_path / "albums.v1.json"
    pool = tmp_path / "pool.json"
    pool.write_text(contents)
    with pytest.raises(ValueError, match="malformed"):
        main([*_full_args(tmp_path, output), "--approved-pool", str(pool)])
    assert not output.exists()
