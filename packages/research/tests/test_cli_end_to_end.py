"""The Slice A end-to-end fixture proof: request.json -> corpus -> analysis
-> report -> findings.json, all real code running against a small
synthetic dataset (never real data) -- proves the pipeline shape works
before any real Discogs data is touched, per the Phase 3 plan."""

from __future__ import annotations

import json
from pathlib import Path

from networked_players_research.cli import main


def _write_request(path: Path, *, topic: str = "Jane", seed: str = "Jane") -> Path:
    path.write_text(
        json.dumps(
            {
                "topic": topic,
                "seeds": {"artists": [seed]},
                "questions": ["How did personnel change across Jane's releases?"],
                "scope": {"hop_tier": 1},
                "analyses": ["personnel_timeline"],
            }
        )
    )
    return path


def test_research_run_produces_every_expected_output_file(
    dataset_root: Path, tmp_path: Path
) -> None:
    config_path = _write_request(tmp_path / "request.json")
    research_root = tmp_path / "research"

    exit_code = main(
        [
            "research-run",
            "--config",
            str(config_path),
            "--dataset",
            str(dataset_root),
            "--research-root",
            str(research_root),
        ]
    )
    assert exit_code == 0

    runs = list((research_root / "jane" / "runs").iterdir())
    assert len(runs) == 1
    run_root = runs[0]

    assert (run_root / "request.json").is_file()
    assert (run_root / "manifest.json").is_file()
    assert (run_root / "analysis" / "personnel_timeline.json").is_file()
    assert (run_root / "report" / "index.md").is_file()
    assert (run_root / "findings.json").is_file()
    assert (run_root / "promotion_candidates.json").is_file()

    manifest = json.loads((run_root / "manifest.json").read_text())
    assert manifest["topic"] == "Jane"
    assert manifest["analyses"] == ["personnel_timeline"]
    assert manifest["corpus_version"].startswith("research-corpus-v1-")

    findings = json.loads((run_root / "findings.json").read_text())
    assert findings["findings"][0]["kind"] == "fact"
    assert findings["findings"][0]["data"]["release_count"] == 2

    report_text = (run_root / "report" / "index.md").read_text()
    assert "Jane's First Album" in report_text
    assert "Jane's Second Album" in report_text

    # The corpus is written under local/research/<topic>/corpus/, never
    # anywhere apps/web/public/** could ever serve it.
    corpus_snapshot = research_root / "jane" / "corpus" / "snapshot=20260601"
    assert corpus_snapshot.is_dir()


def test_research_run_fails_loud_on_an_unresolvable_seed(
    dataset_root: Path, tmp_path: Path
) -> None:
    config_path = _write_request(tmp_path / "request.json", seed="Nobody")
    exit_code = main(
        [
            "research-run",
            "--config",
            str(config_path),
            "--dataset",
            str(dataset_root),
            "--research-root",
            str(tmp_path / "research"),
        ]
    )
    assert exit_code == 1


def test_granular_subcommands_compose_to_the_same_result(
    dataset_root: Path, tmp_path: Path
) -> None:
    config_path = _write_request(tmp_path / "request.json")
    research_root = tmp_path / "research"

    assert (
        main(
            [
                "research-build-corpus",
                "--config",
                str(config_path),
                "--dataset",
                str(dataset_root),
                "--research-root",
                str(research_root),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "research-analyze",
                "--config",
                str(config_path),
                "--research-root",
                str(research_root),
                "--run-id",
                "20260804T000000Z",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "research-report",
                "--config",
                str(config_path),
                "--research-root",
                str(research_root),
                "--run-id",
                "20260804T000000Z",
            ]
        )
        == 0
    )

    run_root = research_root / "jane" / "runs" / "20260804T000000Z"
    assert (run_root / "findings.json").is_file()
    assert (run_root / "report" / "index.md").is_file()
