"""CLI wiring for `research-compare` -- proves the CLI reads the right
flags, writes a run under local/research/<topic>/runs/<run-id>/ exactly
like research-analyze, and reports a clear error for an unimplemented
mode. Full comparison-logic coverage lives in test_compare.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from networked_players_research.cli import main

from .test_compare import CAROL, _build_corpus


def test_research_compare_albums_writes_a_run_with_manifest_and_comparison(
    tmp_path: Path,
) -> None:
    corpus = _build_corpus(tmp_path / "corpus_root")
    research_root = tmp_path / "research"

    exit_code = main(
        [
            "research-compare",
            "--mode",
            "albums",
            "--corpus-root",
            str(corpus),
            "--album-a",
            "1",
            "--album-b",
            "2",
            "--topic",
            "alpha-vs-beta",
            "--research-root",
            str(research_root),
        ]
    )
    assert exit_code == 0

    runs = list((research_root / "alpha-vs-beta" / "runs").iterdir())
    assert len(runs) == 1
    run_root = runs[0]

    assert (run_root / "manifest.json").is_file()
    manifest = json.loads((run_root / "manifest.json").read_text())
    assert manifest["topic"] == "alpha-vs-beta"
    assert manifest["analyses"] == ["compare_albums"]
    assert manifest["corpus_version"].startswith("snapshot=20260601:")

    comparison_path = run_root / "comparison.json"
    assert comparison_path.is_file()
    comparison = json.loads(comparison_path.read_text())
    shared_ids = {p["artist_id"] for p in comparison["shared_vs_unique"]["recurring_personnel"]}
    assert shared_ids == {CAROL}
    assert comparison["album_a"]["release_id"] == 1
    assert comparison["album_b"]["release_id"] == 2


def test_research_compare_rejects_an_unimplemented_mode(tmp_path: Path) -> None:
    # argparse's own `choices=` validation, not compare.py's -- fails before
    # any corpus is even touched, matching every other unrecognized-name
    # error in this repo being a hard, immediate error (request.py's
    # ANALYSIS_NAMES, e.g.), never silently ignored or guessed past.
    corpus = _build_corpus(tmp_path / "corpus_root")

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "research-compare",
                "--mode",
                "artists",
                "--corpus-root",
                str(corpus),
                "--album-a",
                "1",
                "--album-b",
                "2",
                "--topic",
                "alpha-vs-beta",
                "--research-root",
                str(tmp_path / "research"),
            ]
        )
    assert exc_info.value.code == 2


def test_research_compare_reports_a_clear_error_for_an_unresolvable_release(
    tmp_path: Path,
) -> None:
    corpus = _build_corpus(tmp_path / "corpus_root")

    exit_code = main(
        [
            "research-compare",
            "--mode",
            "albums",
            "--corpus-root",
            str(corpus),
            "--album-a",
            "1",
            "--album-b",
            "999999",
            "--topic",
            "alpha-vs-nothing",
            "--research-root",
            str(tmp_path / "research"),
        ]
    )
    assert exit_code == 1
