"""ADR 0073: runtime digests, skew reporting, retries, and the `jobs` commands.

All fixtures are synthetic; worker names are `worker-a` style and no real
infrastructure is contacted (the RQ backend is replaced by an in-memory fake).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from networked_players_platform import digest as digest_module
from networked_players_platform.cli import main, worker_report
from networked_players_platform.digest import (
    DigestError,
    checkout_package_roots,
    contracts_digest,
    entry_modules,
    import_closure,
    runtime_digest,
    workload_closures,
    workload_digests,
)
from networked_players_platform.executor import execute_run
from networked_players_platform.jobs import (
    JobRecord,
    RqJobBackend,
    cancel_job,
    classify_failure,
    is_retryable_failure,
    log_locations,
)
from networked_players_platform.models import (
    CapabilityRequirement,
    DatasetIdentity,
    RunRequest,
    WorkerAdvertisement,
)
from networked_players_platform.retry import (
    RetriesExhaustedError,
    RunFailedError,
    RunLostError,
    WorkerWatch,
    attempt_run_id,
    run_with_retries,
)
from networked_players_platform.scheduler import NoEligibleWorkerError, select_worker
from networked_players_platform.workloads import _artifact_validate_handler

REPO_ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 11, 16, tzinfo=UTC)
COMMIT = "a" * 40
DIGEST = "e" * 64
OTHER_DIGEST = "f" * 64
LOCK = "1" * 64


# --- a synthetic repository ----------------------------------------------------------


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    files = {
        "uv.lock": "lock v1\n",
        "docs/NOTES.md": "docs\n",
        "apps/web/src/app.ts": "export {}\n",
        "data/artifact.json": "{}\n",
        "packages/alpha/src/networked_players_alpha/__init__.py": "",
        "packages/alpha/src/networked_players_alpha/entry.py": (
            "from networked_players_beta import util\n\n\ndef handler():\n    return util\n"
        ),
        "packages/alpha/src/networked_players_alpha/unused.py": "UNUSED = 1\n",
        "packages/alpha/tests/test_alpha.py": "def test(): pass\n",
        "packages/beta/src/networked_players_beta/__init__.py": "",
        "packages/beta/src/networked_players_beta/util.py": "VALUE = 1\n",
        "packages/beta/src/networked_players_beta/data.json": '{"k": 1}\n',
        "packages/gamma/src/networked_players_gamma/__init__.py": "",
        "packages/gamma/src/networked_players_gamma/other.py": "GAMMA = 1\n",
    }
    for relative, content in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return repo


def _digest(repo: Path, module: str = "networked_players_alpha.entry") -> str:
    roots = checkout_package_roots(repo)
    return runtime_digest(import_closure(module, roots), roots)


def test_digest_is_stable_across_file_order_and_mtime(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    first = _digest(repo)
    for index, path in enumerate(sorted(repo.rglob("*"), reverse=True)):
        if path.is_file():
            os.utime(path, (1_000_000 + index, 1_000_000 + index))
    assert _digest(repo) == first

    # Same content written in the opposite creation order, somewhere else.
    clone = tmp_path / "clone"
    for path in sorted(repo.rglob("*"), reverse=True):
        if path.is_file():
            target = clone / path.relative_to(repo)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
    assert _digest(clone) == first


def test_docs_web_data_tests_and_pycache_do_not_change_the_digest(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    before = _digest(repo)
    (repo / "docs/NOTES.md").write_text("changed docs\n")
    (repo / "apps/web/src/app.ts").write_text("export const x = 1\n")
    (repo / "data/artifact.json").write_text('{"changed": true}\n')
    (repo / "packages/alpha/tests/test_alpha.py").write_text("def test(): assert True\n")
    pycache = repo / "packages/alpha/src/networked_players_alpha/__pycache__"
    pycache.mkdir()
    (pycache / "entry.cpython-312.py").write_text("junk")
    (repo / "packages/gamma/src/networked_players_gamma/other.py").write_text("GAMMA = 2\n")
    assert _digest(repo) == before  # gamma is outside alpha.entry's closure


@pytest.mark.parametrize(
    "relative",
    [
        "packages/alpha/src/networked_players_alpha/entry.py",
        "packages/alpha/src/networked_players_alpha/unused.py",  # same package: covered
        "packages/beta/src/networked_players_beta/util.py",
        "packages/beta/src/networked_players_beta/data.json",
    ],
)
def test_one_byte_change_in_executed_package_files_changes_the_digest(
    tmp_path: Path, relative: str
) -> None:
    repo = _make_repo(tmp_path)
    before = _digest(repo)
    target = repo / relative
    target.write_bytes(target.read_bytes() + b" ")
    assert _digest(repo) != before


def test_uv_lock_is_provenance_only_not_part_of_the_digest(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    before = _digest(repo)
    (repo / "uv.lock").write_text("a dev-tool bump\n")
    assert _digest(repo) == before
    assert digest_module.uv_lock_sha256(repo) != digest_module.file_sha256(
        tmp_path / "repo" / "docs/NOTES.md"
    )


def test_any_packaged_file_type_is_hashed_but_bytecode_is_not(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    before = _digest(repo)
    package = repo / "packages/beta/src/networked_players_beta"
    (package / "model.bin").write_bytes(b"weights")  # a packaged non-Python file
    assert _digest(repo) != before
    with_bin = _digest(repo)
    (package / "util.cpython-312.pyc").write_bytes(b"bytecode")
    assert _digest(repo) == with_bin


def test_package_hashing_is_memoized_across_workloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_repo(tmp_path)
    calls: list[Path] = []
    real = digest_module.file_sha256
    monkeypatch.setattr(digest_module, "file_sha256", lambda path: calls.append(path) or real(path))
    modules = {
        "w.one": "networked_players_alpha.entry",
        "w.two": "networked_players_alpha.entry",
        "w.three": "networked_players_alpha.entry",
    }
    workload_digests(modules, checkout_package_roots(repo))
    assert len(calls) == len(set(calls))  # no file hashed twice across three workloads


def test_one_unhashable_workload_is_unavailable_and_the_rest_stay(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    (repo / "packages/alpha/src/networked_players_alpha/broken.py").write_text("def (:\n")
    modules = {
        "ok.workload": "networked_players_beta.util",
        "bad.workload": "networked_players_alpha.broken",
        "missing.workload": "networked_players_nowhere.entry",
    }
    digests, errors = digest_module.safe_workload_digests(modules, checkout_package_roots(repo))
    assert set(digests) == {"ok.workload"}
    assert set(errors) == {"bad.workload", "missing.workload"}
    with pytest.raises(DigestError):
        workload_digests(modules, checkout_package_roots(repo))


def test_import_closure_follows_function_local_and_relative_imports(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    (repo / "packages/alpha/src/networked_players_alpha/entry.py").write_text(
        "from . import unused\n\n\ndef late():\n    import networked_players_gamma.other\n"
    )
    roots = checkout_package_roots(repo)
    assert import_closure("networked_players_alpha.entry", roots) == {
        "networked_players_alpha",
        "networked_players_gamma",
    }
    with pytest.raises(DigestError):
        import_closure("networked_players_missing.entry", roots)


def test_contracts_digest_tracks_content_not_version(tmp_path: Path) -> None:
    pkg = tmp_path / "networked_players_contracts"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('__version__ = "0.1.0"\n')
    (pkg / "rules.py").write_text("ALLOWED = {1}\n")
    before = contracts_digest({"networked_players_contracts": pkg})
    (pkg / "rules.py").write_text("ALLOWED = {1, 2}\n")  # version unchanged
    assert contracts_digest({"networked_players_contracts": pkg}) != before


# --- the real repository --------------------------------------------------------------


def test_real_import_closures_are_pinned() -> None:
    """A new import that widens a workload's closure must be a visible review change."""
    closures = workload_closures(entry_modules(), checkout_package_roots(REPO_ROOT))
    platform_and_contracts = ("networked_players_contracts", "networked_players_platform")
    assert closures["artifact.validate"] == platform_and_contracts
    assert closures["platform.self-test"] == platform_and_contracts
    assert closures["research.corpus-check"] == platform_and_contracts
    assert closures["cohort.score"] == (
        "networked_players_catalog",
        "networked_players_contracts",
        "networked_players_graph_core",
        "networked_players_platform",
    )
    assert closures["research.graph-metrics"] == (
        "networked_players_contracts",
        "networked_players_graph_core",
        "networked_players_platform",
        "networked_players_research",
    )


def test_entry_points_follow_the_workload_id_convention() -> None:
    """Entry point `cohort-score` must register workload `cohort.score`, because the
    executor and the digest code resolve plugin workloads by name without importing."""
    from networked_players_platform.workloads import discover_workloads

    modules = entry_modules()
    for workload_id in discover_workloads():
        assert workload_id in modules
    assert digest_module.workload_id_for_entry_point("research-graph-metrics") == (
        "research.graph-metrics"
    )


def test_load_workload_imports_only_the_requested_plugin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib.metadata

    from networked_players_platform import workloads

    loaded: list[str] = []
    real = workloads._load_entry_point

    def tracking(entry_point: importlib.metadata.EntryPoint):
        loaded.append(entry_point.name)
        return real(entry_point)

    monkeypatch.setattr(workloads, "_load_entry_point", tracking)
    assert workloads.load_workload("artifact.validate") is not None
    assert loaded == []  # a built-in imports no plugin at all
    assert workloads.load_workload("cohort.score") is not None
    assert loaded == ["cohort-score"]
    assert workloads.load_workload("no.such-workload") is None


def test_worker_without_a_release_manifest_still_advertises_digests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PLATFORM_RELEASE_JSON", raising=False)
    digest_module.installed_digest_report.cache_clear()
    try:
        digests, errors = digest_module.installed_digest_report()
    finally:
        digest_module.installed_digest_report.cache_clear()
    assert errors == {}
    assert digests == workload_digests(entry_modules(), checkout_package_roots(REPO_ROOT))


def test_a_broken_release_manifest_is_only_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = tmp_path / "release.json"
    release.write_text("not json")
    monkeypatch.setenv("PLATFORM_RELEASE_JSON", str(release))
    digest_module.installed_digest_report.cache_clear()
    try:
        digests, _ = digest_module.installed_digest_report()
    finally:
        digest_module.installed_digest_report.cache_clear()
    assert "artifact.validate" in digests


# --- selection and skew reporting ----------------------------------------------------


def _worker(
    worker_id: str,
    *,
    schema_version: int = 2,
    digest: str | None = DIGEST,
    observed_at: datetime = NOW,
    architecture: str = "aarch64",
    tags: tuple[str, ...] = ("validation",),
    max_job_memory_mb: int = 512,
    workloads: dict[str, str] | None = None,
    datasets: tuple[DatasetIdentity, ...] = (),
    active_jobs: int = 0,
) -> WorkerAdvertisement:
    return WorkerAdvertisement(
        schema_version=schema_version,
        worker_id=worker_id,
        observed_at=observed_at.isoformat(),
        architecture=architecture,
        tags=tags,
        total_memory_mb=1024,
        max_job_memory_mb=max_job_memory_mb,
        runtime_commit=COMMIT,
        workloads=workloads if workloads is not None else {"artifact.validate": "1"},
        datasets=datasets,
        active_jobs=active_jobs,
        runtime_digests={"artifact.validate": digest} if digest else {},
        contracts_version="0.1.0" if schema_version >= 2 else "",
    )


def _rq_alive(*worker_ids: str) -> dict[str, datetime | None]:
    return {worker_id: NOW for worker_id in worker_ids}


def _select(workers: list[WorkerAdvertisement], **kwargs: Any) -> WorkerAdvertisement:
    requirement = kwargs.pop("requirement", CapabilityRequirement(tags=("validation",)))
    return select_worker(
        workers,
        requirement,
        workload_id="artifact.validate",
        workload_version="1",
        runtime_digest=kwargs.pop("runtime_digest", DIGEST),
        now=NOW,
        **kwargs,
    )


def test_selection_by_digest_ignores_the_git_commit() -> None:
    worker = _worker("worker-a")
    # Same digest, recorded commit differs from whatever a new checkout has: eligible.
    assert _select([worker]).worker_id == "worker-a"


def test_selection_failure_lists_every_workers_reasons() -> None:
    now_stale = NOW - timedelta(minutes=5)
    workers = [
        _worker("worker-stale", observed_at=now_stale),
        _worker("worker-skewed", digest=OTHER_DIGEST),
        _worker("worker-noload", workloads={}),
        _worker("worker-x86", architecture="riscv64"),
        _worker("worker-untagged", tags=()),
        _worker("worker-small", max_job_memory_mb=64),
        _worker("worker-nodata"),
    ]
    requirement = CapabilityRequirement(
        architectures=("aarch64",),
        tags=("validation",),
        min_memory_mb=128,
        datasets=(DatasetIdentity("discogs-onehop", "20260601", "c" * 64),),
    )
    with pytest.raises(NoEligibleWorkerError) as excinfo:
        _select(workers, requirement=requirement)
    reasons = excinfo.value.reasons
    assert "stale heartbeat" in reasons["worker-stale"][0]
    assert any(OTHER_DIGEST in r and DIGEST in r for r in reasons["worker-skewed"])
    assert any("not provided" in r for r in reasons["worker-noload"])
    assert any("architecture riscv64" in r for r in reasons["worker-x86"])
    assert any("missing tags" in r for r in reasons["worker-untagged"])
    assert any("max job memory 64" in r for r in reasons["worker-small"])
    assert any("dataset identity" in r for r in reasons["worker-nodata"])
    message = str(excinfo.value)
    assert message.startswith("no eligible worker for artifact.validate@1")
    assert "worker-skewed" in message and "worker-stale" in message


def test_no_advertisements_is_explained() -> None:
    with pytest.raises(NoEligibleWorkerError, match="no worker advertisements"):
        _select([])


def test_mixed_fleet_old_schema_worker_is_refused_with_a_reason_never_matched() -> None:
    old = _worker("worker-old", schema_version=1, digest=None)
    new = _worker("worker-new")
    assert _select([old, new]).worker_id == "worker-new"
    with pytest.raises(NoEligibleWorkerError) as excinfo:
        _select([old])
    assert any("schema 1" in r and "redeploy" in r for r in excinfo.value.reasons["worker-old"])


def test_schema1_advertisement_round_trips_without_digest_fields() -> None:
    legacy = {
        "schema_version": 1,
        "worker_id": "worker-old",
        "observed_at": NOW.isoformat(),
        "architecture": "aarch64",
        "tags": ["validation"],
        "total_memory_mb": 1024,
        "max_job_memory_mb": 512,
        "runtime_commit": COMMIT,
        "workloads": {"artifact.validate": "1"},
    }
    worker = WorkerAdvertisement.from_dict(legacy)
    assert worker.runtime_digests == {} and worker.contracts_digest == ""


def test_excluded_worker_is_not_reselected() -> None:
    workers = [_worker("worker-a"), _worker("worker-b", active_jobs=3)]
    assert _select(workers, exclude=frozenset({"worker-a"})).worker_id == "worker-b"
    with pytest.raises(NoEligibleWorkerError) as excinfo:
        _select(workers[:1], exclude=frozenset({"worker-a"}))
    assert "already attempted" in str(excinfo.value)


def test_status_report_flags_digest_and_contracts_skew(capsys: pytest.CaptureFixture[str]) -> None:
    worker = _worker("worker-a")
    report = worker_report(
        worker, local_digests={"artifact.validate": OTHER_DIGEST}, local_contracts_digest=DIGEST
    )
    assert report["workload_status"]["artifact.validate"]["match"] == "mismatch"
    assert report["contracts_match"] == "no-digest"
    matching = worker_report(
        worker, local_digests={"artifact.validate": DIGEST}, local_contracts_digest=None
    )
    assert matching["workload_status"]["artifact.validate"]["match"] == "match"
    assert matching["contracts_match"] == "no-digest"


def test_cluster_status_prints_digest_commit_and_match(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    workers = tmp_path / "workers"
    workers.mkdir()
    (workers / "worker-a.json").write_text(json.dumps(_worker("worker-a").to_dict()))
    monkeypatch.setattr(
        "networked_players_platform.cli._local_identity",
        lambda repo_root: ({"artifact.validate": OTHER_DIGEST}, DIGEST),
    )
    assert main(["cluster-status", "--state-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "worker-a" in out and COMMIT[:12] in out and "mismatch" in out
    assert "(local " + OTHER_DIGEST[:12] in out


# --- validation report attribution ---------------------------------------------------


def test_validation_report_records_contracts_version_and_digests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "artifact.json").write_text('{"schema_version": 99}\n')
    from networked_players_platform.models import ArtifactDescriptor
    from networked_players_platform.staging import describe_artifact

    descriptor: ArtifactDescriptor = describe_artifact(
        input_dir, "artifact.json", name="artifact", contract="synthetic-json-v1"
    )
    request = RunRequest(
        schema_version=2,
        run_id="validation-attr",
        workload_id="artifact.validate",
        workload_version="1",
        submitted_at=NOW.isoformat(),
        runtime_commit=COMMIT,
        runtime_digest=DIGEST,
        timeout_seconds=120,
        max_retries=1,
        capabilities=CapabilityRequirement(),
        inputs=(descriptor,),
        expected_outputs=("validation-report",),
        parameters={"validator": "connectivity"},
        attempt=2,
        retry_of="validation-attr0",
    )
    monkeypatch.setattr(
        "networked_players_platform.workloads.installed_runtime_digests",
        lambda: {"artifact.validate": DIGEST},
    )
    monkeypatch.setenv("PLATFORM_RUNTIME_COMMIT", COMMIT)
    monkeypatch.setenv("PLATFORM_WORKER_ID", "worker-a")
    outputs = _artifact_validate_handler(request, input_dir, tmp_path / "out")
    assert outputs[0].contract == "platform-validation-report-v2"
    report = json.loads((tmp_path / "out" / "validation-report.json").read_text())
    import networked_players_contracts

    assert report["contracts_version"] == networked_players_contracts.__version__
    assert report["contracts_digest"] == digest_module.installed_contracts_digest()
    assert len(report["contracts_digest"]) == 64
    assert report["runtime_digest"] == DIGEST
    assert report["attempt"] == 2
    assert report["runtime_commit"] == COMMIT and report["worker_id"] == "worker-a"
    assert report["submitted_commit"] == COMMIT and report["schema_version"] == 2
    assert report["valid"] is False


# --- retries -------------------------------------------------------------------------


def _runner(script: dict[str, Any], calls: list[tuple[str, str, int, str | None]]):
    def run_attempt(
        worker: WorkerAdvertisement, run_id: str, attempt: int, retry_of: str | None
    ) -> dict[str, Any]:
        calls.append((worker.worker_id, run_id, attempt, retry_of))
        outcome = script[worker.worker_id]
        if isinstance(outcome, Exception):
            raise outcome
        return {"status": "succeeded", "attempt": attempt}

    return run_attempt


def _selector(workers: list[WorkerAdvertisement]):
    return lambda excluded, floor: _select(workers, exclude=excluded, memory_above_mb=floor)


def test_lost_worker_retries_on_another_worker_and_records_attempt_two() -> None:
    workers = [_worker("worker-a"), _worker("worker-b", active_jobs=1)]
    calls: list[tuple[str, str, int, str | None]] = []
    outcome = run_with_retries(
        base_run_id="run-1",
        max_retries=1,
        select=_selector(workers),
        run_attempt=_runner({"worker-a": RunLostError("gone"), "worker-b": None}, calls),
    )
    assert outcome.attempt == 2 and outcome.worker.worker_id == "worker-b"
    assert outcome.result["attempt"] == 2
    assert outcome.run_id == "run-1-a2" != "run-1"
    assert calls == [("worker-a", "run-1", 1, None), ("worker-b", "run-1-a2", 2, "run-1")]
    assert [o.worker_id for o in outcome.orphans] == ["worker-a"]


def test_no_retry_when_max_retries_is_zero() -> None:
    workers = [_worker("worker-a"), _worker("worker-b", active_jobs=1)]
    calls: list[tuple[str, str, int, str | None]] = []
    with pytest.raises(RetriesExhaustedError) as excinfo:
        run_with_retries(
            base_run_id="run-1",
            max_retries=0,
            select=_selector(workers),
            run_attempt=_runner({"worker-a": RunLostError("gone"), "worker-b": None}, calls),
        )
    assert len(calls) == 1 and excinfo.value.attempts[0].outcome == "worker-lost"


def test_deterministic_failure_is_not_retried() -> None:
    workers = [_worker("worker-a"), _worker("worker-b", active_jobs=1)]
    calls: list[tuple[str, str, int, str | None]] = []
    with pytest.raises(RetriesExhaustedError):
        run_with_retries(
            base_run_id="run-1",
            max_retries=3,
            select=_selector(workers),
            run_attempt=_runner(
                {"worker-a": RunFailedError("ValueError: bad input", retryable=False)}, calls
            ),
        )
    assert len(calls) == 1


def test_killed_work_horse_is_retried_and_retries_run_out_with_reasons() -> None:
    workers = [_worker("worker-a")]
    calls: list[tuple[str, str, int, str | None]] = []
    killed = RunFailedError("Work-horse terminated unexpectedly", retryable=True)
    with pytest.raises(RetriesExhaustedError, match="cannot retry attempt 2"):
        run_with_retries(
            base_run_id="run-1",
            max_retries=1,
            select=_selector(workers),
            run_attempt=_runner({"worker-a": killed}, calls),
        )
    assert len(calls) == 1


def test_first_attempt_without_eligible_worker_raises_the_reasons() -> None:
    with pytest.raises(NoEligibleWorkerError, match="digest mismatch"):
        run_with_retries(
            base_run_id="run-1",
            max_retries=1,
            select=_selector([_worker("worker-a", digest=OTHER_DIGEST)]),
            run_attempt=_runner({}, []),
        )


def test_failure_classification_maps_rq_statuses_to_retry_decisions() -> None:
    horse = "Work-horse terminated unexpectedly; waitpid returned"
    assert classify_failure(f"{horse} 9 (signal 9); ") == "memory-suspect"
    # No signal info: cannot be told apart from an OOM kill.
    assert classify_failure(f"{horse} 256; ") == "memory-suspect"
    assert classify_failure(f"{horse} 15 (signal 15); ") == "retryable"
    assert classify_failure("rq.exceptions.AbandonedJobError") == "memory-suspect"
    assert classify_failure("Job stopped by user, work-horse terminated.") == "stopped"
    assert classify_failure("Traceback ... RunExecutionError: bad") == "deterministic"
    assert classify_failure("Task exceeded maximum timeout value (120 seconds)") == "deterministic"
    assert classify_failure(None) == "deterministic"
    assert is_retryable_failure(f"{horse} 15 (signal 15); ")
    assert not is_retryable_failure("Job stopped by user, work-horse terminated.")


def test_suspected_oom_is_not_retried_on_identical_hardware() -> None:
    workers = [_worker("worker-a"), _worker("worker-b", active_jobs=1)]  # same 512 MB budget
    calls: list[tuple[str, str, int, str | None]] = []
    killed = RunFailedError("killed (signal 9)", retryable=True, memory_suspect=True)
    with pytest.raises(RetriesExhaustedError, match="possibly out of memory at 512 MB") as excinfo:
        run_with_retries(
            base_run_id="run-1",
            max_retries=2,
            select=_selector(workers),
            run_attempt=_runner({"worker-a": killed, "worker-b": None}, calls),
        )
    assert [c[0] for c in calls] == ["worker-a"]
    assert excinfo.value.attempts[0].outcome == "memory-suspect-kill"


def test_suspected_oom_is_retried_on_a_worker_with_a_larger_budget() -> None:
    workers = [_worker("worker-a"), _worker("worker-big", max_job_memory_mb=1000, active_jobs=5)]
    calls: list[tuple[str, str, int, str | None]] = []
    killed = RunFailedError("killed (signal 9)", retryable=True, memory_suspect=True)
    outcome = run_with_retries(
        base_run_id="run-1",
        max_retries=1,
        select=_selector(workers),
        run_attempt=_runner({"worker-a": killed, "worker-big": None}, calls),
    )
    assert outcome.worker.worker_id == "worker-big" and outcome.attempt == 2


def test_worker_watch_uses_rq_liveness_only_and_the_grace() -> None:
    watch = WorkerWatch("worker-a", grace=timedelta(seconds=60))
    assert watch.observe(NOW, NOW) is False  # live
    # RQ record absent: not yet lost within the grace...
    assert watch.observe(None, NOW + timedelta(seconds=30)) is False
    # ...lost once it has stayed absent for the grace.
    assert watch.observe(None, NOW + timedelta(seconds=95)) is True
    # A returning RQ heartbeat resets the clock.
    back = NOW + timedelta(seconds=100)
    assert watch.observe(back, back) is False
    assert watch.observe(None, back + timedelta(seconds=10)) is False


def test_scenario_a_dead_rq_worker_with_a_fresh_advertisement_is_lost_and_unschedulable() -> None:
    """RQ worker dead while the separate heartbeat timer keeps advertising."""
    watch = WorkerWatch("worker-a", grace=timedelta(seconds=60))
    verdicts = []
    for step in range(0, 700, 30):
        now = NOW + timedelta(seconds=step)
        # The advertisement is fresh at every step; RQ expires its record after 420 s.
        beat = NOW if step < 420 else None
        verdicts.append(watch.observe(beat, now, advertisement_fresh=True))
    assert verdicts[-1] is True and watch.advertisement_fresh is True
    # Scheduling: fresh advertisement, absent RQ record -> excluded with a reason.
    with pytest.raises(NoEligibleWorkerError) as excinfo:
        _select([_worker("worker-a")], rq_heartbeats={"worker-a": None})
    assert any("RQ worker process absent" in r for r in excinfo.value.reasons["worker-a"])
    stale_rq = {"worker-a": NOW - timedelta(seconds=500)}
    with pytest.raises(NoEligibleWorkerError, match="RQ worker heartbeat stale"):
        _select([_worker("worker-a")], rq_heartbeats=stale_rq)
    chosen = _select([_worker("worker-a")], rq_heartbeats=_rq_alive("worker-a"))
    assert chosen.worker_id == "worker-a"


def test_scenario_b_failing_heartbeat_with_a_live_rq_worker_is_never_lost() -> None:
    """Advertisement lapsed (heartbeat unit failing) while RQ itself is healthy."""
    watch = WorkerWatch("worker-a", grace=timedelta(seconds=60))
    for step in range(0, 3600, 30):
        now = NOW + timedelta(seconds=step)
        assert watch.observe(now - timedelta(seconds=5), now, advertisement_fresh=False) is False


def _run_dir(base: Path, name: str, request: RunRequest) -> Path:
    run_dir = base / name
    (run_dir / "input").mkdir(parents=True)
    (run_dir / "request.json").write_text(json.dumps(request.to_dict()))
    return run_dir


def test_a_retried_attempt_does_not_collide_with_the_first_attempts_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PLATFORM_WORKER_ID", "worker-b")
    monkeypatch.setenv("PLATFORM_RUNTIME_COMMIT", COMMIT)
    monkeypatch.setattr(
        "networked_players_platform.executor.installed_digest_report",
        lambda: ({"platform.self-test": DIGEST}, {}),
    )

    def request(run_id: str, attempt: int, retry_of: str | None) -> RunRequest:
        return RunRequest(
            schema_version=2,
            run_id=run_id,
            workload_id="platform.self-test",
            workload_version="1",
            submitted_at=NOW.isoformat(),
            runtime_commit=COMMIT,
            runtime_digest=DIGEST,
            timeout_seconds=60,
            max_retries=1,
            capabilities=CapabilityRequirement(),
            inputs=(),
            expected_outputs=("self-test",),
            parameters={},
            attempt=attempt,
            retry_of=retry_of,
        )

    first = request("run-1", 1, None)
    second = request(attempt_run_id("run-1", 2), 2, "run-1")
    first_dir = _run_dir(tmp_path, first.run_id, first)
    # The first attempt's worker died after creating partial output.
    (first_dir / ".output.staging").mkdir()
    second_dir = _run_dir(tmp_path, second.run_id, second)

    result = execute_run(str(second_dir))
    assert result["status"] == "succeeded" and result["attempt"] == 2
    assert result["runtime_digest"] == DIGEST and result["schema_version"] == 2
    assert (second_dir / "completed" / "result.json").exists()
    assert (first_dir / ".output.staging").exists()  # untouched orphan evidence

    # Reusing the first attempt's directory is still refused (the no-reuse rule stands).
    with pytest.raises(Exception, match="refusing reuse"):
        execute_run(str(first_dir))
    failure = json.loads((first_dir / "failed.json").read_text())
    assert failure["attempt"] == 1 and failure["run_dir"].endswith("run-1")


# --- jobs commands -------------------------------------------------------------------


def _record(job_id: str, state: str, worker: str = "worker-a", **kw: Any) -> JobRecord:
    defaults: dict[str, Any] = {
        "queue": f"networked-players.platform.{worker}",
        "workload_id": "artifact.validate",
        "attempt": 1,
        "retry_of": None,
        "enqueued_at": "2026-11-16T00:00:00+00:00",
        "started_at": None,
        "ended_at": None,
        "remote_run": f"~/runs/{job_id}",
        "exc_info": None,
    }
    defaults.update(kw)
    return JobRecord(job_id=job_id, worker_id=worker, state=state, **defaults)


class FakeBackend:
    def __init__(self, records: list[JobRecord], advertised: list[str]) -> None:
        self.records = {r.job_id: r for r in records}
        self.advertised_workers = advertised
        self.canceled: list[str] = []
        self.stopped: list[str] = []

    def list_jobs(self, *, limit_per_state: int) -> list[JobRecord]:
        return list(self.records.values())

    def get_job(self, job_id: str) -> JobRecord | None:
        return self.records.get(job_id)

    def cancel_queued(self, job_id: str) -> None:
        self.canceled.append(job_id)

    def request_stop(self, job_id: str) -> None:
        self.stopped.append(job_id)


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend(
        [
            _record("job-queued", "queued"),
            _record("job-started", "started", started_at="2026-11-16T00:01:00+00:00"),
            _record("job-done", "finished", "worker-b", ended_at="2026-11-16T00:02:00+00:00"),
            _record(
                "job-failed",
                "failed",
                "worker-b",
                attempt=2,
                retry_of="job-failed0",
                exc_info="RunExecutionError: digest mismatch",
            ),
        ],
        advertised=["worker-a", "worker-b"],
    )


@pytest.fixture
def backend_fixture(backend: FakeBackend) -> FakeBackend:
    return backend


def test_jobs_list_filters_and_prints_timestamps(
    backend: FakeBackend, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["jobs", "list"], jobs_backend=backend) == 0
    out = capsys.readouterr().out
    assert "job-queued" in out and "2026-11-16T00:01:00+00:00" in out and "ATTEMPT" in out
    assert (
        main(
            ["jobs", "--json", "list", "--worker", "worker-b", "--state", "failed"],
            jobs_backend=backend,
        )
        == 0
    )
    rows = json.loads(capsys.readouterr().out)
    assert [r["job_id"] for r in rows] == ["job-failed"] and rows[0]["attempt"] == 2


def test_jobs_status_and_logs(backend: FakeBackend, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["jobs", "status", "job-failed"], jobs_backend=backend) == 0
    status = capsys.readouterr().out
    assert "state: failed" in status and "digest mismatch" in status and "attempt: 2" in status
    assert main(["jobs", "logs", "job-failed"], jobs_backend=backend) == 0
    logs = capsys.readouterr().out
    assert "failure_record_on_worker: ~/runs/job-failed/failed.json" in logs
    assert "recorded_failure: RunExecutionError: digest mismatch" in logs
    assert "does not connect" in logs
    assert main(["jobs", "status", "job-missing"], jobs_backend=backend) == 1
    assert (
        log_locations(_record("j", "queued", remote_run=None))["failure_record_on_worker"] is None
    )


def test_cancel_queued_job_removes_it_without_stopping_anything(
    backend: FakeBackend, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["jobs", "cancel", "job-queued"], jobs_backend=backend) == 0
    assert backend.canceled == ["job-queued"] and backend.stopped == []
    assert "canceled" in capsys.readouterr().out


def test_cancel_started_job_requests_a_stop_and_says_so_honestly(
    backend: FakeBackend, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["jobs", "cancel", "job-started"], jobs_backend=backend) == 0
    assert backend.stopped == ["job-started"] and backend.canceled == []
    out = capsys.readouterr().out
    assert "stop-requested" in out and "asynchronously" in out and "left in place" in out


def test_cancel_started_job_on_a_silent_worker_warns_it_may_not_be_delivered() -> None:
    backend = FakeBackend([_record("job-started", "started")], advertised=[])
    outcome = cancel_job(backend, "job-started", advertised_workers=[])
    assert outcome.action == "stop-requested" and "not advertising" in outcome.message


def test_cancel_finished_or_unknown_job_is_refused(
    backend: FakeBackend, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["jobs", "cancel", "job-done"], jobs_backend=backend) == 1
    assert main(["jobs", "cancel", "job-missing"], jobs_backend=backend) == 1
    assert backend.canceled == [] and backend.stopped == []
    assert "already finished" in capsys.readouterr().out


def test_rq_backend_maps_a_job_to_a_record_without_a_broker() -> None:
    status = SimpleNamespace(value="failed")
    job = SimpleNamespace(
        id="job-1",
        origin="networked-players.platform.worker-a",
        meta={"workload_id": "artifact.validate", "attempt": 2, "retry_of": "job-0"},
        args=("~/runs/job-1",),
        worker_name="worker-a",
        enqueued_at=NOW,
        started_at=None,
        ended_at=None,
        exc_info="boom",
        get_status=lambda refresh=True: status,
    )
    record = RqJobBackend(connection=None)._record(job)
    assert (record.worker_id, record.state, record.attempt, record.retry_of) == (
        "worker-a",
        "failed",
        2,
        "job-0",
    )
    assert record.remote_run == "~/runs/job-1" and record.enqueued_at == NOW.isoformat()


# --- executor refusals -----------------------------------------------------------------


def _self_test_request(**overrides: Any) -> RunRequest:
    fields: dict[str, Any] = {
        "schema_version": 2,
        "run_id": "refusal-1",
        "workload_id": "platform.self-test",
        "workload_version": "1",
        "submitted_at": NOW.isoformat(),
        "runtime_commit": COMMIT,
        "runtime_digest": DIGEST,
        "timeout_seconds": 60,
        "max_retries": 0,
        "capabilities": CapabilityRequirement(),
        "inputs": (),
        "expected_outputs": ("self-test",),
        "parameters": {},
    }
    fields.update(overrides)
    return RunRequest(**fields)


def test_executor_refuses_a_schema_1_request_that_carries_no_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PLATFORM_WORKER_ID", "worker-a")
    monkeypatch.setattr(
        "networked_players_platform.executor.installed_digest_report",
        lambda: ({"platform.self-test": DIGEST}, {}),
    )
    request = _self_test_request(schema_version=1, runtime_digest="")
    run_dir = _run_dir(tmp_path, "legacy", request)
    with pytest.raises(Exception, match="no runtime digest"):
        execute_run(str(run_dir))
    assert (run_dir / "failed.json").exists() and not (run_dir / "completed").exists()


def test_executor_refuses_when_the_worker_has_no_digest_for_the_workload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PLATFORM_WORKER_ID", "worker-a")
    monkeypatch.setattr(
        "networked_players_platform.executor.installed_digest_report",
        lambda: ({}, {"platform.self-test": "cannot parse broken.py"}),
    )
    run_dir = _run_dir(tmp_path, "nodigest", _self_test_request())
    with pytest.raises(Exception, match=r"no runtime digest for platform\.self-test") as excinfo:
        execute_run(str(run_dir))
    assert "cannot parse broken.py" in str(excinfo.value)
    assert not (run_dir / "completed").exists()


def test_executor_loads_only_the_requested_workload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PLATFORM_WORKER_ID", "worker-a")
    monkeypatch.setenv("PLATFORM_RUNTIME_COMMIT", COMMIT)
    monkeypatch.setattr(
        "networked_players_platform.executor.installed_digest_report",
        lambda: ({"platform.self-test": DIGEST}, {}),
    )

    def forbidden() -> None:
        raise AssertionError("executor must not discover every plugin")

    monkeypatch.setattr("networked_players_platform.workloads.discover_workloads", forbidden)
    monkeypatch.setattr(
        "networked_players_platform.workloads.discover_available_workloads", forbidden
    )
    run_dir = _run_dir(tmp_path, "single", _self_test_request())
    assert execute_run(str(run_dir))["status"] == "succeeded"


# --- advertisements and CLI ------------------------------------------------------------


class _Store:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values

    def scan_iter(self, match: str):
        return iter(self.values)

    def get(self, name: bytes | str) -> str | None:
        return self.values.get(name if isinstance(name, str) else name.decode())


def test_one_malformed_advertisement_is_skipped_with_a_per_worker_reason() -> None:
    from networked_players_platform.broker import (
        WORKER_KEY_PREFIX,
        read_advertisements,
        read_advertisements_checked,
    )

    good = _worker("worker-a")
    store = _Store(
        {
            WORKER_KEY_PREFIX + "worker-a": json.dumps(good.to_dict()),
            WORKER_KEY_PREFIX + "worker-bad": "{not json",
            WORKER_KEY_PREFIX + "worker-future": json.dumps(
                {**good.to_dict(), "schema_version": 9}
            ),
            WORKER_KEY_PREFIX + "worker-short": json.dumps({"schema_version": 2}),
        }
    )
    workers, problems = read_advertisements_checked(store)
    assert [w.worker_id for w in workers] == ["worker-a"]
    assert set(problems) == {"worker-bad", "worker-future", "worker-short"}
    assert all(p.startswith("unreadable advertisement") for p in problems.values())
    assert [w.worker_id for w in read_advertisements(store)] == ["worker-a"]
    # The reasons surface in selection failures.
    with pytest.raises(NoEligibleWorkerError) as excinfo:
        _select([_worker("worker-a", digest=OTHER_DIGEST)], problems=problems)
    assert "unreadable advertisement" in excinfo.value.reasons["worker-bad"][0]


def test_rq_worker_heartbeat_reads_the_rq_record_read_only() -> None:
    from networked_players_platform.broker import read_rq_worker_heartbeat

    class Store:
        def __init__(self, value: bytes | None) -> None:
            self.value = value
            self.asked: list[tuple[str, str]] = []

        def hget(self, name: str, key: str) -> bytes | None:
            self.asked.append((name, key))
            return self.value

    store = Store(b"2026-11-16T00:00:30.250000Z")
    beat = read_rq_worker_heartbeat(store, "worker-a")
    assert beat == datetime(2026, 11, 16, 0, 0, 30, 250000, tzinfo=UTC)
    assert store.asked == [("rq:worker:worker-a", "last_heartbeat")]
    assert read_rq_worker_heartbeat(Store(None), "worker-a") is None
    assert read_rq_worker_heartbeat(Store(b"garbage"), "worker-a") is None


def test_unavailable_workload_is_reported_with_its_reason() -> None:
    worker = WorkerAdvertisement.from_dict(
        {
            **_worker("worker-a", workloads={}).to_dict(),
            "unavailable_workloads": {"artifact.validate": "ImportError: boom"},
        }
    )
    with pytest.raises(NoEligibleWorkerError, match="unavailable on worker: ImportError: boom"):
        _select([worker])


def test_makefile_shaped_jobs_invocation_accepts_json_after_the_subcommand(
    backend_fixture: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    # `make platform-jobs ARGS="list --json"` runs: networked-players-platform jobs list --json
    assert main(["jobs", "list", "--json"], jobs_backend=backend_fixture) == 0
    assert isinstance(json.loads(capsys.readouterr().out), list)
    # Parent-position flags keep working, and a subcommand flag does not reset them.
    assert main(["jobs", "--json", "status", "job-queued"], jobs_backend=backend_fixture) == 0
    assert json.loads(capsys.readouterr().out)["job_id"] == "job-queued"
    assert main(["jobs", "status", "job-queued", "--json"], jobs_backend=backend_fixture) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "queued"
    assert main(["jobs", "cancel", "job-queued", "--json"], jobs_backend=backend_fixture) == 0
    assert json.loads(capsys.readouterr().out)["action"] == "canceled"
    assert main(["jobs", "logs", "job-queued", "--json"], jobs_backend=backend_fixture) == 0
    assert json.loads(capsys.readouterr().out)["worker_id"] == "worker-a"


def test_makefile_target_passes_args_to_the_jobs_subcommand() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text()
    assert "PLATFORM_SUBCOMMAND=jobs ./scripts/platform-status.sh $(or $(ARGS),list)" in makefile
    script = (REPO_ROOT / "scripts/platform-status.sh").read_text()
    assert 'networked-players-platform "${PLATFORM_SUBCOMMAND:-cluster-status}" "$@"' in script
