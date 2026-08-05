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
import time
from pathlib import Path
from typing import Any

from redis import Redis
from rq import Queue
from rq.job import JobStatus

from networked_players_platform.broker import queue_name
from networked_players_platform.models import ArtifactDescriptor
from networked_players_platform.staging import describe_artifact


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


def enqueue_and_wait(
    *, broker: Redis, worker_id: str, remote_run: str, run_id: str, timeout_seconds: int
) -> dict[str, Any]:
    queue = Queue(queue_name(worker_id), connection=broker)
    job = queue.enqueue(
        "networked_players_platform.executor.execute_run",
        remote_run,
        job_id=run_id,
        job_timeout=timeout_seconds,
        result_ttl=604800,
        failure_ttl=2592000,
        retry=None,
    )
    deadline = time.monotonic() + timeout_seconds + 60
    while time.monotonic() < deadline:
        status = job.get_status(refresh=True)
        if status == JobStatus.FINISHED:
            break
        if status in {JobStatus.FAILED, JobStatus.CANCELED, JobStatus.STOPPED}:
            raise PlatformClientError(
                f"remote run ended with status {status.value}: {job.exc_info}"
            )
        time.sleep(2)
    else:
        raise PlatformClientError("timed out waiting for remote run completion")

    result = job.result
    if not isinstance(result, dict) or result.get("status") != "succeeded":
        raise PlatformClientError("remote run returned no valid success manifest")
    return result


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
