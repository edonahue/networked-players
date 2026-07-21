from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from networked_players_catalog.cli import main

PROVENANCE = {
    "source": "Discogs monthly data dump (CC0), one-hop working set",
    "license": "See docs/DATA_AND_RIGHTS.md.",
    "snapshot_date": "20260601",
    "generated_by": "test",
    "catalog_version": "catalog-v1-20260601-abc",
    "pool_version": "connection-v1-20260601-def",
    "artifact_version": "connection-artifact-v1-20260601-ghi",
    "note": "Real records, not synthetic.",
}


def _album(album_id: str) -> dict[str, Any]:
    return {
        "id": album_id,
        "title": album_id,
        "year": 1995,
        "act": "Act",
        "label": None,
        "art": None,
    }


def _one_hop(round_id: str, i: int) -> dict[str, Any]:
    return {
        "id": round_id,
        "pool": "real-records",
        "kind": "one_hop",
        "difficulty": "hard",
        "endpoints": [_album(f"album-a{i}"), _album(f"album-c{i}")],
        "answer_set": [{"id": 1000 + i, "name": f"P{i}", "role_category": "guitar"}],
        "distractors": [],
        "clues": [],
        "evidence": [{"contributor_id": 1000 + i}],
        "provenance_note": "test",
    }


def _two_hop(round_id: str) -> dict[str, Any]:
    return {
        "id": round_id,
        "pool": "real-records",
        "kind": "two_hop",
        "difficulty": "hard",
        "endpoints": [_album("album-x"), _album("album-y")],
        "middle": {"album": _album("album-m"), "choices": [_album("album-m")]},
        "answer_set": [],
        "bridge_answer_sets": [[], []],
        "distractors": [],
        "clues": [],
        "evidence": [],
        "provenance_note": "test",
    }


GENERATED_AT = "2026-07-22T00:00:00+00:00"


def _round_id(i: int) -> str:
    return f"conn-{i:010x}"


def _rounds_path(tmp_path: Path, n: int = 10) -> Path:
    rounds = [_one_hop(_round_id(i), i) for i in range(n)]
    rounds.append(_two_hop("conn-2222222222"))
    path = tmp_path / "rounds.v1.json"
    path.write_text(json.dumps({"schema_version": 1, "provenance": PROVENANCE, "rounds": rounds}))
    return path


def test_build_connection_daily_manifest_cli_wiring(tmp_path: Path, capsys) -> None:
    rounds_path = _rounds_path(tmp_path, 10)
    output_path = tmp_path / "daily-manifest.v1.json"

    exit_code = main(
        [
            "build-connection-daily-manifest",
            "--rounds",
            str(rounds_path),
            "--start-date",
            "2026-08-01",
            "--days",
            "10",
            "--output",
            str(output_path),
            "--generated-at",
            GENERATED_AT,
        ]
    )
    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["days_scheduled"] == 10
    assert summary["first_date"] == "2026-08-01"
    assert "diagnostics" in summary

    manifest = json.loads(output_path.read_text())
    assert manifest["mode"] == "connection_guesser_one_hop"
    assert manifest["generated_at"] == GENERATED_AT
    assert len(manifest["schedule"]) == 10
    assert all(e["round_id"] in {_round_id(i) for i in range(10)} for e in manifest["schedule"])
    assert not any(e["round_id"] == "conn-2222222222" for e in manifest["schedule"])


def test_extend_connection_daily_manifest_cli_wiring(tmp_path: Path, capsys) -> None:
    rounds_path = _rounds_path(tmp_path, 10)
    manifest_path = tmp_path / "daily-manifest.v1.json"
    main(
        [
            "build-connection-daily-manifest",
            "--rounds",
            str(rounds_path),
            "--start-date",
            "2026-08-01",
            "--days",
            "4",
            "--output",
            str(manifest_path),
            "--generated-at",
            GENERATED_AT,
        ]
    )
    capsys.readouterr()
    extended_path = tmp_path / "daily-manifest-extended.v1.json"
    extended_at = "2026-08-05T00:00:00+00:00"

    exit_code = main(
        [
            "extend-connection-daily-manifest",
            "--manifest",
            str(manifest_path),
            "--rounds",
            str(rounds_path),
            "--days",
            "3",
            "--output",
            str(extended_path),
            "--generated-at",
            extended_at,
        ]
    )
    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["days_before"] == 4
    assert summary["days_after"] == 7

    before = json.loads(manifest_path.read_text())
    after = json.loads(extended_path.read_text())
    assert after["schedule"][:4] == before["schedule"]
    assert after["generated_at"] == extended_at


def test_validate_connection_daily_manifest_cli_wiring(tmp_path: Path, capsys) -> None:
    rounds_path = _rounds_path(tmp_path, 6)
    manifest_path = tmp_path / "daily-manifest.v1.json"
    main(
        [
            "build-connection-daily-manifest",
            "--rounds",
            str(rounds_path),
            "--start-date",
            "2026-08-01",
            "--days",
            "6",
            "--output",
            str(manifest_path),
            "--generated-at",
            GENERATED_AT,
        ]
    )
    capsys.readouterr()

    exit_code = main(
        [
            "validate-connection-daily-manifest",
            "--manifest",
            str(manifest_path),
            "--rounds",
            str(rounds_path),
        ]
    )
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True}


def test_connection_daily_manifest_diagnostics_cli_wiring(tmp_path: Path, capsys) -> None:
    rounds_path = _rounds_path(tmp_path, 6)
    manifest_path = tmp_path / "daily-manifest.v1.json"
    main(
        [
            "build-connection-daily-manifest",
            "--rounds",
            str(rounds_path),
            "--start-date",
            "2026-08-01",
            "--days",
            "6",
            "--output",
            str(manifest_path),
            "--generated-at",
            GENERATED_AT,
        ]
    )
    capsys.readouterr()

    exit_code = main(
        [
            "connection-daily-manifest-diagnostics",
            "--manifest",
            str(manifest_path),
            "--rounds",
            str(rounds_path),
        ]
    )
    assert exit_code == 0
    diagnostics = json.loads(capsys.readouterr().out)
    assert diagnostics["total_dates"] == 6
