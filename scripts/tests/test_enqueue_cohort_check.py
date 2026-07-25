"""Tests for scripts/enqueue_cohort_check.py's own stage/enqueue/cleanup
control flow -- now real, non-trivial logic (unlike the thin argparse-only
wrapper the other five enqueue_*_check.py scripts stay at), so it gets its
own focused test: cleanup must be attempted after a pass, after a fail,
after an infra-level enqueue abort, and after the staging attempt itself
fails -- and must be skippable with --keep-staged.

Loads scripts/_artifact_staging.py and scripts/_fleet_check.py into
sys.modules first (same trick test_fleet_check.py uses for a single module)
so enqueue_cohort_check.py's own top-level `from _artifact_staging import
...` / `from _fleet_check import ...` resolve from the cache instead of
needing scripts/ on sys.path.
"""

from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]

_ARTIFACT_BYTES = b"{}"
_FIXED_RUN_ID = "testrunid00"
_EXPECTED_SHA256 = hashlib.sha256(_ARTIFACT_BYTES).hexdigest()
_EXPECTED_REMOTE_FILENAME = f"cohort-input-{_EXPECTED_SHA256}-{_FIXED_RUN_ID}.json"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def enqueue_cohort_check(tmp_path, monkeypatch):
    _load("_artifact_staging", SCRIPTS_DIR / "_artifact_staging.py")
    _load("_fleet_check", SCRIPTS_DIR / "_fleet_check.py")
    module = _load("enqueue_cohort_check", SCRIPTS_DIR / "enqueue_cohort_check.py")

    artifact = tmp_path / "connectivity.json"
    artifact.write_bytes(_ARTIFACT_BYTES)
    monkeypatch.setattr(module, "validate_local_artifact", lambda path: None)
    monkeypatch.setattr(module, "connect_to_broker", lambda usage_hint: object())
    monkeypatch.setattr(module, "resolve_target_workers", lambda group, limit: ["worker-01"])
    monkeypatch.setattr(module, "write_report", lambda **kwargs: tmp_path / "report.json")
    monkeypatch.setattr(module, "new_run_id", lambda: _FIXED_RUN_ID)

    yield module, artifact

    for name in ("_artifact_staging", "_fleet_check", "enqueue_cohort_check"):
        sys.modules.pop(name, None)


def _run(
    module,
    artifact,
    monkeypatch,
    *,
    extra_argv=(),
    enqueue_result=None,
    enqueue_raises=None,
    stage_raises=None,
):
    argv = ["enqueue_cohort_check.py", "--kind", "connectivity", "--artifact", str(artifact)]
    argv.extend(extra_argv)
    monkeypatch.setattr(sys, "argv", argv)

    staged_calls: list[tuple] = []

    def fake_stage_artifact(path, hosts, *, remote_filename, sha256):
        staged_calls.append((path, hosts, remote_filename, sha256))
        if stage_raises is not None:
            raise stage_raises

    monkeypatch.setattr(module, "stage_artifact", fake_stage_artifact)

    unstaged: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        module, "unstage_artifact", lambda filename, hosts: unstaged.append((filename, hosts))
    )

    enqueue_calls: list[dict] = []

    def fake_enqueue_and_collect(**kwargs):
        enqueue_calls.append(kwargs)
        if enqueue_raises is not None:
            raise enqueue_raises
        return enqueue_result

    monkeypatch.setattr(module, "enqueue_and_collect", fake_enqueue_and_collect)
    return unstaged, staged_calls, enqueue_calls


def test_cleanup_runs_after_a_passing_check(enqueue_cohort_check, monkeypatch) -> None:
    module, artifact = enqueue_cohort_check
    unstaged, _staged, _enqueued = _run(
        module,
        artifact,
        monkeypatch,
        enqueue_result={"worker-01": {"ok": True, "result": {"valid": True, "failures": []}}},
    )

    module.main()

    assert unstaged == [(_EXPECTED_REMOTE_FILENAME, ["worker-01"])]


def test_cleanup_runs_after_a_failing_check(enqueue_cohort_check, monkeypatch) -> None:
    module, artifact = enqueue_cohort_check
    unstaged, _staged, _enqueued = _run(
        module,
        artifact,
        monkeypatch,
        enqueue_result={
            "worker-01": {
                "ok": False,
                "job_failed": False,
                "result": {"valid": False, "failures": ["nope"]},
            }
        },
    )

    with pytest.raises(SystemExit):
        module.main()

    assert unstaged == [(_EXPECTED_REMOTE_FILENAME, ["worker-01"])]


def test_cleanup_runs_when_enqueue_and_collect_raises(enqueue_cohort_check, monkeypatch) -> None:
    module, artifact = enqueue_cohort_check
    unstaged, _staged, _enqueued = _run(module, artifact, monkeypatch, enqueue_raises=SystemExit(1))

    with pytest.raises(SystemExit):
        module.main()

    assert unstaged == [(_EXPECTED_REMOTE_FILENAME, ["worker-01"])]


def test_cleanup_runs_when_stage_artifact_itself_raises(enqueue_cohort_check, monkeypatch) -> None:
    """The Finding-3 regression test: stage_artifact raising (e.g. a partial
    Ansible copy that fails a later host's checksum assert) must still
    trigger cleanup -- this fails against the pre-fix code, where
    stage_artifact was called outside the try/finally entirely."""
    module, artifact = enqueue_cohort_check
    unstaged, _staged, _enqueued = _run(
        module, artifact, monkeypatch, stage_raises=subprocess.CalledProcessError(1, ["ansible"])
    )

    with pytest.raises(subprocess.CalledProcessError):
        module.main()

    assert unstaged == [(_EXPECTED_REMOTE_FILENAME, ["worker-01"])]


def test_no_job_enqueued_when_staging_fails(enqueue_cohort_check, monkeypatch) -> None:
    module, artifact = enqueue_cohort_check
    _unstaged, _staged, enqueued = _run(
        module, artifact, monkeypatch, stage_raises=subprocess.CalledProcessError(1, ["ansible"])
    )

    with pytest.raises(subprocess.CalledProcessError):
        module.main()

    assert enqueued == []


def test_keep_staged_skips_cleanup(enqueue_cohort_check, monkeypatch) -> None:
    module, artifact = enqueue_cohort_check
    unstaged, _staged, _enqueued = _run(
        module,
        artifact,
        monkeypatch,
        extra_argv=["--keep-staged"],
        enqueue_result={"worker-01": {"ok": True, "result": {"valid": True, "failures": []}}},
    )

    module.main()

    assert unstaged == []


def test_stage_artifact_is_called_with_the_precomputed_remote_filename_and_sha256(
    enqueue_cohort_check, monkeypatch
) -> None:
    module, artifact = enqueue_cohort_check
    _unstaged, staged, _enqueued = _run(
        module,
        artifact,
        monkeypatch,
        enqueue_result={"worker-01": {"ok": True, "result": {"valid": True, "failures": []}}},
    )

    module.main()

    assert len(staged) == 1
    _path, hosts, remote_filename, sha256 = staged[0]
    assert hosts == ["worker-01"]
    assert remote_filename == _EXPECTED_REMOTE_FILENAME
    assert sha256 == _EXPECTED_SHA256


def test_job_args_use_the_remote_filename_not_the_local_path(
    enqueue_cohort_check, monkeypatch
) -> None:
    module, artifact = enqueue_cohort_check
    _unstaged, _staged, enqueued = _run(
        module,
        artifact,
        monkeypatch,
        enqueue_result={"worker-01": {"ok": True, "result": {"valid": True, "failures": []}}},
    )

    module.main()

    assert len(enqueued) == 1
    assert enqueued[0]["job_args"] == (_EXPECTED_REMOTE_FILENAME,)
