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

from networked_players_platform.broker import (
    RQ_BUSY_WORKER_TTL_SECONDS,
    RQ_WORKER_TTL_SECONDS,
    queue_name,
    read_advertisements_checked,
    read_rq_worker_heartbeat,
)
from networked_players_platform.digest import checkout_runtime_digests
from networked_players_platform.jobs import classify_failure
from networked_players_platform.models import ArtifactDescriptor, RunRequest, WorkerAdvertisement
from networked_players_platform.retry import (
    DEFAULT_LOST_GRACE,
    RetriesExhaustedError,
    RetryOutcome,
    RunFailedError,
    RunLostError,
    Selector,
    WorkerWatch,
    run_with_retries,
)
from networked_players_platform.scheduler import (
    DEFAULT_HEARTBEAT_MAX_AGE,
    NoEligibleWorkerError,
    select_worker,
    select_workers,
)
from networked_players_platform.sharding import (
    ShardedRun,
    ShardedRunError,
    ShardPlan,
    ShardSpec,
    run_sharded,
)
from networked_players_platform.staging import describe_artifact
from networked_players_platform.workloads import load_workload


class PlatformClientError(RuntimeError):
    """Raised for any real submission-lifecycle failure: missing
    inventory, a dirty checkout, an unreachable/misconfigured broker, a
    failed or timed-out remote run, or a fetched output failing checksum
    verification. `attempts` carries the per-attempt records (including orphans)
    when the failure came out of a retry sequence."""

    def __init__(self, message: str, attempts: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.attempts = attempts or []


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
    registered = load_workload(workload_id)
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
    check_interval_seconds: float = 10.0,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    """Enqueue one attempt and wait. Raises `RunLostError` only when RQ's own liveness
    for the worker (its `rq:worker:<name>` record) has lapsed for `lost_grace` (see
    `WorkerWatch`); the advertisement never causes a lost verdict and a live RQ worker
    is never sent a stop command. `RunFailedError` for any other non-success. RQ's own
    retry stays off: a retry is a new attempt with a new run id and directory."""
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
    # Two explicit points. `deadline` (job timeout + 60 s) is when a timeout DECISION is
    # due, not when the client gives up: a worker that died just after enqueue needs up to
    # RQ's worker TTL plus the grace to be declared lost, which is longer than a short
    # workload's deadline. `hard_end` is therefore the last moment recovery may still
    # run; after `deadline` the client resolves by job status and RQ liveness (below).
    started = monotonic()
    deadline = started + timeout_seconds + 60
    hard_end = deadline + RQ_WORKER_TTL_SECONDS + lost_grace.total_seconds() + 30
    next_check = 0.0
    beat: datetime | None = None
    status: JobStatus | None = None
    try:
        while True:
            status = job.get_status(refresh=True)
            if status == JobStatus.FINISHED:
                break
            if status in {JobStatus.FAILED, JobStatus.CANCELED, JobStatus.STOPPED}:
                kind = classify_failure(job.exc_info)
                raise RunFailedError(
                    f"remote run ended with status {status.value} ({kind}): {job.exc_info}",
                    retryable=kind in {"retryable", "memory-suspect"},
                    memory_suspect=kind == "memory-suspect",
                )
            if monotonic() >= next_check:
                next_check = monotonic() + check_interval_seconds
                now = clock()
                beat = read_rq_worker_heartbeat(broker, worker_id)
                advertisements, _ = read_advertisements_checked(broker)
                fresh = any(
                    ad.worker_id == worker_id
                    and now - datetime.fromisoformat(ad.observed_at) <= DEFAULT_HEARTBEAT_MAX_AGE
                    for ad in advertisements
                )
                if watch.observe(beat, now, advertisement_fresh=fresh):
                    _release_orphan(broker, job, status, worker_id, now)
                    raise RunLostError(
                        f"RQ worker {worker_id} has had no live rq:worker record for over "
                        f"{int(lost_grace.total_seconds())}s (last RQ heartbeat "
                        f"{beat.isoformat() if beat else 'none'}; advertisement "
                        f"{'fresh' if fresh else 'also lapsed'}) while job {run_id} was "
                        f"{status.value}; remote run directory {remote_run} may remain on it"
                    )
            if monotonic() >= deadline:
                _resolve_after_deadline(
                    broker, job, status, worker_id, beat, clock(), run_id, remote_run
                )
                if monotonic() >= hard_end:
                    _release_orphan(broker, job, status, worker_id, clock())
                    raise RunLostError(
                        f"job {run_id} still {status.value} at the end of the recovery "
                        f"window; worker {worker_id} liveness never became decidable"
                    )
            sleep(2)
    except (RunLostError, RunFailedError):
        raise
    except Exception:
        # Abandoning the wait (e.g. a Redis error): release the job before propagating.
        _release_orphan(broker, job, status, worker_id, None)
        raise

    result = job.result
    if not isinstance(result, dict) or result.get("status") != "succeeded":
        raise RunFailedError("remote run returned no valid success manifest", retryable=False)
    return result


def _resolve_after_deadline(
    broker: Redis,
    job: Any,
    status: JobStatus,
    worker_id: str,
    beat: datetime | None,
    now: datetime,
    run_id: str,
    remote_run: str,
) -> None:
    """The timeout decision, made once the deadline has passed (never a bare give-up):

    - QUEUED: the job never started. Cancel it (Redis-side, safe) and raise
      `RunLostError` so a retry can re-dispatch to another worker.
    - STARTED, RQ worker live (heartbeat within 90 s): a genuine timeout. RQ's own
      job_timeout kills the job;
      also ask for a stop, and fail non-retryably (a slow job would only be slow again).
    - STARTED, RQ worker not live: not decidable yet. Return and keep watching;
      `WorkerWatch` declares the loss after the grace, and `hard_end` bounds the wait.
    """
    # A running job's worker refreshes its record every ~30 s, so "live" is strict here.
    ttl = timedelta(seconds=RQ_BUSY_WORKER_TTL_SECONDS)
    if status == JobStatus.QUEUED:
        _release_orphan(broker, job, status, worker_id, now)
        raise RunLostError(
            f"job {run_id} was still queued after the deadline (never started); cancelled "
            f"so it can be re-dispatched; remote run directory {remote_run} was only staged"
        )
    live = beat is not None and now - beat <= ttl
    if status == JobStatus.STARTED and live:
        try:
            send_stop_job_command(broker, job.id)
        except Exception as exc:
            print(f"warning: could not stop timed-out job {job.id}: {exc}", file=sys.stderr)
        raise RunFailedError("timed out waiting for remote run completion", retryable=False)


def _release_orphan(
    broker: Redis, job: Any, status: JobStatus | None, worker_id: str, now: datetime | None
) -> None:
    """Best effort. A queued job is cancelled (Redis-side, always safe). A started job
    is sent a stop command ONLY when RQ's liveness for its worker has just been
    re-read and is lapsed; if the worker is live, or liveness cannot be read (for
    example because Redis itself failed), the job is left running and reported, since
    stopping a healthy job is worse than orphaning a result nobody fetches."""
    try:
        if status == JobStatus.QUEUED:
            job.cancel()
        elif status == JobStatus.STARTED:
            beat = read_rq_worker_heartbeat(broker, worker_id)
            current = now or datetime.now(UTC)
            if beat is not None and current - beat <= timedelta(seconds=RQ_WORKER_TTL_SECONDS):
                print(
                    f"note: not stopping {job.id}: RQ worker {worker_id} is live",
                    file=sys.stderr,
                )
            elif now is None:
                print(
                    f"warning: job {job.id} left running; liveness unknown after an error",
                    file=sys.stderr,
                )
            else:
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
    select_override: Selector | None = None,
) -> tuple[RetryOutcome, str, str]:
    """select -> disk preflight -> stage -> enqueue/wait, retried on a lost or killed
    worker. Returns (outcome, inventory host, remote run dir) of the successful attempt.
    Each attempt rewrites `request.json` with its own run id/attempt and stages to its
    own remote directory, so no attempt ever reuses another's output.
    `select_override` lets a shard fan-out choose the worker (still from the same
    eligibility rules, see `list_eligible_workers`)."""
    final: dict[str, Any] = {}

    def select(excluded: frozenset[str], memory_floor: int | None) -> WorkerAdvertisement:
        workers, problems = read_advertisements_checked(broker)
        if worker_id_filter:
            workers = [w for w in workers if w.worker_id == worker_id_filter]
            problems = {k: v for k, v in problems.items() if k == worker_id_filter}
        # A fresh advertisement alone is not enough: the RQ worker must be running too.
        rq_heartbeats = {
            w.worker_id: read_rq_worker_heartbeat(broker, w.worker_id) for w in workers
        }
        return select_worker(
            workers,
            request.capabilities,
            workload_id=request.workload_id,
            workload_version=request.workload_version,
            runtime_digest=request.runtime_digest,
            exclude=excluded,
            rq_heartbeats=rq_heartbeats,
            problems=problems,
            memory_above_mb=memory_floor,
        )

    chosen_select: Selector = select_override if select_override is not None else select

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
            select=chosen_select,
            run_attempt=run_attempt,
        )
    except RetriesExhaustedError as exc:
        raise PlatformClientError(
            f"{exc}\nattempts: {json.dumps([a.to_dict() for a in exc.attempts])}",
            attempts=[a.to_dict() for a in exc.attempts],
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


def list_eligible_workers(
    broker: Redis, request: RunRequest, *, worker_id_filter: str | None = None
) -> Callable[[frozenset[str], int | None], list[WorkerAdvertisement]]:
    """`select_workers` over live advertisements and RQ liveness, as the `ListEligible`
    callable `sharding.run_sharded` needs: every eligible worker, least-loaded first,
    minus `excluded` (workers already tried by a retry)."""

    def list_eligible(
        excluded: frozenset[str], memory_floor: int | None
    ) -> list[WorkerAdvertisement]:
        workers, problems = read_advertisements_checked(broker)
        if worker_id_filter:
            workers = [w for w in workers if w.worker_id == worker_id_filter]
            problems = {k: v for k, v in problems.items() if k == worker_id_filter}
        rq_heartbeats = {
            w.worker_id: read_rq_worker_heartbeat(broker, w.worker_id) for w in workers
        }
        return select_workers(
            workers,
            max(len(workers), 1),
            request.capabilities,
            workload_id=request.workload_id,
            workload_version=request.workload_version,
            runtime_digest=request.runtime_digest,
            exclude=excluded,
            rq_heartbeats=rq_heartbeats,
            problems=problems,
            memory_above_mb=memory_floor,
        )

    return list_eligible


def dispatch_shards(
    *,
    broker: Redis,
    plan: ShardPlan,
    requests: dict[int, tuple[RunRequest, Path]],
    inventory_path: Path,
    repo_root: Path,
    hostvars: dict[str, dict[str, Any]],
    min_free_disk_gb: float,
    max_retries: int,
    worker_id_filter: str | None = None,
    concurrency: int | None = None,
) -> tuple[ShardedRun, dict[int, tuple[str, str]]]:
    """Fan a sharded job out: one `dispatch_with_retries` per active shard (its own run
    id, its own staging, its own retry budget), spread over distinct eligible workers.
    A shard whose worker is lost is re-queued on another eligible worker by the same
    retry rule a single job uses. `requests` maps shard index -> (request, local run
    dir) for every active shard. Returns the run and shard index -> (host, remote run).
    Raises `PlatformClientError` if any shard cannot complete (completed shards are
    left staged remotely and fetched by nobody: re-run the whole job)."""
    missing = sorted(shard.index for shard in plan.active if shard.index not in requests)
    if missing:
        raise PlatformClientError(f"no request prepared for shard(s) {missing}")
    placements: dict[int, tuple[str, str]] = {}
    template = requests[plan.active[0].index][0]

    def run_one(shard: ShardSpec, select: Selector) -> RetryOutcome:
        request, local_run = requests[shard.index]
        outcome, host, remote_run = dispatch_with_retries(
            broker=broker,
            request=request,
            local_run=local_run,
            inventory_path=inventory_path,
            repo_root=repo_root,
            hostvars=hostvars,
            min_free_disk_gb=min_free_disk_gb,
            max_retries=max_retries,
            worker_id_filter=worker_id_filter,
            select_override=select,
        )
        placements[shard.index] = (host, remote_run)
        return outcome

    try:
        run = run_sharded(
            plan,
            run_one=run_one,
            list_eligible=list_eligible_workers(
                broker, template, worker_id_filter=worker_id_filter
            ),
            concurrency=concurrency,
        )
    except ShardedRunError as exc:
        raise PlatformClientError(str(exc)) from exc
    except NoEligibleWorkerError as exc:
        raise PlatformClientError(str(exc)) from exc
    return run, placements
