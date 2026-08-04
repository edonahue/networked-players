from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from networked_players_research.runs import (
    RunPaths,
    corpus_root,
    new_run_id,
    new_run_paths,
    runs_root,
    topic_root,
    write_run_manifest,
)


def test_topic_and_corpus_and_runs_roots_nest_under_the_topic() -> None:
    research_root = Path("local/research")
    assert topic_root("jamiroquai", research_root=research_root) == Path(
        "local/research/jamiroquai"
    )
    assert corpus_root("jamiroquai", research_root=research_root) == Path(
        "local/research/jamiroquai/corpus"
    )
    assert runs_root("jamiroquai", research_root=research_root) == Path(
        "local/research/jamiroquai/runs"
    )


def test_new_run_id_is_a_sortable_utc_timestamp() -> None:
    moment = datetime(2026, 8, 4, 12, 30, 45, tzinfo=UTC)
    assert new_run_id(moment) == "20260804T123045Z"


def test_new_run_id_defaults_to_now() -> None:
    run_id = new_run_id()
    assert re.fullmatch(r"\d{8}T\d{6}Z", run_id)


def test_run_paths_nest_correctly(tmp_path: Path) -> None:
    paths = new_run_paths("jamiroquai", "20260804T000000Z", research_root=tmp_path)
    assert paths.root == tmp_path / "jamiroquai" / "runs" / "20260804T000000Z"
    assert paths.request_path == paths.root / "request.json"
    assert paths.findings_path == paths.root / "findings.json"
    assert paths.analysis_dir == paths.root / "analysis"
    assert paths.report_dir == paths.root / "report"


def test_ensure_dirs_creates_analysis_and_report(tmp_path: Path) -> None:
    paths = RunPaths(root=tmp_path / "run")
    paths.ensure_dirs()
    assert paths.analysis_dir.is_dir()
    assert paths.report_dir.is_dir()


def test_write_run_manifest_records_provenance(tmp_path: Path) -> None:
    paths = RunPaths(root=tmp_path / "run")
    paths.root.mkdir(parents=True)
    manifest = write_run_manifest(
        paths,
        topic="Jamiroquai",
        run_id="20260804T000000Z",
        corpus_version="research-corpus-v1-20260601-abc123",
        analyses=["personnel_timeline"],
        started_at="2026-08-04T00:00:00+00:00",
        finished_at="2026-08-04T00:00:05+00:00",
    )
    assert manifest["topic"] == "Jamiroquai"
    assert manifest["corpus_version"] == "research-corpus-v1-20260601-abc123"
    assert manifest["analyses"] == ["personnel_timeline"]
    assert paths.manifest_path.is_file()
