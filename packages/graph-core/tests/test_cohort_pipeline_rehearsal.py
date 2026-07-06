from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from networked_players_catalog.cli import main

SOURCE_ID = "synthetic-rehearsal"
SOURCE_URL = "https://example.invalid/synthetic-rehearsal"
SOURCE_TITLE = "Synthetic Rehearsal Fixture"


def _write_saved_source(tmp_path: Path) -> Path:
    source_html = tmp_path / "data" / "private" / "source-html" / f"{SOURCE_ID}.html"
    source_html.parent.mkdir(parents=True)
    source_html.write_text(
        """
        <html>
        <body>
          <h1>Synthetic Rehearsal Fixture</h1>
          <ol>
            <li>1. Alice - First Light (1993) <a href="/release/1">Discogs</a></li>
            <li>2. Cara - Second Set (1994) <a href="/release/2">Discogs</a></li>
            <li>3. Ghost Player - Missing Session (1995)</li>
          </ol>
        </body>
        </html>
        """
    )
    return source_html


def _run_json(
    args: list[str],
    capsys: pytest.CaptureFixture[str],
    *,
    allow_stderr: bool = False,
) -> dict[str, Any]:
    assert main(args) == 0
    captured = capsys.readouterr()
    if not allow_stderr:
        assert captured.err == ""
    return json.loads(captured.out)


def _status(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    return _run_json(["cohort-pipeline-status", "--source-id", SOURCE_ID, "--json"], capsys)


def _status_stage(report: dict[str, Any], name: str) -> dict[str, Any]:
    return next(stage for stage in report["stages"] if stage["name"] == name)


def test_synthetic_cohort_pipeline_rehearsal(
    dataset_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    source_html = _write_saved_source(tmp_path)
    analysis_dir = tmp_path / "local" / "analysis" / "cohorts" / SOURCE_ID
    review_dir = tmp_path / "data" / "private" / "cohort-review"
    promoted_artifact = tmp_path / "data" / "albums" / "cohorts" / f"{SOURCE_ID}-playable-v1.json"

    preflight = _run_json(
        [
            "cohort-pipeline-preflight",
            "--source-id",
            SOURCE_ID,
            "--source-html",
            str(source_html),
            "--parsed-dataset",
            str(dataset_root),
            "--onehop-dataset",
            str(dataset_root),
            "--source-url",
            SOURCE_URL,
            "--source-title",
            SOURCE_TITLE,
            "--json",
        ],
        capsys,
    )
    assert preflight["ready"] is True

    report = _status(capsys)
    assert report["current_checkpoint"] == "saved_source"
    assert "import-cohort-source" in report["next_action"]
    assert _status_stage(report, "saved_source")["present"] is True

    extracted_path = analysis_dir / "extracted.json"
    imported = _run_json(
        [
            "import-cohort-source",
            "--input",
            str(source_html),
            "--output",
            str(extracted_path),
            "--source-url",
            SOURCE_URL,
            "--source-title",
            SOURCE_TITLE,
            "--saved-at",
            "2026-07-06",
        ],
        capsys,
    )
    assert imported["candidate_count"] == 3
    assert extracted_path.exists()

    report = _status(capsys)
    assert report["current_checkpoint"] == "extracted"
    assert "resolve-cohort" in report["next_action"]

    resolved_path = analysis_dir / "resolved.json"
    resolved_summary = _run_json(
        [
            "resolve-cohort",
            "--extracted",
            str(extracted_path),
            "--dataset",
            str(dataset_root),
            "--output",
            str(resolved_path),
        ],
        capsys,
    )
    assert resolved_summary == {
        "output": str(resolved_path),
        "resolved_count": 2,
        "unresolved_count": 1,
    }
    resolved = json.loads(resolved_path.read_text())
    assert {album["artist_name"] for album in resolved["resolved"]} == {"Alice", "Cara"}

    report = _status(capsys)
    assert report["current_checkpoint"] == "resolved"
    assert "score-cohort-connectivity" in report["next_action"]

    scored = _run_json(
        [
            "score-cohort-connectivity",
            "--resolved",
            str(resolved_path),
            "--dataset",
            str(dataset_root),
            "--output-dir",
            str(analysis_dir),
        ],
        capsys,
    )
    assert scored["pair_count"] == 1
    assert scored["by_status"] == {"found": 1, "no_path": 0, "skipped": 0}
    connectivity_path = analysis_dir / "connectivity.json"
    playable_pairs_path = analysis_dir / "playable-pairs.json"
    review_report_path = analysis_dir / "review-report.md"
    assert connectivity_path.exists()
    assert playable_pairs_path.exists()
    assert review_report_path.exists()

    assert _run_json(["validate-connectivity", "--input", str(connectivity_path)], capsys) == {
        "ok": True
    }

    report = _status(capsys)
    assert report["current_checkpoint"] == "review_report"
    assert "draft-cohort-review" in report["next_action"]

    selection_template_path = review_dir / f"{SOURCE_ID}-selection.template.json"
    drafted = _run_json(
        [
            "draft-cohort-review",
            "--connectivity",
            str(connectivity_path),
            "--output",
            str(selection_template_path),
        ],
        capsys,
    )
    assert drafted["candidate_count"] == 1
    template = json.loads(selection_template_path.read_text())
    assert template["approved_pairs"] == []
    assert len(template["candidate_pairs"]) == 1

    report = _status(capsys)
    assert report["current_checkpoint"] == "selection_template"
    assert "human review" in report["next_action"].lower()

    approved = template["candidate_pairs"][0]
    selection_path = review_dir / f"{SOURCE_ID}-selection.json"
    selection_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "reviewed_by": "Synthetic Reviewer",
                "reviewed_at": "2026-07-06T00:00:00+00:00",
                "review_note": "Synthetic rehearsal selection.",
                "allow_flagged_pairs": False,
                "approved_pairs": [
                    {
                        "album_a_id": approved["album_a_id"],
                        "album_b_id": approved["album_b_id"],
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    report = _status(capsys)
    assert report["current_checkpoint"] == "selection"
    assert "promote-playable-cohort" in report["next_action"]

    promoted = _run_json(
        [
            "promote-playable-cohort",
            "--resolved",
            str(resolved_path),
            "--connectivity",
            str(connectivity_path),
            "--selection",
            str(selection_path),
            "--cohort-id",
            SOURCE_ID,
            "--output",
            str(promoted_artifact),
        ],
        capsys,
        allow_stderr=True,
    )
    assert promoted["pair_count"] == 1
    assert promoted_artifact.exists()
    assert _run_json(["validate-playable-cohort", "--input", str(promoted_artifact)], capsys) == {
        "ok": True
    }

    report = _status(capsys)
    assert report["pipeline_state"] == "promoted, not web-visible"
    assert report["current_checkpoint"] == "promoted_artifact"
    assert "future explicit PR" in report["next_action"]

    relative_files = {
        path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*") if path.is_file()
    }
    assert f"data/private/source-html/{SOURCE_ID}.html" in relative_files
    assert f"local/analysis/cohorts/{SOURCE_ID}/extracted.json" in relative_files
    assert f"local/analysis/cohorts/{SOURCE_ID}/resolved.json" in relative_files
    assert f"local/analysis/cohorts/{SOURCE_ID}/connectivity.json" in relative_files
    assert f"data/private/cohort-review/{SOURCE_ID}-selection.json" in relative_files
    assert f"data/albums/cohorts/{SOURCE_ID}-playable-v1.json" in relative_files
