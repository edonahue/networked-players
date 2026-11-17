# ruff: noqa: E501
"""Atomic part writes, the progress record, and ``parse-releases --resume`` (Atlas I4).

All inputs are small synthetic dumps; crashes are simulated by raising a ``BaseException``
(which, like SIGKILL, skips the writer's ``except Exception`` cleanup) from the write path,
plus one real SIGKILL of a child process.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import textwrap
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

from networked_players_catalog import cli
from networked_players_catalog.discogs import parquet
from networked_players_catalog.discogs.manifest import DumpKind, build_manifest
from networked_players_catalog.discogs.parquet import parse_release_dump
from networked_players_catalog.discogs.resume import PROGRESS_FILENAME, ResumeRefused
from networked_players_catalog.discogs.validation import validate_dataset

SNAPSHOT = "20260501"
SOURCE_URL = "https://example.test/discogs_20260501_releases.xml.gz"
DUMP_NAME = f"discogs_{SNAPSHOT}_releases.xml.gz"


class SimulatedCrash(BaseException):
    """Stands in for SIGKILL / power loss: not an ``Exception``, so no cleanup runs."""


def _release_xml(release_id: int) -> str:
    return f"""
  <release id="{release_id}" status="Accepted">
    <artists><artist><id>{release_id % 7 + 10}</id><name>Artist {release_id % 7}</name></artist></artists>
    <title>Record {release_id}</title>
    <country>US</country>
    <released>2001</released>
    <extraartists>
      <artist><id>{release_id % 5 + 50}</id><name>Producer {release_id % 5}</name><role>Producer</role></artist>
      <artist><id>0</id><name>Unlinked {release_id}</name><role>Strings</role></artist>
    </extraartists>
    <tracklist>
      <track><position>A1</position><title>One {release_id}</title></track>
      <track><position>A2</position><title>Two {release_id}</title></track>
    </tracklist>
    <data_quality>Correct</data_quality>
  </release>"""


def make_dump(directory: Path, count: int = 7, *, first_id: int = 1000) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    body = "".join(_release_xml(first_id + i) for i in range(count))
    path = directory / DUMP_NAME
    with gzip.open(path, "wb") as handle:
        handle.write(f'<?xml version="1.0"?>\n<releases>{body}\n</releases>\n'.encode())
    return path


def run(
    dump: Path,
    out: Path,
    *,
    chunk: int = 2,
    resume: bool = False,
    max_releases: int | None = None,
    input_manifest: Path | None = None,
) -> dict[str, object]:
    return parse_release_dump(
        dump,
        out,
        snapshot_date=SNAPSHOT,
        source_url=SOURCE_URL,
        chunk_releases=chunk,
        max_releases=max_releases,
        resume=resume,
        input_manifest=input_manifest,
    )


def comparable(manifest: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in manifest.items() if key != "generated_at"}


def dataset_bytes(root: Path) -> dict[str, bytes]:
    final = root / f"snapshot={SNAPSHOT}"
    return {
        p.relative_to(final).as_posix(): p.read_bytes() for p in sorted(final.rglob("*.parquet"))
    }


def staging_dirs(root: Path) -> list[Path]:
    return sorted(root.glob(f".snapshot={SNAPSHOT}.tmp-*"))


def crash_on_replace(monkeypatch: pytest.MonkeyPatch, nth: int) -> None:
    """Raise after the nth part's bytes are fully written to the temp name, before rename."""
    real = parquet._replace_into_place
    calls = {"n": 0}

    def fake(tmp: Path, final: Path) -> None:
        calls["n"] += 1
        if calls["n"] == nth:
            raise SimulatedCrash
        real(tmp, final)

    monkeypatch.setattr(parquet, "_replace_into_place", fake)


@pytest.fixture
def reference(tmp_path: Path) -> tuple[Path, dict[str, object], dict[str, bytes]]:
    dump = make_dump(tmp_path / "raw")
    out = tmp_path / "reference"
    manifest = run(dump, out)
    return dump, manifest, dataset_bytes(out)


def interrupt(monkeypatch: pytest.MonkeyPatch, dump: Path, out: Path, nth: int) -> None:
    with monkeypatch.context() as patch:
        crash_on_replace(patch, nth)
        with pytest.raises(SimulatedCrash):
            run(dump, out)


# --- atomicity ---------------------------------------------------------------------


def test_crash_mid_part_leaves_no_torn_file_under_a_final_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    dump = make_dump(tmp_path / "raw")
    out = tmp_path / "out"
    interrupt(monkeypatch, dump, out, nth=5)

    (staging,) = staging_dirs(out)
    finals = sorted(staging.rglob("*.parquet"))
    assert finals, "earlier parts should have survived"
    for part in finals:
        assert pq.read_table(part).num_rows >= 0  # every final name is complete
    temps = [p for p in staging.rglob("*") if p.name.endswith(".tmp") and "table=" in str(p)]
    assert temps, "the interrupted part should exist only under its temp name"
    assert not (out / f"snapshot={SNAPSHOT}").exists()

    with caplog.at_level(logging.WARNING):
        run(dump, out, resume=True)
    assert any("deleting unrecorded file" in r.getMessage() for r in caplog.records)
    final = out / f"snapshot={SNAPSHOT}"
    assert not [p for p in final.rglob("*") if p.name.endswith(".tmp")]
    assert staging_dirs(out) == []


# --- resume equals uninterrupted --------------------------------------------------


# 7 releases / chunk 2 -> 4 parts x 3 tables = 12 part renames, then 1 empty-table part.
@pytest.mark.parametrize("nth", [1, 2, 5, 8, 12, 13])
def test_resume_equals_uninterrupted_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reference: tuple[Path, dict[str, object], dict[str, bytes]],
    nth: int,
) -> None:
    dump, ref_manifest, ref_bytes = reference
    out = tmp_path / "out"
    interrupt(monkeypatch, dump, out, nth)

    promotions: list[Path] = []
    real_promote = parquet._promote

    def counting_promote(staging: Path, final: Path) -> None:
        promotions.append(final)
        real_promote(staging, final)

    monkeypatch.setattr(parquet, "_promote", counting_promote)
    manifest = run(dump, out, resume=True)

    assert comparable(manifest) == comparable(ref_manifest)
    assert dataset_bytes(out) == ref_bytes  # byte-identical parts, not just logical equality
    assert promotions == [out / f"snapshot={SNAPSHOT}"]
    assert staging_dirs(out) == []
    on_disk = json.loads((out / f"snapshot={SNAPSHOT}" / "manifest.json").read_text())
    assert comparable(on_disk) == comparable(ref_manifest)
    assert not (out / f"snapshot={SNAPSHOT}" / PROGRESS_FILENAME).exists()
    metrics = validate_dataset(out / f"snapshot={SNAPSHOT}")  # DuckDB round trip
    assert metrics["release_rows"] == 7
    assert metrics["orphan_credits"] == 0


def test_crash_after_finalize_before_promotion_resumes_without_restreaming(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reference: tuple[Path, dict[str, object], dict[str, bytes]],
) -> None:
    dump, ref_manifest, ref_bytes = reference
    out = tmp_path / "out"
    with monkeypatch.context() as patch:

        def boom(staging: Path, final: Path) -> None:
            raise SimulatedCrash

        patch.setattr(parquet, "_promote", boom)
        with pytest.raises(SimulatedCrash):
            run(dump, out)
    (staging,) = staging_dirs(out)
    assert json.loads((staging / PROGRESS_FILENAME).read_text())["state"] == "finalized"

    def no_stream(*args: object, **kwargs: object) -> None:
        raise AssertionError("a finalized staging directory must not re-stream the dump")

    monkeypatch.setattr(parquet, "iter_releases", no_stream)
    manifest = run(dump, out, resume=True)
    assert comparable(manifest) == comparable(ref_manifest)
    assert dataset_bytes(out) == ref_bytes
    assert staging_dirs(out) == []


def test_finalized_resume_refuses_altered_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dump = make_dump(tmp_path / "raw")
    out = tmp_path / "out"
    with monkeypatch.context() as patch:
        patch.setattr(parquet, "_promote", lambda s, f: (_ for _ in ()).throw(SimulatedCrash()))
        with pytest.raises(SimulatedCrash):
            run(dump, out)
    (staging,) = staging_dirs(out)
    (staging / "manifest.json").write_text("{}\n")
    with pytest.raises(ResumeRefused, match=r"manifest\.json"):
        run(dump, out, resume=True)


def test_stream_position_is_recorded_and_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dump = make_dump(tmp_path / "raw")
    out = tmp_path / "out"
    interrupt(monkeypatch, dump, out, nth=8)
    (staging,) = staging_dirs(out)
    record = json.loads((staging / PROGRESS_FILENAME).read_text())
    assert record["releases_persisted"] == record["parts_completed"] * 2
    assert record["last_release_id"] == 1000 + record["releases_persisted"] - 1
    assert record["counts"]["releases"] == record["releases_persisted"]
    assert len(record["release_id_digest"]) == 64
    assert record["input"]["filename"] == DUMP_NAME
    for item in record["files"]:
        assert {"path", "size_bytes", "sha256", "rows"} <= set(item)


# --- bounded runs ------------------------------------------------------------------


def test_max_releases_still_bounds_and_resume_honours_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dump = make_dump(tmp_path / "raw")
    ref = run(dump, tmp_path / "ref", max_releases=5)
    assert ref["counts"]["releases"] == 5  # type: ignore[index]
    out = tmp_path / "out"
    with monkeypatch.context() as patch:
        crash_on_replace(patch, 5)
        with pytest.raises(SimulatedCrash):
            run(dump, out, max_releases=5)
    manifest = run(dump, out, resume=True, max_releases=5)
    assert comparable(manifest) == comparable(ref)
    assert dataset_bytes(out) == dataset_bytes(tmp_path / "ref")


def test_resume_with_different_max_releases_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dump = make_dump(tmp_path / "raw")
    out = tmp_path / "out"
    with monkeypatch.context() as patch:
        crash_on_replace(patch, 5)
        with pytest.raises(SimulatedCrash):
            run(dump, out, max_releases=5)
    with pytest.raises(ResumeRefused, match="max_releases"):
        run(dump, out, resume=True, max_releases=6)
    with pytest.raises(ResumeRefused, match="max_releases"):
        run(dump, out, resume=True)


# --- refusals ----------------------------------------------------------------------


def _interrupted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    dump = make_dump(tmp_path / "raw")
    out = tmp_path / "out"
    interrupt(monkeypatch, dump, out, nth=8)
    (staging,) = staging_dirs(out)
    return dump, out, staging


def test_non_resume_start_refuses_existing_staging_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dump, out, staging = _interrupted(tmp_path, monkeypatch)
    with pytest.raises(FileExistsError, match="--resume") as excinfo:
        run(dump, out)
    assert "check_ingest_recovery" in str(excinfo.value)
    assert staging.is_dir()  # untouched


def test_refuses_when_no_staging_dir(tmp_path: Path) -> None:
    dump = make_dump(tmp_path / "raw")
    (tmp_path / "out").mkdir()
    with pytest.raises(ResumeRefused, match="nothing to resume"):
        run(dump, tmp_path / "out", resume=True)


def test_refuses_when_two_staging_dirs_and_names_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dump, out, staging = _interrupted(tmp_path, monkeypatch)
    twin = out / f".snapshot={SNAPSHOT}.tmp-deadbeef"
    shutil.copytree(staging, twin)
    with pytest.raises(ResumeRefused, match="ambiguous") as excinfo:
        run(dump, out, resume=True)
    assert staging.name in str(excinfo.value) and twin.name in str(excinfo.value)


def test_refuses_missing_progress_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dump, out, staging = _interrupted(tmp_path, monkeypatch)
    (staging / PROGRESS_FILENAME).unlink()
    with pytest.raises(ResumeRefused, match=PROGRESS_FILENAME):
        run(dump, out, resume=True)
    assert staging.is_dir()


@pytest.mark.parametrize("content", ["{not json", "[]", '{"progress_version": 1}'])
def test_refuses_corrupt_progress_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str
) -> None:
    dump, out, staging = _interrupted(tmp_path, monkeypatch)
    (staging / PROGRESS_FILENAME).write_text(content)
    with pytest.raises(ResumeRefused, match="corrupt"):
        run(dump, out, resume=True)
    assert staging.is_dir()


def test_refuses_altered_recorded_part(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dump, out, staging = _interrupted(tmp_path, monkeypatch)
    victim = staging / "table=releases" / "part-00000.parquet"
    data = bytearray(victim.read_bytes())
    data[len(data) // 2] ^= 0xFF  # same size, different content
    victim.write_bytes(bytes(data))
    with pytest.raises(ResumeRefused, match="sha256"):
        run(dump, out, resume=True)
    assert staging.is_dir()


def test_refuses_missing_recorded_part(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dump, out, staging = _interrupted(tmp_path, monkeypatch)
    (staging / "table=releases" / "part-00000.parquet").unlink()
    with pytest.raises(ResumeRefused, match="missing"):
        run(dump, out, resume=True)


def test_refuses_different_input_same_size_via_stream_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dump, out, staging = _interrupted(tmp_path, monkeypatch)
    # Same filename; record the swapped file's size so only the stream-prefix digest can
    # tell the inputs apart.
    target = tmp_path / "swap" / DUMP_NAME
    target.parent.mkdir()
    raw = gzip.decompress(dump.read_bytes()).replace(b'id="1001"', b'id="1009"')
    target.write_bytes(gzip.compress(raw))
    record_path = staging / PROGRESS_FILENAME
    record = json.loads(record_path.read_text())
    record["input"]["size_bytes"] = target.stat().st_size
    record_path.write_text(json.dumps(record))
    with pytest.raises(ResumeRefused, match="different or modified dump"):
        run(target, out, resume=True)
    assert staging.is_dir()


def test_refuses_input_with_different_size(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, out, staging = _interrupted(tmp_path, monkeypatch)
    other = make_dump(tmp_path / "other", count=9)
    with pytest.raises(ResumeRefused, match="input differs"):
        run(other, out, resume=True)
    assert staging.is_dir()


def test_refuses_input_shorter_than_recorded_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _dump, out, staging = _interrupted(tmp_path, monkeypatch)
    record_path = staging / PROGRESS_FILENAME
    short = make_dump(tmp_path / "short", count=2)
    record = json.loads(record_path.read_text())
    record["input"]["size_bytes"] = short.stat().st_size
    record_path.write_text(json.dumps(record))
    with pytest.raises(ResumeRefused, match="only 2 releases"):
        run(short, out, resume=True)
    assert staging.is_dir()


def test_refuses_input_manifest_sha_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dump = make_dump(tmp_path / "raw")
    out = tmp_path / "out"

    def manifest_with(sha: str) -> Path:
        manifest = build_manifest(SNAPSHOT, "2026-01-01")
        item = manifest.object_for(DumpKind.RELEASES)
        item.sha256 = sha
        item.size_bytes = dump.stat().st_size
        path = tmp_path / f"manifest-{sha[:4]}.json"
        manifest.write(path)
        return path

    with monkeypatch.context() as patch:
        crash_on_replace(patch, 5)
        with pytest.raises(SimulatedCrash):
            run(dump, out, input_manifest=manifest_with("a" * 64))
    (staging,) = staging_dirs(out)
    record = json.loads((staging / PROGRESS_FILENAME).read_text())
    assert record["input"]["sha256"] == "a" * 64
    assert record["input"]["sha256_source"] == "download_manifest"
    with pytest.raises(ResumeRefused, match="sha256"):
        run(dump, out, resume=True, input_manifest=manifest_with("b" * 64))
    assert run(dump, out, resume=True, input_manifest=manifest_with("a" * 64))["counts"]


def test_refuses_parameter_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dump, out, staging = _interrupted(tmp_path, monkeypatch)
    with pytest.raises(ResumeRefused, match="chunk_releases"):
        run(dump, out, resume=True, chunk=3)
    assert staging.is_dir()


# --- failure behaviour unchanged ---------------------------------------------------


def test_malformed_input_still_cleans_up_staging(tmp_path: Path) -> None:
    bad = tmp_path / "raw" / DUMP_NAME
    bad.parent.mkdir()
    good = gzip.decompress(make_dump(tmp_path / "good").read_bytes())
    bad.write_bytes(gzip.compress(good[: len(good) // 2]))  # torn XML
    out = tmp_path / "out"
    with pytest.raises(Exception):  # noqa: B017 - lxml syntax error type
        run(bad, out)
    assert staging_dirs(out) == []
    assert not (out / f"snapshot={SNAPSHOT}").exists()


def test_refusal_does_not_delete_staging_but_ordinary_failure_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dump, out, staging = _interrupted(tmp_path, monkeypatch)
    # A resume that hits malformed input behaves like any failed run (staging removed).
    torn = tmp_path / "torn" / DUMP_NAME
    torn.parent.mkdir()
    raw = gzip.decompress(dump.read_bytes())
    torn.write_bytes(gzip.compress(raw[: len(raw) - 400]))
    record_path = staging / PROGRESS_FILENAME
    record = json.loads(record_path.read_text())
    record["input"]["size_bytes"] = torn.stat().st_size
    record_path.write_text(json.dumps(record))
    with pytest.raises(Exception):  # noqa: B017
        run(torn, out, resume=True)
    assert staging_dirs(out) == []


# --- CLI ---------------------------------------------------------------------------


def _cli_args(dump: Path, out: Path, *extra: str) -> list[str]:
    return [
        "parse-releases",
        "--input",
        str(dump),
        "--snapshot",
        SNAPSHOT,
        "--source-url",
        SOURCE_URL,
        "--output-root",
        str(out),
        "--chunk-releases",
        "2",
        *extra,
    ]


def test_cli_resume_and_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    reference: tuple[Path, dict[str, object], dict[str, bytes]],
) -> None:
    dump, ref_manifest, _ = reference
    out = tmp_path / "out"
    assert cli.main(_cli_args(dump, out, "--resume")) == 2
    assert "nothing to resume" in capsys.readouterr().err
    interrupt(monkeypatch, dump, out, nth=8)
    assert cli.main(_cli_args(dump, out, "--resume")) == 0
    printed = json.loads(capsys.readouterr().out)
    assert comparable(printed) == comparable(ref_manifest)


# --- real SIGKILL ------------------------------------------------------------------

CHILD = textwrap.dedent(
    """
    import pathlib, sys, time
    from networked_players_catalog import cli
    from networked_players_catalog.discogs import parquet

    marker, keep = pathlib.Path(sys.argv[1]), int(sys.argv[2])
    real = parquet.iter_releases

    def stalling(*args, **kwargs):
        for index, record in enumerate(real(*args, **kwargs)):
            yield record
            if index + 1 == keep:
                marker.write_text("stalled")
                time.sleep(600)

    parquet.iter_releases = stalling
    sys.exit(cli.main(sys.argv[3:]))
    """
)


@pytest.mark.skipif(not hasattr(signal, "SIGKILL"), reason="needs POSIX SIGKILL")
def test_sigkill_of_a_real_process_then_resume(
    tmp_path: Path, reference: tuple[Path, dict[str, object], dict[str, bytes]]
) -> None:
    dump, ref_manifest, ref_bytes = reference
    out = tmp_path / "out"
    marker = tmp_path / "marker"
    script = tmp_path / "child.py"
    script.write_text(CHILD)
    child = subprocess.Popen(
        [sys.executable, str(script), str(marker), "5", *_cli_args(dump, out)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_for(lambda: marker.exists(), "child never reached the stall point")
        # The in-flight part (index 1) is fully written by the background thread but not yet
        # recorded; wait for it so the kill lands with committed + uncommitted parts on disk.
        wait_for(
            lambda: any(out.glob(".snapshot=*/table=releases/part-00001.parquet")),
            "in-flight part never appeared",
        )
    finally:
        os.kill(child.pid, signal.SIGKILL)
        child.wait(timeout=30)
    assert child.returncode == -signal.SIGKILL
    (staging,) = staging_dirs(out)
    assert json.loads((staging / PROGRESS_FILENAME).read_text())["parts_completed"] == 1

    manifest = run(dump, out, resume=True)
    assert comparable(manifest) == comparable(ref_manifest)
    assert dataset_bytes(out) == ref_bytes
    assert staging_dirs(out) == []


def _recovery_module() -> Any:
    import importlib.util

    path = Path(__file__).resolve().parents[3] / "scripts" / "check_ingest_recovery.py"
    spec = importlib.util.spec_from_file_location("check_ingest_recovery", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_recovery_report_recommends_resume_only_when_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, out, staging = _interrupted(tmp_path, monkeypatch)
    report = _recovery_module().check_recovery(SNAPSHOT, out, 2)
    assert report["resume_safe"] is True
    assert "--resume" in report["recommendation"]
    assert report["releases_persisted"] == report["parts_completed"] * 2
    assert report["unrecorded_files_resume_will_delete"]  # the torn temp file

    victim = staging / "table=releases" / "part-00000.parquet"
    victim.write_bytes(victim.read_bytes()[:-5])
    report = _recovery_module().check_recovery(SNAPSHOT, out, 2)
    assert report["resume_safe"] is False
    assert report["recorded_part_problems"] == ["altered: table=releases/part-00000.parquet"]


def wait_for(predicate: Callable[[], bool], message: str, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError(message)
