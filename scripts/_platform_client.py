"""Shared plumbing for the ADR 0034 capability-platform submission scripts
(`submit_cohort_score.py`, `submit_research_platform_job.py`,
`submit_artifact_check.py`) -- the near-identical stage/dispatch/wait/
fetch/verify machinery all three independently duplicated (~90-120 lines
each), confirmed by direct comparison during the post-Phase-3 cleanup
pass. Workload-specific logic stays in each caller: dataset-locality
`CapabilityRequirement`/output promotion (cohort score), the dual-workload
dispatch table (research platform jobs), and ad-hoc artifact size bounds
plus redundant multi-worker fan-out (artifact checks). This module is
only the common run lifecycle: run a local command, resolve the private
inventory, stage a request onto a worker, enqueue and wait, fetch and
verify outputs, and (new) clean up a successfully completed remote run.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from redis import Redis
from rq import Queue
from rq.command import send_stop_job_command
from rq.job import JobStatus

from networked_players_platform.broker import queue_name, read_advertisements
from networked_players_platform.digest import checkout_runtime_digests
from networked_players_platform.jobs import is_retryable_failure
from networked_players_platform.models import ArtifactDescriptor, RunRequest, WorkerAdvertisement
from networked_players_platform.retry import (
    DEFAULT_LOST_GRACE,
    RetriesExhaustedError,
    RetryOutcome,
    RunFailedError,
    RunLostError,
    WorkerWatch,
    run_with_retries,
)
from networked_players_platform.scheduler import NoEligibleWorkerError, select_worker
from networked_players_platform.staging import describe_artifact
from networked_players_platform.workloads import discover_workloads


class PlatformClientError(RuntimeError):
    """Raised for any real submission-lifecycle failure: missing
    inventory, a dirty checkout, an unreachable/misconfigured broker, a
    failed or timed-out remote run, or a fetched output failing checksum
    verification."""


def run(*command: str, cwd: Path, capture: bool = False) -> str:
    completed = subprocess.run(command, cwd=cwd, check=True, text=True, capture_output=capture)
    return completed.stdout if capture else ""


def require_clean_checkout(repo_root: Path) -> None:
    if run("git", "status", "--short", cwd=repo_root, capture=True).strip():
        raise PlatformClientError("submit only from a clean checkout")


def current_commit(repo_root: Path) -> str:
    """Recorded as provenance on the request (ADR 0073); not the eligibility key."""
    return run("git", "rev-parse", "HEAD", cwd=repo_root, capture=True).strip()


def require_broker_url() -> str:
    broker_url = os.environ.get("JOBS_BROKER_URL", "")
    if not broker_url:
        raise PlatformClientError("JOBS_BROKER_URL is required")
    return broker_url


def _inventory_list(inventory_path: Path, repo_root: Path) -> dict[str, Any]:
    if not inventory_path.is_file():
        raise PlatformClientError(f"private Ansible inventory is missing: {inventory_path}")
    payload: dict[str, Any] = json.loads(
        run(
            "uv",
            "run",
            "ansible-inventory",
            "-i",
            str(inventory_path),
            "--list",
            cwd=repo_root,
            capture=True,
        )
    )
    return payload


def inventory_hostvars(inventory_path: Path, repo_root: Path) -> dict[str, dict[str, Any]]:
    hostvars: dict[str, dict[str, Any]] = (
        _inventory_list(inventory_path, repo_root).get("_meta", {}).get("hostvars", {})
    )
    return hostvars


def inventory_group_hosts(inventory_path: Path, repo_root: Path, group: str) -> list[str]:
    inventory = _inventory_list(inventory_path, repo_root)
    hosts: list[str] = sorted(inventory.get(group, {}).get("hosts", []))
    return hosts


def resolve_inventory_host(hostvars: dict[str, dict[str, Any]], worker_id: str) -> str:
    matches = [
        host for host, values in hostvars.items() if values.get("platform_worker_id") == worker_id
    ]
    if len(matches) != 1:
        raise PlatformClientError(
            f"worker_id {worker_id!r} does not map to exactly one private inventory host"
        )
    return matches[0]


def ansible(
    inventory_path: Path,
    repo_root: Path,
    host: str,
    module: str,
    arguments: str,
    *,
    capture: bool = False,
) -> str:
    return run(
        "uv",
        "run",
        "ansible",
        host,
        "-i",
        str(inventory_path),
        "-m",
        module,
        "-a",
        arguments,
        cwd=repo_root,
        capture=capture,
    )


def require_free_disk(
    *,
    inventory_path: Path,
    repo_root: Path,
    host: str,
    min_free_gb: float,
    mount: str = "/",
) -> None:
    """Read-only free-space preflight, run before every dispatch. The
    zimaworker1 disk-full incident happened with no check at all between
    "the worker looked schedulable" and "the job wrote to an already
    critically full disk" -- this refuses to submit rather than dispatching
    into that gap. Uses the same read-only `df` primitive as
    `playbooks/health.yml`'s own floor check, just invoked ad hoc instead
    of via `gather_facts`, so this and the health playbook can drift out of
    sync in value but never in method."""
    output = ansible(
        inventory_path,
        repo_root,
        host,
        "command",
        f"df --output=avail -B1 {mount}",
        capture=True,
    )
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    try:
        available_bytes = int(lines[-1])
    except (IndexError, ValueError) as exc:
        raise PlatformClientError(f"could not parse free-disk check output: {output!r}") from exc
    min_free_bytes = min_free_gb * 1024**3
    if available_bytes < min_free_bytes:
        available_gb = available_bytes / 1024**3
        raise PlatformClientError(
            f"{host} has {available_gb:.1f} GB free on {mount}, below the "
            f"{min_free_gb:g} GB preflight floor -- refusing to dispatch"
        )


def stage_run(
    *, inventory_path: Path, repo_root: Path, host: str, remote_run: str, local_run: Path
) -> None:
    """Copy `request.json` + `input/` onto the worker's remote run directory."""
    ansible(
        inventory_path,
        repo_root,
        host,
        "file",
        f"path={remote_run}/input state=directory mode=0755",
    )
    ansible(
        inventory_path,
        repo_root,
        host,
        "copy",
        f"src={local_run / 'request.json'} dest={remote_run}/request.json mode=0644",
    )
    ansible(
        inventory_path,
        repo_root,
        host,
        "copy",
        f"src={local_run / 'input'}/ dest={remote_run}/input/ mode=0644",
    )


def current_runtime_digest(repo_root: Path, workload_id: str) -> str:
    """The runtime digest (ADR 0073) a worker must advertise for `workload_id`, computed
    from this checkout. A docs-only or web-only commit leaves it unchanged."""
    digests = checkout_runtime_digests(repo_root)
    if workload_id not in digests:
        raise PlatformClientError(f"no runtime digest for unknown workload {workload_id!r}")
    return digests[workload_id]


def declared_max_retries(workload_id: str, override: int | None) -> int:
    """The workload's declared `max_retries`, unless explicitly overridden."""
    if override is not None:
        if override < 0:
            raise PlatformClientError("--max-retries must be non-negative")
        return override
    registered = discover_workloads().get(workload_id)
    if registered is None:
        raise PlatformClientError(f"workload {workload_id!r} is not installed locally")
    return registered.spec.max_retries


def add_retry_argument(parser: Any) -> None:
    parser.add_argument(
        "--max-retries",
        type=int,
        default=None,
        help=(
            "retries after a lost worker or killed work-horse, each on a fresh attempt directory "
            "(default: the workload's declared max_retries; 0 disables)"
        ),
    )


def enqueue_and_wait(
    *,
    broker: Redis,
    worker_id: str,
    remote_run: str,
    run_id: str,
    timeout_seconds: int,
    workload_id: str = "unknown",
    attempt: int = 1,
    retry_of: str | None = None,
    lost_grace: timedelta = DEFAULT_LOST_GRACE,
    advertisement_poll_seconds: float = 10.0,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Enqueue one attempt and wait. Raises `RunLostError` when the worker stops
    advertising for `lost_grace` (the orphaned job is cancelled/stop-requested first),
    `RunFailedError` for any other non-success. RQ's own retry stays off: a retry
    is a new attempt with a new run id and directory (see `retry.py`)."""
    queue = Queue(queue_name(worker_id), connection=broker)
    job = queue.enqueue(
        "networked_players_platform.executor.execute_run",
        remote_run,
        job_id=run_id,
        job_timeout=timeout_seconds,
        result_ttl=604800,
        failure_ttl=2592000,
        retry=None,
        meta={"workload_id": workload_id, "attempt": attempt, "retry_of": retry_of},
    )
    watch = WorkerWatch(worker_id, grace=lost_grace)
    deadline = time.monotonic() + timeout_seconds + 60
    next_check = 0.0
    while time.monotonic() < deadline:
        status = job.get_status(refresh=True)
        if status == JobStatus.FINISHED:
            break
        if status in {JobStatus.FAILED, JobStatus.CANCELED, JobStatus.STOPPED}:
            raise RunFailedError(
                f"remote run ended with status {status.value}: {job.exc_info}",
                retryable=is_retryable_failure(job.exc_info),
            )
        if time.monotonic() >= next_check:
            next_check = time.monotonic() + advertisement_poll_seconds
            if watch.observe(read_advertisements(broker), datetime.now(UTC)):
                _release_orphan(broker, job, status)
                raise RunLostError(
                    f"worker {worker_id} stopped advertising for over "
                    f"{int(lost_grace.total_seconds())}s while job {run_id} was {status.value}; "
                    f"remote run directory {remote_run} may remain on it"
                )
        sleep(2)
    else:
        raise RunFailedError("timed out waiting for remote run completion", retryable=False)

    result = job.result
    if not isinstance(result, dict) or result.get("status") != "succeeded":
        raise RunFailedError("remote run returned no valid success manifest", retryable=False)
    return result


def _release_orphan(broker: Redis, job: Any, status: JobStatus) -> None:
    """Best effort: a queued orphan is cancelled (Redis-side, reliable); a started
    one gets a stop command, which a dead worker never receives."""
    try:
        if status == JobStatus.QUEUED:
            job.cancel()
        elif status == JobStatus.STARTED:
            send_stop_job_command(broker, job.id)
    except Exception as exc:
        print(f"warning: could not release orphaned job {job.id}: {exc}", file=sys.stderr)


def dispatch_with_retries(
    *,
    broker: Redis,
    request: RunRequest,
    local_run: Path,
    inventory_path: Path,
    repo_root: Path,
    hostvars: dict[str, dict[str, Any]],
    min_free_disk_gb: float,
    max_retries: int,
    worker_id_filter: str | None = None,
) -> tuple[RetryOutcome, str, str]:
    """select -> disk preflight -> stage -> enqueue/wait, retried on a lost or killed
    worker. Returns (outcome, inventory host, remote run dir) of the successful attempt.
    Each attempt rewrites `request.json` with its own run id/attempt and stages to its
    own remote directory, so no attempt ever reuses another's output."""
    final: dict[str, Any] = {}

    def select(excluded: frozenset[str]) -> WorkerAdvertisement:
        workers = read_advertisements(broker)
        if worker_id_filter:
            workers = [w for w in workers if w.worker_id == worker_id_filter]
        return select_worker(
            workers,
            request.capabilities,
            workload_id=request.workload_id,
            workload_version=request.workload_version,
            runtime_digest=request.runtime_digest,
            exclude=excluded,
        )

    def run_attempt(
        worker: WorkerAdvertisement, run_id: str, attempt: int, retry_of: str | None
    ) -> dict[str, Any]:
        host = resolve_inventory_host(hostvars, worker.worker_id)
        require_free_disk(
            inventory_path=inventory_path,
            repo_root=repo_root,
            host=host,
            min_free_gb=min_free_disk_gb,
        )
        attempt_request = replace(
            request, run_id=run_id, attempt=attempt, retry_of=retry_of, max_retries=max_retries
        )
        (local_run / "request.json").write_text(
            json.dumps(attempt_request.to_dict(), indent=2, sort_keys=True) + "\n"
        )
        remote_run = f"~/.local/share/networked-players/platform/runs/{run_id}"
        stage_run(
            inventory_path=inventory_path,
            repo_root=repo_root,
            host=host,
            remote_run=remote_run,
            local_run=local_run,
        )
        final.update(host=host, remote_run=remote_run)
        return enqueue_and_wait(
            broker=broker,
            worker_id=worker.worker_id,
            remote_run=remote_run,
            run_id=run_id,
            timeout_seconds=request.timeout_seconds,
            workload_id=request.workload_id,
            attempt=attempt,
            retry_of=retry_of,
        )

    try:
        outcome = run_with_retries(
            base_run_id=request.run_id,
            max_retries=max_retries,
            select=select,
            run_attempt=run_attempt,
        )
    except RetriesExhaustedError as exc:
        raise PlatformClientError(
            f"{exc}\nattempts: {json.dumps([a.to_dict() for a in exc.attempts])}"
        ) from exc
    except NoEligibleWorkerError as exc:
        raise PlatformClientError(str(exc)) from exc
    for orphan in outcome.orphans:
        print(
            f"warning: orphaned attempt {orphan.attempt} ({orphan.run_id}) on worker "
            f"{orphan.worker_id}: {orphan.detail}",
            file=sys.stderr,
        )
    return outcome, str(final["host"]), str(final["remote_run"])


def fetch_and_verify(
    *,
    inventory_path: Path,
    repo_root: Path,
    host: str,
    remote_run: str,
    local_run: Path,
    result: dict[str, Any],
    save_result_json: bool = True,
) -> Path:
    """Fetch every output named in `result["outputs"]`, verify each against
    its own `ArtifactDescriptor` (sha256 + size), and atomically publish
    `local_run/completed/`. `save_result_json` additionally fetches the
    remote `result.json` record for local reference -- every caller except
    `submit_artifact_check.py` wants this (it reads one specific output
    file directly instead)."""
    partial = local_run / ".completed.partial"
    partial.mkdir()
    if save_result_json:
        ansible(
            inventory_path,
            repo_root,
            host,
            "fetch",
            f"src={remote_run}/completed/result.json dest={partial / 'result.json'} flat=yes",
        )
    for output in result["outputs"]:
        descriptor = ArtifactDescriptor(**output)
        destination = partial / descriptor.relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        ansible(
            inventory_path,
            repo_root,
            host,
            "fetch",
            f"src={remote_run}/completed/{descriptor.relative_path} dest={destination} flat=yes",
        )
        actual = describe_artifact(
            partial, descriptor.relative_path, name=descriptor.name, contract=descriptor.contract
        )
        if actual.sha256 != descriptor.sha256 or actual.size_bytes != descriptor.size_bytes:
            raise PlatformClientError(f"fetched output {descriptor.name!r} failed verification")
    completed = local_run / "completed"
    os.replace(partial, completed)
    return completed


def remove_remote_run(*, inventory_path: Path, repo_root: Path, host: str, remote_run: str) -> None:
    """Delete a completed remote run directory -- only call this after a
    successful `fetch_and_verify`, whose content is now safely local and
    verified. Never call this for a failed/timed-out run; those are left
    in place for debugging (see each script's `--keep-remote` flag)."""
    ansible(inventory_path, repo_root, host, "file", f"path={remote_run} state=absent")
