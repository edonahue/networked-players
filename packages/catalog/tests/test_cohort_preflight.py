"""Tests for the read-only cohort pipeline preflight helper. Synthetic
tmp_path fixtures only -- never a real data/private/ or local/ path."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from networked_players_catalog.cli import main
from networked_players_catalog.cohort_preflight import (
    build_preflight_report,
    format_preflight_report,
)


def _make_dataset(root: Path) -> Path:
    root.mkdir(parents=True)
    (root / "manifest.json").write_text("{}")
    return root


def _ready_kwargs(tmp_path: Path) -> dict[str, Any]:
    source_html = tmp_path / "source.html"
    source_html.write_text("<html></html>")
    return {
        "source_id": "demo-source",
        "source_html": source_html,
        "parsed_dataset": _make_dataset(tmp_path / "parsed" / "snapshot=1"),
        "onehop_dataset": _make_dataset(tmp_path / "onehop" / "snapshot=1"),
        "source_url": "https://example.invalid/demo",
        "source_title": "Demo Title",
    }


def test_all_required_paths_present_is_ready(tmp_path: Path) -> None:
    report = build_preflight_report(**_ready_kwargs(tmp_path))
    assert report["ready"] is True
    assert all(check["present"] for check in report["required_checks"])


def test_missing_source_html_is_not_ready(tmp_path: Path) -> None:
    kwargs = _ready_kwargs(tmp_path)
    kwargs["source_html"] = tmp_path / "does-not-exist.html"
    report = build_preflight_report(**kwargs)
    assert report["ready"] is False
    by_name = {c["name"]: c["present"] for c in report["required_checks"]}
    assert by_name["source_html"] is False
    assert by_name["parsed_dataset"] is True
    assert by_name["onehop_dataset"] is True


def test_missing_parsed_dataset_directory_is_not_ready(tmp_path: Path) -> None:
    kwargs = _ready_kwargs(tmp_path)
    kwargs["parsed_dataset"] = tmp_path / "no-such-dataset"
    report = build_preflight_report(**kwargs)
    assert report["ready"] is False
    by_name = {c["name"]: c["present"] for c in report["required_checks"]}
    assert by_name["parsed_dataset"] is False


def test_parsed_dataset_without_manifest_is_not_ready(tmp_path: Path) -> None:
    kwargs = _ready_kwargs(tmp_path)
    bare_dir = tmp_path / "parsed-no-manifest"
    bare_dir.mkdir()
    kwargs["parsed_dataset"] = bare_dir
    report = build_preflight_report(**kwargs)
    assert report["ready"] is False
    by_name = {c["name"]: c["present"] for c in report["required_checks"]}
    assert by_name["parsed_dataset"] is False


def test_missing_onehop_dataset_is_not_ready(tmp_path: Path) -> None:
    kwargs = _ready_kwargs(tmp_path)
    kwargs["onehop_dataset"] = tmp_path / "no-such-onehop"
    report = build_preflight_report(**kwargs)
    assert report["ready"] is False
    by_name = {c["name"]: c["present"] for c in report["required_checks"]}
    assert by_name["onehop_dataset"] is False


def test_existing_outputs_warn_without_blocking_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    kwargs = _ready_kwargs(tmp_path)

    analysis_dir = tmp_path / "local" / "analysis" / "cohorts" / "demo-source"
    analysis_dir.mkdir(parents=True)
    (analysis_dir / "extracted.json").write_text("{}")
    (analysis_dir / "resolved.json").write_text("{}")
    (analysis_dir / "connectivity.json").write_text("{}")
    (analysis_dir / "playable-pairs.json").write_text("[]")
    (analysis_dir / "review-report.md").write_text("# report")

    review_dir = tmp_path / "data" / "private" / "cohort-review"
    review_dir.mkdir(parents=True)
    (review_dir / "demo-source-selection.template.json").write_text("{}")
    (review_dir / "demo-source-selection.json").write_text("{}")

    report = build_preflight_report(**kwargs)
    assert report["ready"] is True
    assert len(report["existing_outputs"]) == 7


def test_no_existing_outputs_reported_when_none_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    report = build_preflight_report(**_ready_kwargs(tmp_path))
    assert report["existing_outputs"] == []


def test_all_expected_commands_appear(tmp_path: Path) -> None:
    report = build_preflight_report(**_ready_kwargs(tmp_path))
    joined = "\n".join(report["commands"])
    for expected in (
        "import-cohort-source",
        "resolve-cohort",
        "score-cohort-connectivity",
        "draft-cohort-review",
        "Human review",
        "promote-playable-cohort",
        "validate-playable-cohort",
        "enqueue-cohort-check.sh",
    ):
        assert expected in joined, f"expected {expected!r} in commands output"


def test_source_url_and_title_are_safely_quoted(tmp_path: Path) -> None:
    kwargs = _ready_kwargs(tmp_path)
    kwargs["source_url"] = "https://example.invalid/some page?x=1"
    kwargs["source_title"] = "Some Title's Apostrophe"
    report = build_preflight_report(**kwargs)
    import_command = report["commands"][0]

    assert "https://example.invalid/some page?x=1" not in import_command.replace(
        "'https://example.invalid/some page?x=1'", ""
    )
    assert "'https://example.invalid/some page?x=1'" in import_command
    assert "Some Title" in import_command
    assert "'\"'\"'" in import_command  # shlex.quote's apostrophe-escaping signature


def test_json_report_round_trips(tmp_path: Path) -> None:
    report = build_preflight_report(**_ready_kwargs(tmp_path))
    round_tripped = json.loads(json.dumps(report))
    assert round_tripped == report


def test_format_preflight_report_mentions_readiness(tmp_path: Path) -> None:
    ready_dir = tmp_path / "ready"
    ready_dir.mkdir()
    ready_report = build_preflight_report(**_ready_kwargs(ready_dir))
    assert "READY" in format_preflight_report(ready_report)

    not_ready_dir = tmp_path / "not-ready"
    not_ready_dir.mkdir()
    kwargs = _ready_kwargs(not_ready_dir)
    kwargs["source_html"] = not_ready_dir / "missing.html"
    not_ready_report = build_preflight_report(**kwargs)
    assert "NOT READY" in format_preflight_report(not_ready_report)


# --- CLI wiring ---


def test_cli_help() -> None:
    # main() calls sys.exit via argparse for --help; just confirm it doesn't
    # crash with an unexpected exception by catching the expected SystemExit.
    try:
        main(["cohort-pipeline-preflight", "--help"])
    except SystemExit as exc:
        assert exc.code == 0


def test_cli_exits_zero_when_ready(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    kwargs = _ready_kwargs(tmp_path)
    exit_code = main(
        [
            "cohort-pipeline-preflight",
            "--source-id",
            str(kwargs["source_id"]),
            "--source-html",
            str(kwargs["source_html"]),
            "--parsed-dataset",
            str(kwargs["parsed_dataset"]),
            "--onehop-dataset",
            str(kwargs["onehop_dataset"]),
            "--source-url",
            str(kwargs["source_url"]),
            "--source-title",
            str(kwargs["source_title"]),
        ]
    )
    assert exit_code == 0
    assert "READY" in capsys.readouterr().out


def test_cli_exits_nonzero_when_not_ready(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    kwargs = _ready_kwargs(tmp_path)
    exit_code = main(
        [
            "cohort-pipeline-preflight",
            "--source-id",
            str(kwargs["source_id"]),
            "--source-html",
            str(tmp_path / "missing.html"),
            "--parsed-dataset",
            str(kwargs["parsed_dataset"]),
            "--onehop-dataset",
            str(kwargs["onehop_dataset"]),
            "--source-url",
            str(kwargs["source_url"]),
            "--source-title",
            str(kwargs["source_title"]),
        ]
    )
    assert exit_code == 1
    assert "NOT READY" in capsys.readouterr().out


def test_cli_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    kwargs = _ready_kwargs(tmp_path)
    exit_code = main(
        [
            "cohort-pipeline-preflight",
            "--source-id",
            str(kwargs["source_id"]),
            "--source-html",
            str(kwargs["source_html"]),
            "--parsed-dataset",
            str(kwargs["parsed_dataset"]),
            "--onehop-dataset",
            str(kwargs["onehop_dataset"]),
            "--source-url",
            str(kwargs["source_url"]),
            "--source-title",
            str(kwargs["source_title"]),
            "--json",
        ]
    )
    assert exit_code == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["ready"] is True


# --- memory_limit_preflight_failure (ADR 0033) ---


def _meminfo(tmp_path: Path, mem_available_kb: int) -> Path:
    path = tmp_path / "meminfo"
    path.write_text(
        f"MemTotal:       8000000 kB\nMemFree:        1000000 kB\n"
        f"MemAvailable:   {mem_available_kb} kB\n"
    )
    return path


def test_memory_preflight_refuses_limit_above_half_available(tmp_path: Path) -> None:
    from networked_players_catalog.cohort_preflight import memory_limit_preflight_failure

    # 6 GB available -> half is 3 GB; a 4 GB limit must be refused.
    meminfo = _meminfo(tmp_path, 6 * 1024 * 1024)
    failure = memory_limit_preflight_failure("4GB", meminfo_path=meminfo)
    assert failure is not None
    assert "4GB" in failure
    assert "swap-killed" in failure


def test_memory_preflight_allows_limit_within_half_available(tmp_path: Path) -> None:
    from networked_players_catalog.cohort_preflight import memory_limit_preflight_failure

    meminfo = _meminfo(tmp_path, 6 * 1024 * 1024)
    assert memory_limit_preflight_failure("3GB", meminfo_path=meminfo) is None
    assert memory_limit_preflight_failure("1GB", meminfo_path=meminfo) is None


def test_memory_preflight_never_blocks_on_unparseable_or_missing(tmp_path: Path) -> None:
    from networked_players_catalog.cohort_preflight import memory_limit_preflight_failure

    meminfo = _meminfo(tmp_path, 1 * 1024 * 1024)  # tiny, but limit syntax is unknown
    assert memory_limit_preflight_failure("lots", meminfo_path=meminfo) is None
    # Missing meminfo (e.g. non-Linux) never blocks.
    assert memory_limit_preflight_failure("4GB", meminfo_path=tmp_path / "nope") is None


def test_memory_preflight_parses_mib_and_gib(tmp_path: Path) -> None:
    from networked_players_catalog.cohort_preflight import memory_limit_preflight_failure

    meminfo = _meminfo(tmp_path, 2 * 1024 * 1024)  # 2 GB available, half = 1 GB
    assert memory_limit_preflight_failure("512MiB", meminfo_path=meminfo) is None
    assert memory_limit_preflight_failure("2GiB", meminfo_path=meminfo) is not None
