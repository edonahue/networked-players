"""Tests for the read-only cohort pipeline status helper.

Synthetic tmp_path fixtures only -- never a real data/private/ or local/ path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from networked_players_catalog.cli import main
from networked_players_catalog.cohort_status import build_status_report, format_status_report


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _source_html(tmp_path: Path, source_id: str) -> Path:
    return _write(
        tmp_path / "data" / "private" / "source-html" / f"{source_id}.html",
        "<html></html>",
    )


def _stage_core_pipeline(tmp_path: Path, source_id: str) -> dict[str, Path]:
    analysis_dir = tmp_path / "local" / "analysis" / "cohorts" / source_id
    review_dir = tmp_path / "data" / "private" / "cohort-review"
    promoted_artifact = tmp_path / "data" / "albums" / "cohorts" / f"{source_id}-playable-v1.json"

    files = {
        "source_html": _source_html(tmp_path, source_id),
        "extracted": _write(analysis_dir / "extracted.json", "{}"),
        "resolved": _write(analysis_dir / "resolved.json", "{}"),
        "connectivity": _write(analysis_dir / "connectivity.json", "{}"),
        "playable_pairs": _write(analysis_dir / "playable-pairs.json", "[]"),
        "review_report": _write(analysis_dir / "review-report.md", "# report"),
        "selection_template": _write(review_dir / f"{source_id}-selection.template.json", "{}"),
        "selection": _write(review_dir / f"{source_id}-selection.json", "{}"),
        "promoted_artifact": _write(promoted_artifact, "{}"),
        "analysis_dir": analysis_dir,
    }
    return files


def test_empty_state_reports_first_missing_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    report = build_status_report(source_id="demo-source")

    assert report["pipeline_state"] == "in progress"
    assert report["current_checkpoint"] == "none"
    assert "Save the source HTML" in report["next_action"]
    assert report["stages"][0]["present"] is False
    assert report["stages"][0]["path"] == "data/private/source-html/demo-source.html"
    assert report["warnings"] == []
    assert "Stages:" in format_status_report(report)


def test_progression_stops_at_manual_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    source_id = "demo-source"
    _source_html(tmp_path, source_id)
    analysis_dir = tmp_path / "local" / "analysis" / "cohorts" / source_id
    review_dir = tmp_path / "data" / "private" / "cohort-review"
    _write(analysis_dir / "extracted.json", "{}")
    _write(analysis_dir / "resolved.json", "{}")
    _write(analysis_dir / "connectivity.json", "{}")
    _write(analysis_dir / "playable-pairs.json", "[]")
    _write(analysis_dir / "review-report.md", "# report")
    _write(review_dir / f"{source_id}-selection.template.json", "{}")

    report = build_status_report(source_id=source_id)

    assert report["current_checkpoint"] == "selection_template"
    assert "Perform the human review step" in report["next_action"]
    assert report["warnings"] == []


def test_web_visibility_is_reported_without_requiring_dist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    source_id = "demo-source"
    files = _stage_core_pipeline(tmp_path, source_id)

    manifest = {
        "schema_version": 1,
        "cohorts": [
            {
                "cohort_id": source_id,
                "title": "Demo Cohort",
                "description": "Synthetic reviewed entry.",
                "artifact_path": f"/data/cohorts/{source_id}-playable-v1.json",
                "status": "reviewed",
            }
        ],
    }
    _write(
        tmp_path / "apps" / "web" / "public" / "data" / "cohorts" / "index.json",
        json.dumps(manifest),
    )
    _write(
        tmp_path / "apps" / "web" / "src" / "data" / "cohortArtifacts.ts",
        f'export const cohortArtifacts = {{ "{source_id}": {{}} }};\n',
    )

    report = build_status_report(source_id=source_id)

    assert report["pipeline_state"] == "web-visible"
    assert report["current_checkpoint"] == "web-visible"
    assert "final review and deploy" in report["next_action"].lower()
    assert report["web_visibility"]["manifest_entry"]["present"] is True
    assert report["web_visibility"]["import_map_entry"]["present"] is True
    assert report["web_visibility"]["generated_route"]["present"] is None
    assert report["warnings"] == []
    assert files["promoted_artifact"].read_text() == "{}"


def test_import_map_before_manifest_warns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    source_id = "demo-source"
    _stage_core_pipeline(tmp_path, source_id)
    _write(
        tmp_path / "apps" / "web" / "src" / "data" / "cohortArtifacts.ts",
        f'export const cohortArtifacts = {{ "{source_id}": {{}} }};\n',
    )

    report = build_status_report(source_id=source_id)

    assert any("import map" in warning for warning in report["warnings"])
    assert report["pipeline_state"] == "promoted, not web-visible"
    assert (
        "web-visible" not in report["next_action"].lower()
        or "future explicit PR" in report["next_action"]
    )


def test_cli_json_output_is_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    source_id = "demo-source"
    _stage_core_pipeline(tmp_path, source_id)
    _write(
        tmp_path / "apps" / "web" / "public" / "data" / "cohorts" / "index.json",
        json.dumps(
            {
                "schema_version": 1,
                "cohorts": [
                    {
                        "cohort_id": source_id,
                        "title": "Demo Cohort",
                        "description": "Synthetic reviewed entry.",
                        "artifact_path": f"/data/cohorts/{source_id}-playable-v1.json",
                        "status": "reviewed",
                    }
                ],
            }
        ),
    )
    _write(
        tmp_path / "apps" / "web" / "src" / "data" / "cohortArtifacts.ts",
        f'export const cohortArtifacts = {{ "{source_id}": {{}} }};\n',
    )

    before = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    exit_code = main(["cohort-pipeline-status", "--source-id", source_id, "--json"])
    after = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))

    assert exit_code == 0
    assert before == after
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["source_id"] == source_id
    assert parsed["pipeline_state"] == "web-visible"
    assert parsed["pi_check"] is None
