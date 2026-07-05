"""Tests for the import-cohort-source CLI subcommand."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from networked_players_catalog.cli import main
from networked_players_catalog.cohort_source.validation import validate_extracted_candidates

FIXTURE = Path(__file__).parents[3] / "data" / "samples" / "cohort-source-sample.html"


def test_cli_import_cohort_source_writes_extracted_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output_path = tmp_path / "extracted.json"

    exit_code = main(
        [
            "import-cohort-source",
            "--input",
            str(FIXTURE),
            "--output",
            str(output_path),
            "--source-url",
            "https://example.invalid/fake-digs-post",
            "--source-title",
            "Fake Digs Post",
            "--saved-at",
            "2026-07-05",
        ]
    )
    assert exit_code == 0

    printed = json.loads(capsys.readouterr().out)
    assert printed["candidate_count"] == 4
    # Entries 3 and 4 each accumulate >=2 warnings (missing link/year/separator).
    assert printed["low_confidence_count"] == 2
    assert printed["missing_link_count"] == 2

    artifact = json.loads(output_path.read_text())
    validate_extracted_candidates(artifact)


def test_cli_import_cohort_source_never_embeds_local_input_path(tmp_path: Path) -> None:
    output_path = tmp_path / "extracted.json"

    main(
        [
            "import-cohort-source",
            "--input",
            str(FIXTURE),
            "--output",
            str(output_path),
            "--source-url",
            "https://example.invalid/fake-digs-post",
            "--source-title",
            "Fake Digs Post",
            "--saved-at",
            "2026-07-05",
        ]
    )

    serialized = output_path.read_text()
    assert str(tmp_path) not in serialized
    assert str(FIXTURE.parent) not in serialized
