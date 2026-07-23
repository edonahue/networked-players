"""Tests for scripts/_artifact_staging.py -- the stage/verify/cleanup flow
`enqueue_cohort_check.py` uses to put an ad hoc, per-invocation artifact
onto every targeted Pi worker before a check job can read it. Mocks
`subprocess.run` (mirrors scripts/tests/test_fleet_check.py's
`run_burst_workers` test) -- no real Ansible, no real hardware.

Loads scripts/_artifact_staging.py via importlib.util.spec_from_file_location,
same pattern as test_fleet_check.py.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

STAGING_PATH = Path(__file__).resolve().parents[1] / "_artifact_staging.py"


@pytest.fixture
def staging():
    spec = importlib.util.spec_from_file_location("_artifact_staging", STAGING_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_artifact_staging"] = module
    spec.loader.exec_module(module)
    yield module
    del sys.modules["_artifact_staging"]


# --- validate_local_artifact ---------------------------------------------


def test_validate_local_artifact_aborts_if_source_is_missing(staging, tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        staging.validate_local_artifact(tmp_path / "does-not-exist.json")


def test_validate_local_artifact_aborts_if_source_is_a_directory(staging, tmp_path: Path) -> None:
    directory = tmp_path / "a-directory"
    directory.mkdir()
    with pytest.raises(SystemExit):
        staging.validate_local_artifact(directory)


def test_validate_local_artifact_aborts_on_malformed_json(staging, tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not valid json")
    with pytest.raises(SystemExit):
        staging.validate_local_artifact(path)


def test_validate_local_artifact_accepts_a_real_json_file(staging, tmp_path: Path) -> None:
    path = tmp_path / "connectivity.json"
    path.write_text(json.dumps({"ok": True}))
    staging.validate_local_artifact(path)  # does not raise


# --- local_sha256 / remote_filename_for -----------------------------------


def test_local_sha256_matches_a_known_vector(staging, tmp_path: Path) -> None:
    path = tmp_path / "hello.txt"
    path.write_bytes(b"hello world")
    assert staging.local_sha256(path) == hashlib.sha256(b"hello world").hexdigest()


def test_remote_filename_is_deterministic_and_content_addressed(staging) -> None:
    assert staging.remote_filename_for("abc123") == "cohort-input-abc123.json"


def test_stage_artifact_uses_the_same_remote_filename_for_every_host(
    staging, tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "connectivity.json"
    path.write_text(json.dumps({"ok": True}))
    expected_sha256 = staging.local_sha256(path)

    calls: list[list[str]] = []
    monkeypatch.setattr(staging.subprocess, "run", lambda cmd, check: calls.append(cmd))

    filename = staging.stage_artifact(path, ["worker-01", "worker-02", "worker-03"])

    assert filename == f"cohort-input-{expected_sha256}.json"
    assert len(calls) == 1  # one playbook run covering every host, not one per host
    cmd = calls[0]
    assert "--limit" in cmd
    assert cmd[cmd.index("--limit") + 1] == "worker-01,worker-02,worker-03"
    assert f"remote_filename={filename}" in cmd
    assert f"expected_sha256={expected_sha256}" in cmd
    assert "stage_action=stage" in cmd


def test_stage_artifact_propagates_a_checksum_or_ansible_failure(
    staging, tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "connectivity.json"
    path.write_text(json.dumps({"ok": True}))

    def _raise(cmd, check):
        raise staging.subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(staging.subprocess, "run", _raise)

    with pytest.raises(staging.subprocess.CalledProcessError):
        staging.stage_artifact(path, ["worker-01"])


def test_stage_artifact_limits_to_a_single_worker_when_given_one(
    staging, tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "connectivity.json"
    path.write_text(json.dumps({"ok": True}))
    calls: list[list[str]] = []
    monkeypatch.setattr(staging.subprocess, "run", lambda cmd, check: calls.append(cmd))

    staging.stage_artifact(path, ["worker-02"])

    cmd = calls[0]
    assert cmd[cmd.index("--limit") + 1] == "worker-02"


# --- unstage_artifact ------------------------------------------------------


def test_unstage_artifact_invokes_the_playbook_with_unstage_action(staging, monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(staging.subprocess, "run", lambda cmd, check: calls.append(cmd))

    staging.unstage_artifact("cohort-input-abc123.json", ["worker-01", "worker-02"])

    cmd = calls[0]
    assert "stage_action=unstage" in cmd
    assert "remote_filename=cohort-input-abc123.json" in cmd
    assert cmd[cmd.index("--limit") + 1] == "worker-01,worker-02"


def test_unstage_artifact_does_not_raise_on_failure(staging, monkeypatch) -> None:
    def _raise(cmd, check):
        raise staging.subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(staging.subprocess, "run", _raise)

    staging.unstage_artifact("cohort-input-abc123.json", ["worker-01"])  # does not raise
