from __future__ import annotations

import json
from pathlib import Path

from networked_players_catalog.cli import main

SOURCE = {
    "source_url": "https://example.invalid/fake-digs-post",
    "page_title": "Fake Digs Post",
    "saved_at": "2026-07-05",
    "operator_note": "",
}

RESOLVED = {
    "schema_version": 1,
    "source": SOURCE,
    "resolver_version": 1,
    "generated_at": "2026-07-05T00:00:00+00:00",
    "dataset_snapshot_date": "20260601",
    "resolved": [
        {
            "rank": 1,
            "artist_query": "Alice",
            "title_query": "First Light",
            "resolution_method": "release_id_hint",
            "master_id": None,
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
            "artist_query": "Cara",
            "title_query": "Third Wave",
            "resolution_method": "release_id_hint",
            "master_id": None,
            "release_id": 2,
            "title": "Third Wave",
            "artist_id": 300,
            "artist_name": "Cara",
            "year": 1995,
            "extraction_confidence": "high",
            "warnings": [],
        },
    ],
    "unresolved": [],
}

CONNECTIVITY = {
    "schema_version": 1,
    "source": SOURCE,
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
                    "quality_flags": ["co_billed_release_artists"],
                }
            ],
            "warnings": [],
            "skip_reason": None,
        }
    ],
    "unresolved": [],
}

SELECTION = {
    "schema_version": 1,
    "reviewed_by": "Erich",
    "reviewed_at": "2026-07-05T12:00:00+00:00",
    "allow_flagged_pairs": False,
    "approved_pairs": [{"album_a_id": "release-1", "album_b_id": "release-2"}],
}


def test_promote_playable_cohort_cli_wiring(tmp_path: Path, capsys) -> None:
    resolved_path = tmp_path / "resolved.json"
    connectivity_path = tmp_path / "connectivity.json"
    selection_path = tmp_path / "selection.json"
    output_path = tmp_path / "cohort-playable-v1.json"

    resolved_path.write_text(json.dumps(RESOLVED))
    connectivity_path.write_text(json.dumps(CONNECTIVITY))
    selection_path.write_text(json.dumps(SELECTION))

    exit_code = main(
        [
            "promote-playable-cohort",
            "--resolved",
            str(resolved_path),
            "--connectivity",
            str(connectivity_path),
            "--selection",
            str(selection_path),
            "--cohort-id",
            "fake-digs-post",
            "--output",
            str(output_path),
        ]
    )
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "prepublish checklist" in captured.err
    summary = json.loads(captured.out)
    assert summary["album_count"] == 2
    assert summary["pair_count"] == 1

    assert output_path.exists()
    playable = json.loads(output_path.read_text())
    assert playable["cohort_id"] == "fake-digs-post"
    assert len(playable["pairs"]) == 1


def test_validate_playable_cohort_cli_wiring(tmp_path: Path, capsys) -> None:
    resolved_path = tmp_path / "resolved.json"
    connectivity_path = tmp_path / "connectivity.json"
    selection_path = tmp_path / "selection.json"
    output_path = tmp_path / "cohort-playable-v1.json"

    resolved_path.write_text(json.dumps(RESOLVED))
    connectivity_path.write_text(json.dumps(CONNECTIVITY))
    selection_path.write_text(json.dumps(SELECTION))

    main(
        [
            "promote-playable-cohort",
            "--resolved",
            str(resolved_path),
            "--connectivity",
            str(connectivity_path),
            "--selection",
            str(selection_path),
            "--cohort-id",
            "fake-digs-post",
            "--output",
            str(output_path),
        ]
    )
    capsys.readouterr()  # discard first command's output

    exit_code = main(["validate-playable-cohort", "--input", str(output_path)])
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True}


def test_draft_cohort_review_cli_wiring(tmp_path: Path, capsys) -> None:
    connectivity_path = tmp_path / "connectivity.json"
    output_path = tmp_path / "selection.template.json"
    connectivity_path.write_text(json.dumps(CONNECTIVITY))

    exit_code = main(
        [
            "draft-cohort-review",
            "--connectivity",
            str(connectivity_path),
            "--output",
            str(output_path),
        ]
    )
    assert exit_code == 0

    summary = json.loads(capsys.readouterr().out)
    assert summary["candidate_count"] == 1
    assert summary["clean_count"] == 1
    assert summary["flagged_count"] == 0

    template = json.loads(output_path.read_text())
    assert template["approved_pairs"] == []
    assert len(template["candidate_pairs"]) == 1
