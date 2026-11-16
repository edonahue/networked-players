"""build-connection-rounds: build_parameters stamping, inheritance and declared
lineage (ADR 0072 section 1). Mirrors `test_cli_record_routes.py`'s read-back
tests, reusing its synthetic one-hop dataset and catalog."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any

import pytest

from networked_players_catalog.cli import main
from test_cli_record_routes import _write_catalog, _write_onehop_dataset


def _build(tmp_path: Path, *extra_args: str) -> tuple[int, str, str, Path]:
    onehop_root = _write_onehop_dataset(tmp_path / "onehop")
    catalog_path = _write_catalog(tmp_path / "catalog.json")
    universe_path = tmp_path / "out-universe.v1.json"
    rounds_path = tmp_path / "out-rounds.v1.json"
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(
            [
                "build-connection-rounds",
                "--onehop-root",
                str(onehop_root),
                "--albums",
                str(catalog_path),
                "--max-endpoint-share",
                "1.0",
                "--max-bridge-share",
                "1.0",
                "--output-universe",
                str(universe_path),
                "--output-rounds",
                str(rounds_path),
                *extra_args,
            ]
        )
    return code, out.getvalue(), err.getvalue(), universe_path


def _previous(path: Path, build_parameters: dict[str, Any] | None) -> Path:
    provenance: dict[str, Any] = {"snapshot_date": "20260601"}
    if build_parameters is not None:
        provenance["build_parameters"] = build_parameters
    path.write_text(json.dumps({"provenance": provenance}))
    return path


def test_parameters_are_stamped_and_the_catalog_input_is_declared(tmp_path: Path) -> None:
    code, stdout, stderr, universe_path = _build(tmp_path)
    assert code == 0
    provenance = json.loads(universe_path.read_text())["provenance"]
    assert provenance["build_parameters"] == {
        "one_hop_target": 300,
        "two_hop_target": 200,
        "max_endpoint_share": 1.0,
        "max_bridge_share": 1.0,
    }
    assert provenance["inputs"] == {"catalog": "catalog-v1-20260601-test"}
    assert "no previous artifact given" in stderr
    assert "300 (default)" in stderr
    assert json.loads(stdout)["build_parameters"]["two_hop_target"] == {
        "value": 200,
        "source": "default",
    }


def test_previous_universe_targets_are_inherited(tmp_path: Path) -> None:
    previous = _previous(tmp_path / "previous.json", {"one_hop_target": 450, "two_hop_target": 321})
    code, stdout, stderr, universe_path = _build(
        tmp_path, "--previous-connection-universe", str(previous)
    )
    assert code == 0
    stamped = json.loads(universe_path.read_text())["provenance"]["build_parameters"]
    assert stamped["one_hop_target"] == 450
    assert stamped["two_hop_target"] == 321
    assert "321 (inherited)" in stderr
    assert json.loads(stdout)["build_parameters"]["one_hop_target"]["source"] == "inherited"


def test_an_explicit_flag_overrides_and_the_report_says_so(tmp_path: Path) -> None:
    previous = _previous(tmp_path / "previous.json", {"two_hop_target": 321})
    code, stdout, stderr, universe_path = _build(
        tmp_path,
        "--previous-connection-universe",
        str(previous),
        "--two-hop-target",
        "7",
    )
    assert code == 0
    stamped = json.loads(universe_path.read_text())["provenance"]["build_parameters"]
    assert stamped["two_hop_target"] == 7
    assert "7 (cli)" in stderr
    assert json.loads(stdout)["build_parameters"]["two_hop_target"]["source"] == "cli"


def test_previous_without_a_block_falls_back_to_defaults(tmp_path: Path) -> None:
    previous = _previous(tmp_path / "previous.json", None)
    code, _stdout, stderr, universe_path = _build(
        tmp_path, "--previous-connection-universe", str(previous)
    )
    assert code == 0
    assert (
        json.loads(universe_path.read_text())["provenance"]["build_parameters"]["two_hop_target"]
        == 200
    )
    assert "200 (default)" in stderr


def test_malformed_previous_block_fails_naming_the_flag(tmp_path: Path) -> None:
    previous = tmp_path / "previous.json"
    previous.write_text(json.dumps({"provenance": {"build_parameters": [1, 2]}}))
    with pytest.raises(Exception, match="--previous-connection-universe"):
        _build(tmp_path, "--previous-connection-universe", str(previous))
