"""Tests for scripts/enqueue_cohort_check.py's own stage/enqueue/cleanup
control flow -- now real, non-trivial logic (unlike the thin argparse-only
wrapper the other five enqueue_*_check.py scripts stay at), so it gets its
own focused test: cleanup must run after a pass, after a fail, and after an
infra-level abort, and must be skippable with --keep-staged.

Loads scripts/_artifact_staging.py and scripts/_fleet_check.py into
sys.modules first (same trick test_fleet_check.py uses for a single module)
so enqueue_cohort_check.py's own top-level `from _artifact_staging import
...` / `from _fleet_check import ...` resolve from the cache instead of
needing scripts/ on sys.path.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]


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
    artifact.write_text("{}")
    monkeypatch.setattr(module, "validate_local_artifact", lambda path: None)
    monkeypatch.setattr(module, "connect_to_broker", lambda usage_hint: object())
    monkeypatch.setattr(module, "resolve_target_workers", lambda group, limit: ["worker-01"])
    monkeypatch.setattr(module, "write_report", lambda **kwargs: tmp_path / "report.json")

    yield module, artifact

    for name in ("_artifact_staging", "_fleet_check", "enqueue_cohort_check"):
        sys.modules.pop(name, None)


def _run(module, artifact, monkeypatch, *, extra_argv=(), enqueue_result=None, enqueue_raises=None):
    argv = ["enqueue_cohort_check.py", "--kind", "connectivity", "--artifact", str(artifact)]
    argv.extend(extra_argv)
    monkeypatch.setattr(sys, "argv", argv)

    def fake_stage_artifact(path, hosts):
        return "cohort-input-abc.json"

    monkeypatch.setattr(module, "stage_artifact", fake_stage_artifact)

    unstaged: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        module, "unstage_artifact", lambda filename, hosts: unstaged.append((filename, hosts))
    )

    def fake_enqueue_and_collect(**kwargs):
        if enqueue_raises is not None:
            raise enqueue_raises
        return enqueue_result

    monkeypatch.setattr(module, "enqueue_and_collect", fake_enqueue_and_collect)
    return unstaged


def test_cleanup_runs_after_a_passing_check(enqueue_cohort_check, monkeypatch) -> None:
    module, artifact = enqueue_cohort_check
    unstaged = _run(
        module,
        artifact,
        monkeypatch,
        enqueue_result={"worker-01": {"ok": True, "result": {"valid": True, "failures": []}}},
    )

    module.main()

    assert unstaged == [("cohort-input-abc.json", ["worker-01"])]


def test_cleanup_runs_after_a_failing_check(enqueue_cohort_check, monkeypatch) -> None:
    module, artifact = enqueue_cohort_check
    unstaged = _run(
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

    assert unstaged == [("cohort-input-abc.json", ["worker-01"])]


def test_cleanup_runs_when_enqueue_and_collect_raises(enqueue_cohort_check, monkeypatch) -> None:
    module, artifact = enqueue_cohort_check
    unstaged = _run(module, artifact, monkeypatch, enqueue_raises=SystemExit(1))

    with pytest.raises(SystemExit):
        module.main()

    assert unstaged == [("cohort-input-abc.json", ["worker-01"])]


def test_keep_staged_skips_cleanup(enqueue_cohort_check, monkeypatch) -> None:
    module, artifact = enqueue_cohort_check
    unstaged = _run(
        module,
        artifact,
        monkeypatch,
        extra_argv=["--keep-staged"],
        enqueue_result={"worker-01": {"ok": True, "result": {"valid": True, "failures": []}}},
    )

    module.main()

    assert unstaged == []
