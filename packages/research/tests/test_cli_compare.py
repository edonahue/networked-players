"""CLI wiring for `research-compare` -- proves the CLI reads the right
flags, writes a run under local/research/<topic>/runs/<run-id>/ exactly
like research-analyze, and reports a clear error for an unimplemented
mode. Full comparison-logic coverage lives in test_compare.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from networked_players_research.cli import main

from .test_compare import BOB, CAROL, SEED_A, SEED_B, _build_corpus


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

    request_path = run_root / "request.json"
    assert request_path.is_file()
    request = json.loads(request_path.read_text())
    assert request == {
        "mode": "albums",
        "corpus_snapshot_root": str(corpus),
        "album_a_release_id": 1,
        "album_b_release_id": 2,
        "max_hops": 4,
        "max_route_candidate_pairs": 200,
        "performer_only": True,
    }


def test_research_compare_rejects_an_unrecognized_mode(tmp_path: Path) -> None:
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
                "bands",  # not a real mode -- never will be
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


def test_research_compare_albums_requires_album_a_and_album_b(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    corpus = _build_corpus(tmp_path / "corpus_root")

    exit_code = main(
        [
            "research-compare",
            "--mode",
            "albums",
            "--corpus-root",
            str(corpus),
            "--topic",
            "alpha-vs-beta",
            "--research-root",
            str(tmp_path / "research"),
        ]
    )
    assert exit_code == 1
    assert "requires --album-a and --album-b" in capsys.readouterr().err


def test_research_compare_artists_writes_a_run_with_manifest_and_comparison(
    tmp_path: Path,
) -> None:
    corpus = _build_corpus(tmp_path / "corpus_root")
    research_root = tmp_path / "research"

    exit_code = main(
        [
            "research-compare",
            "--mode",
            "artists",
            "--corpus-root",
            str(corpus),
            "--artist-a",
            str(SEED_A),
            "--artist-b",
            str(SEED_B),
            "--topic",
            "seeda-vs-seedb",
            "--research-root",
            str(research_root),
        ]
    )
    assert exit_code == 0

    runs = list((research_root / "seeda-vs-seedb" / "runs").iterdir())
    assert len(runs) == 1
    run_root = runs[0]

    manifest = json.loads((run_root / "manifest.json").read_text())
    assert manifest["analyses"] == ["compare_artists"]

    comparison = json.loads((run_root / "comparison.json").read_text())
    assert comparison["artist_a"]["artist_id"] == SEED_A
    assert comparison["artist_b"]["artist_id"] == SEED_B
    assert CAROL in comparison["shared_collaborators"]["artist_ids"]

    request = json.loads((run_root / "request.json").read_text())
    assert request == {
        "mode": "artists",
        "corpus_snapshot_root": str(corpus),
        "artist_a_id": SEED_A,
        "artist_b_id": SEED_B,
        "max_hops": 4,
        "performer_only": True,
    }


def test_research_compare_artists_requires_artist_a_and_artist_b(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    corpus = _build_corpus(tmp_path / "corpus_root")

    exit_code = main(
        [
            "research-compare",
            "--mode",
            "artists",
            "--corpus-root",
            str(corpus),
            "--topic",
            "seeda-vs-seedb",
            "--research-root",
            str(tmp_path / "research"),
        ]
    )
    assert exit_code == 1
    assert "requires --artist-a and --artist-b" in capsys.readouterr().err


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


def test_research_compare_scenes_writes_a_run_with_manifest_and_comparison(
    tmp_path: Path,
) -> None:
    corpus = _build_corpus(tmp_path / "corpus_root")
    research_root = tmp_path / "research"

    exit_code = main(
        [
            "research-compare",
            "--mode",
            "scenes",
            "--corpus-root",
            str(corpus),
            "--scene-a",
            str(SEED_A),
            str(BOB),
            "--scene-b",
            str(SEED_B),
            "--topic",
            "scene-a-vs-scene-b",
            "--research-root",
            str(research_root),
        ]
    )
    assert exit_code == 0

    runs = list((research_root / "scene-a-vs-scene-b" / "runs").iterdir())
    assert len(runs) == 1
    run_root = runs[0]

    manifest = json.loads((run_root / "manifest.json").read_text())
    assert manifest["analyses"] == ["compare_scenes"]

    comparison = json.loads((run_root / "comparison.json").read_text())
    assert comparison["scene_a"]["member_artist_ids"] == [SEED_A, BOB]
    assert comparison["scene_a"]["resolved_artist_ids"] == [SEED_A, BOB]
    assert CAROL in comparison["shared_collaborators"]["artist_ids"]

    request = json.loads((run_root / "request.json").read_text())
    assert request == {
        "mode": "scenes",
        "corpus_snapshot_root": str(corpus),
        # tuple[int, ...] fields round-trip through JSON as plain lists --
        # JSON has no tuple type.
        "scene_a_artist_ids": [SEED_A, BOB],
        "scene_b_artist_ids": [SEED_B],
        "max_hops": 4,
        "max_route_candidate_pairs": 200,
        "performer_only": True,
    }


def test_research_compare_scenes_requires_scene_a_and_scene_b(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    corpus = _build_corpus(tmp_path / "corpus_root")

    exit_code = main(
        [
            "research-compare",
            "--mode",
            "scenes",
            "--corpus-root",
            str(corpus),
            "--topic",
            "scene-a-vs-scene-b",
            "--research-root",
            str(tmp_path / "research"),
        ]
    )
    assert exit_code == 1
    assert "requires --scene-a and --scene-b" in capsys.readouterr().err
