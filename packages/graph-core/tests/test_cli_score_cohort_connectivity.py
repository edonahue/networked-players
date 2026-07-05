from __future__ import annotations

import json
from pathlib import Path

from networked_players_catalog.cli import main

RESOLVED = {
    "schema_version": 1,
    "source": {
        "source_url": "https://example.invalid/fake-digs-post",
        "page_title": "Fake Digs Post",
        "saved_at": "2026-07-05",
        "operator_note": "",
    },
    "resolver_version": 1,
    "generated_at": "2026-07-05T00:00:00+00:00",
    "dataset_snapshot_date": "20260601",
    "resolved": [
        {
            "rank": 1,
            "artist_query": "Alice",
            "title_query": "First Light",
            "resolution_method": "release_id_hint",
            "master_id": 901,
            "release_id": 1,
            "title": "First Light",
            "artist_id": 100,
            "artist_name": "Alice",
            "year": 1993,
            "extraction_confidence": "high",
            "warnings": [],
        },
        {
            "rank": 2,
            "artist_query": "Bob",
            "title_query": "First Light",
            "resolution_method": "release_id_hint",
            "master_id": 901,
            "release_id": 1,
            "title": "First Light",
            "artist_id": 200,
            "artist_name": "Bob",
            "year": 1993,
            "extraction_confidence": "high",
            "warnings": [],
        },
    ],
    "unresolved": [],
}


def test_score_cohort_connectivity_cli_wiring(dataset_root: Path, tmp_path: Path, capsys) -> None:
    resolved_path = tmp_path / "resolved.json"
    resolved_path.write_text(json.dumps(RESOLVED))
    output_dir = tmp_path / "out"

    exit_code = main(
        [
            "score-cohort-connectivity",
            "--resolved",
            str(resolved_path),
            "--dataset",
            str(dataset_root),
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 0

    summary = json.loads(capsys.readouterr().out)
    assert summary["pair_count"] == 1
    assert summary["by_status"] == {"found": 1, "no_path": 0, "skipped": 0}
    assert summary["by_difficulty"]["easy"] == 1

    assert (output_dir / "connectivity.json").exists()
    assert (output_dir / "playable-pairs.json").exists()
    assert (output_dir / "review-report.md").exists()

    connectivity = json.loads((output_dir / "connectivity.json").read_text())
    assert connectivity["dataset_snapshot_date"] == "20260601"

    playable_pairs = json.loads((output_dir / "playable-pairs.json").read_text())
    assert len(playable_pairs) == 1


def test_score_cohort_connectivity_cli_accepts_guardrail_flags(
    dataset_root: Path, tmp_path: Path, capsys
) -> None:
    resolved_path = tmp_path / "resolved.json"
    resolved_path.write_text(json.dumps(RESOLVED))
    output_dir = tmp_path / "out"

    exit_code = main(
        [
            "score-cohort-connectivity",
            "--resolved",
            str(resolved_path),
            "--dataset",
            str(dataset_root),
            "--output-dir",
            str(output_dir),
            "--max-frontier-expansion",
            "5",
            "--pair-timeout-seconds",
            "10",
            "--temp-dir",
            str(tmp_path / "spill"),
        ]
    )
    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["by_status"]["found"] == 1
