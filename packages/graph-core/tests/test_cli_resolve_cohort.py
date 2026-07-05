from __future__ import annotations

import json
from pathlib import Path

from networked_players_catalog.cli import main

EXTRACTED = {
    "schema_version": 1,
    "source": {
        "source_url": "https://example.invalid/fake-digs-post",
        "page_title": "Fake Digs Post",
        "saved_at": "2026-07-05",
        "operator_note": "",
    },
    "extractor_version": 1,
    "generated_at": "2026-07-05T00:00:00+00:00",
    "notes": [],
    "candidates": [
        {
            "rank": 1,
            "artist": "Alice",
            "title": "First Light",
            "year": None,
            "master_id": None,
            "release_id": 1,
            "confidence": "high",
            "warnings": [],
        },
        {
            "rank": 2,
            "artist": None,
            "title": None,
            "year": None,
            "master_id": 999_999,
            "release_id": None,
            "confidence": "low",
            "warnings": ["no discogs master/release link found in source HTML"],
        },
    ],
}


def test_resolve_cohort_cli_wiring(dataset_root: Path, tmp_path: Path, capsys) -> None:
    extracted_path = tmp_path / "extracted.json"
    extracted_path.write_text(json.dumps(EXTRACTED))
    output_path = tmp_path / "resolved.json"

    exit_code = main(
        [
            "resolve-cohort",
            "--extracted",
            str(extracted_path),
            "--dataset",
            str(dataset_root),
            "--output",
            str(output_path),
        ]
    )
    assert exit_code == 0

    summary = json.loads(capsys.readouterr().out)
    assert summary["resolved_count"] == 1
    assert summary["unresolved_count"] == 1

    artifact = json.loads(output_path.read_text())
    assert artifact["dataset_snapshot_date"] == "20260601"
    assert artifact["resolved"][0]["artist_id"] == 100
    assert artifact["resolved"][0]["resolution_method"] == "release_id_hint"
