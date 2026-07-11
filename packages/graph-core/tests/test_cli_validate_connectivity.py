from __future__ import annotations

import json
from pathlib import Path

import pytest

from networked_players_catalog.cli import main

VALID_CONNECTIVITY = {
    "schema_version": 1,
    "source": {
        "source_url": "https://example.invalid/fake-digs-post",
        "page_title": "Fake Digs Post",
        "saved_at": "2026-07-05",
        "operator_note": "",
    },
    "scorer_version": 2,
    "generated_at": "2026-07-05T00:00:00+00:00",
    "dataset_snapshot_date": "20260601",
    "max_hops": 3,
    "pairs": [
        {
            "album_a_id": "release-1",
            "album_b_id": "release-2",
            "artist_a_id": 100,
            "artist_b_id": 300,
            "status": "found",
            "hop_count": 1,
            "difficulty": "easy",
            "hops": [
                {
                    "release_id": 1,
                    "artist_a_id": 100,
                    "artist_b_id": 300,
                    "quality_flags": ["co_billed_release_artists", "same_recording"],
                }
            ],
            "warnings": [],
            "skip_reason": None,
        }
    ],
    "unresolved": [],
}


def test_validate_connectivity_cli_wiring_accepts_clean_artifact(tmp_path: Path, capsys) -> None:
    input_path = tmp_path / "connectivity.json"
    input_path.write_text(json.dumps(VALID_CONNECTIVITY))

    exit_code = main(["validate-connectivity", "--input", str(input_path)])
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True}


def test_validate_connectivity_cli_wiring_raises_on_broken_artifact(tmp_path: Path) -> None:
    broken = json.loads(json.dumps(VALID_CONNECTIVITY))
    broken["pairs"][0]["status"] = "not-a-real-status"
    input_path = tmp_path / "connectivity.json"
    input_path.write_text(json.dumps(broken))

    with pytest.raises(Exception, match="invalid status"):
        main(["validate-connectivity", "--input", str(input_path)])
