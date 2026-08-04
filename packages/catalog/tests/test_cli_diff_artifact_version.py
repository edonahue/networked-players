"""CLI wiring for `diff-artifact-version`. Full diff-logic coverage lives in
packages/contracts/tests/test_artifact_diff.py -- this file only proves the
CLI reads the right flags and reports exit codes correctly."""

from __future__ import annotations

import json
from pathlib import Path

from networked_players_catalog.cli import main


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload))
    return path


def test_identical_files_exit_zero(tmp_path: Path, capsys) -> None:
    payload = {"catalog_version": "catalog-v1-abc", "albums": []}
    old = _write(tmp_path / "old.json", payload)
    new = _write(tmp_path / "new.json", dict(payload))

    exit_code = main(["diff-artifact-version", "--old", str(old), "--new", str(new)])
    assert exit_code == 0

    report = json.loads(capsys.readouterr().out)
    assert report["identical"] is True


def test_a_real_difference_exits_one_and_reports_it(tmp_path: Path, capsys) -> None:
    old = _write(tmp_path / "old.json", {"catalog_version": "catalog-v1-old"})
    new = _write(tmp_path / "new.json", {"catalog_version": "catalog-v1-new"})

    exit_code = main(["diff-artifact-version", "--old", str(old), "--new", str(new)])
    assert exit_code == 1

    report = json.loads(capsys.readouterr().out)
    assert report["identical"] is False
    assert report["version_field_changes"] == {
        "catalog_version": {"old": "catalog-v1-old", "new": "catalog-v1-new"}
    }
