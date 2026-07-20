from __future__ import annotations

import json
from pathlib import Path

import pytest

from networked_players_catalog.cli import main


def _rounds_artifact(pool_version: str, round_ids: list[str]) -> dict:
    return {"pool_version": pool_version, "rounds": [{"id": rid} for rid in round_ids]}


def test_build_daily_manifest_cli_wiring(tmp_path: Path, capsys) -> None:
    rounds_path = tmp_path / "rounds.v1.json"
    rounds_path.write_text(
        json.dumps(_rounds_artifact("rounds-v1-a", [f"round-{i:06d}" for i in range(1, 6)]))
    )
    output_path = tmp_path / "daily-manifest.v1.json"

    exit_code = main(
        [
            "build-daily-manifest",
            "--rounds",
            str(rounds_path),
            "--start-date",
            "2026-07-19",
            "--days",
            "5",
            "--output",
            str(output_path),
        ]
    )
    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["days_scheduled"] == 5
    assert summary["first_date"] == "2026-07-19"

    manifest = json.loads(output_path.read_text())
    assert len(manifest["schedule"]) == 5


def test_extend_daily_manifest_cli_wiring(tmp_path: Path, capsys) -> None:
    rounds_path = tmp_path / "rounds.v1.json"
    round_ids = [f"round-{i:06d}" for i in range(1, 11)]
    rounds_path.write_text(json.dumps(_rounds_artifact("rounds-v1-a", round_ids)))
    manifest_path = tmp_path / "daily-manifest.v1.json"

    main(
        [
            "build-daily-manifest",
            "--rounds",
            str(rounds_path),
            "--start-date",
            "2026-07-19",
            "--days",
            "5",
            "--output",
            str(manifest_path),
        ]
    )
    capsys.readouterr()

    exit_code = main(
        [
            "extend-daily-manifest",
            "--manifest",
            str(manifest_path),
            "--rounds",
            str(rounds_path),
            "--days",
            "5",
            "--output",
            str(manifest_path),
        ]
    )
    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["days_before"] == 5
    assert summary["days_after"] == 10

    manifest = json.loads(manifest_path.read_text())
    assert len(manifest["schedule"]) == 10


def test_validate_daily_manifest_cli_wiring(tmp_path: Path, capsys) -> None:
    rounds_path = tmp_path / "rounds.v1.json"
    rounds_path.write_text(
        json.dumps(_rounds_artifact("rounds-v1-a", [f"round-{i:06d}" for i in range(1, 6)]))
    )
    manifest_path = tmp_path / "daily-manifest.v1.json"
    main(
        [
            "build-daily-manifest",
            "--rounds",
            str(rounds_path),
            "--start-date",
            "2026-07-19",
            "--days",
            "5",
            "--output",
            str(manifest_path),
        ]
    )
    capsys.readouterr()

    exit_code = main(
        ["validate-daily-manifest", "--manifest", str(manifest_path), "--rounds", str(rounds_path)]
    )
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True}


def test_extend_daily_manifest_rejects_pool_version_mismatch(tmp_path: Path, capsys) -> None:
    rounds_path = tmp_path / "rounds.v1.json"
    rounds_path.write_text(
        json.dumps(_rounds_artifact("rounds-v1-a", [f"round-{i:06d}" for i in range(1, 6)]))
    )
    manifest_path = tmp_path / "daily-manifest.v1.json"
    main(
        [
            "build-daily-manifest",
            "--rounds",
            str(rounds_path),
            "--start-date",
            "2026-07-19",
            "--days",
            "5",
            "--output",
            str(manifest_path),
        ]
    )
    capsys.readouterr()

    other_rounds_path = tmp_path / "rounds-v2.json"
    other_rounds_path.write_text(
        json.dumps(_rounds_artifact("rounds-v1-b", [f"round-{i:06d}" for i in range(1, 6)]))
    )
    with pytest.raises(ValueError, match="does not match"):
        main(
            [
                "extend-daily-manifest",
                "--manifest",
                str(manifest_path),
                "--rounds",
                str(other_rounds_path),
                "--days",
                "5",
                "--output",
                str(manifest_path),
            ]
        )
