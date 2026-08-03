from __future__ import annotations

import json
from pathlib import Path

import pytest

from networked_players_catalog.cli import main
from test_rounds_generator import CREDITS, RELEASES, SNAPSHOT_DATE


@pytest.fixture
def classify_dataset_root(tmp_path: Path) -> Path:
    from conftest import write_synthetic_dataset

    return write_synthetic_dataset(
        tmp_path / f"snapshot={SNAPSHOT_DATE}", release_rows=RELEASES, credit_rows=CREDITS
    )


def test_classify_roles_cli_wiring(classify_dataset_root: Path, tmp_path: Path, capsys) -> None:
    output_path = tmp_path / "role-taxonomy-report.json"

    exit_code = main(
        [
            "classify-roles",
            "--dataset",
            str(classify_dataset_root),
            "--output",
            str(output_path),
            "--top-unknown",
            "5",
        ]
    )
    assert exit_code == 0

    report = json.loads(capsys.readouterr().out)
    assert report["total_credits"] == len(CREDITS)
    assert 0.0 <= report["classified_pct"] <= 100.0
    assert isinstance(report["unknown_role_text_frequency"], list)

    written = json.loads(output_path.read_text())
    assert written == report


def test_classify_roles_cli_without_output_still_prints(
    classify_dataset_root: Path, capsys
) -> None:
    exit_code = main(["classify-roles", "--dataset", str(classify_dataset_root)])
    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["total_credits"] == len(CREDITS)
