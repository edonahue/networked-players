"""Local inspection surface for platform state."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .broker import (
    read_advertisements_checked,
    read_rq_worker_heartbeat,
    redis_from_url,
)
from .jobs import (
    JobBackend,
    RqJobBackend,
    cancel_job,
    filter_records,
    log_locations,
    render_table,
)
from .models import WorkerAdvertisement
from .runtime import heartbeat, run_worker
from .scheduler import DEFAULT_HEARTBEAT_MAX_AGE


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="networked-players-platform")
    subparsers = parser.add_subparsers(dest="command", required=True)
    status = subparsers.add_parser(
        "cluster-status", help="read worker advertisements and compare them with this checkout"
    )
    status.add_argument("--state-dir", type=Path, default=Path("local/platform"))
    status.add_argument("--broker-url")
    status.add_argument("--repo-root", type=Path, default=Path.cwd())
    status.add_argument("--json", action="store_true")
    digests = subparsers.add_parser(
        "runtime-digests", help="print the per-workload runtime digests of a source checkout"
    )
    digests.add_argument("--repo-root", type=Path, default=Path.cwd())
    verify = subparsers.add_parser(
        "verify-wheels",
        help="fail unless the per-workload digests of the built wheels equal the checkout's",
    )
    verify.add_argument("--repo-root", type=Path, default=Path.cwd())
    verify.add_argument("--wheels-dir", type=Path, required=True)
    subparsers.add_parser("heartbeat", help="publish this worker's observed capabilities")
    subparsers.add_parser("worker", help="run the standing RQ worker")

    shards = subparsers.add_parser(
        "shards",
        help="print the shard plan of a keyed job (dry run: reads state, submits nothing)",
    )
    shards_sub = shards.add_subparsers(dest="shards_command", required=True)
    plan = shards_sub.add_parser(
        "plan", help="stable-hash shard split, plus current worker eligibility when a broker is set"
    )
    plan.add_argument("--keys-file", type=Path, required=True)
    plan.add_argument("--shard-count", type=int, required=True)
    plan.add_argument("--job-id", required=True)
    plan.add_argument("--workload-id", help="preview worker assignment for this workload")
    plan.add_argument("--repo-root", type=Path, default=Path.cwd())
    plan.add_argument("--broker-url")
    plan.add_argument("--json", action="store_true")

    jobs = subparsers.add_parser("jobs", help="list, inspect and cancel platform jobs")
    jobs.add_argument("--broker-url")
    jobs.add_argument("--json", action="store_true")
    # Accepted after the subcommand too (`jobs list --json`, as `make platform-jobs`
    # passes ARGS); SUPPRESS keeps a value given before the subcommand from being reset.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--broker-url", default=argparse.SUPPRESS)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    jobs_sub = jobs.add_subparsers(dest="jobs_command", required=True)
    listing = jobs_sub.add_parser(
        "list", help="queued/started/finished/failed jobs", parents=[common]
    )
    listing.add_argument("--worker", help="only this worker id")
    listing.add_argument("--state", help="only this state (queued, started, finished, failed, ...)")
    listing.add_argument("--limit", type=int, default=50, help="max jobs read per state per queue")
    for name, help_text in (
        ("status", "one job's state, timestamps and recorded failure"),
        ("cancel", "cancel a queued job, or request a stop of a started one"),
        ("logs", "where a job's run directory and failure record live on its worker"),
    ):
        sub = jobs_sub.add_parser(name, help=help_text, parents=[common])
        sub.add_argument("job_id")
    return parser


def worker_report(
    worker: WorkerAdvertisement,
    *,
    local_digests: dict[str, str] | None,
    local_contracts_digest: str | None,
) -> dict[str, Any]:
    """Per-worker view including whether each workload digest matches this checkout."""
    workloads: dict[str, Any] = {}
    for workload_id, version in sorted(worker.workloads.items()):
        digest = worker.runtime_digests.get(workload_id)
        if digest is None:
            match = "no-digest"
        elif local_digests is None or workload_id not in local_digests:
            match = "unknown"
        else:
            match = "match" if digest == local_digests[workload_id] else "mismatch"
        workloads[workload_id] = {
            "version": version,
            "runtime_digest": digest,
            "local_runtime_digest": (local_digests or {}).get(workload_id),
            "match": match,
        }
    if not worker.contracts_digest:
        contracts_match = "no-digest"
    elif local_contracts_digest is None:
        contracts_match = "unknown"
    else:
        contracts_match = (
            "match" if worker.contracts_digest == local_contracts_digest else "mismatch"
        )
    return {
        **worker.to_dict(),
        "workload_status": workloads,
        "contracts_match": contracts_match,
    }


def _local_identity(repo_root: Path) -> tuple[dict[str, str] | None, str | None]:
    from .digest import DigestError, checkout_contracts_digest, checkout_runtime_digests

    try:
        return checkout_runtime_digests(repo_root), checkout_contracts_digest(repo_root)
    except (DigestError, OSError):
        return None, None


def _short(value: str | None) -> str:
    return value[:12] if value else "-"


def _cluster_status(
    state_dir: Path, *, broker_url: str | None, repo_root: Path, as_json: bool
) -> int:
    problems: dict[str, str] = {}
    rq_heartbeats: dict[str, str | None] = {}
    if broker_url:
        connection = redis_from_url(broker_url)
        workers, problems = read_advertisements_checked(connection)
        for advertised in workers:
            beat = read_rq_worker_heartbeat(connection, advertised.worker_id)
            rq_heartbeats[advertised.worker_id] = beat.isoformat() if beat else None
    else:
        workers_dir = state_dir / "workers"
        workers = []
        if workers_dir.is_dir():
            for path in sorted(workers_dir.glob("*.json")):
                workers.append(WorkerAdvertisement.from_dict(json.loads(path.read_text())))
    local_digests, local_contracts = _local_identity(repo_root)
    reports = [
        worker_report(w, local_digests=local_digests, local_contracts_digest=local_contracts)
        for w in workers
    ]
    payload = {
        "schema_version": 2,
        "worker_count": len(workers),
        "local_runtime_digests": local_digests,
        "local_contracts_digest": local_contracts,
        "workers": reports,
        "unreadable_advertisements": problems,
        "rq_worker_last_heartbeat": rq_heartbeats,
    }
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    for worker_id, problem in sorted(problems.items()):
        print(f"{worker_id}\tSKIPPED\t{problem}")
    if not workers:
        print("No worker advertisements found.")
        return 0
    now = datetime.now(UTC)
    if local_digests is None:
        print(f"note: no local runtime digests under {repo_root} (is it a checkout with uv.lock?)")
    print("WORKER\tARCH\tACTIVE\tMAX_JOB_MB\tSCHEMA\tCOMMIT\tCONTRACTS\tCONTRACTS_DIGEST\tOBSERVED")
    for worker, report in zip(workers, reports, strict=True):
        observed = datetime.fromisoformat(worker.observed_at).astimezone(UTC)
        stale = " STALE" if now - observed > DEFAULT_HEARTBEAT_MAX_AGE else ""
        print(
            f"{worker.worker_id}\t{worker.architecture}\t{worker.active_jobs}\t"
            f"{worker.max_job_memory_mb}\t{worker.schema_version}\t{worker.runtime_commit[:12]}\t"
            f"{worker.contracts_version or '-'}\t"
            f"{_short(worker.contracts_digest)} ({report['contracts_match']})\t"
            f"{worker.observed_at}{stale}"
            + (
                f"\tRQ worker: {rq_heartbeats.get(worker.worker_id) or 'ABSENT'}"
                if broker_url
                else ""
            )
        )
        for workload_id, info in report["workload_status"].items():
            print(
                f"    {workload_id}@{info['version']}\tdigest {_short(info['runtime_digest'])}"
                f"\t{info['match']}"
                + (
                    f" (local {_short(info['local_runtime_digest'])})"
                    if info["match"] == "mismatch"
                    else ""
                )
            )
    return 0


def _jobs(args: argparse.Namespace, broker_url: str | None, backend: JobBackend | None) -> int:
    if backend is None:
        if not broker_url:
            print("JOBS_BROKER_URL (or --broker-url) is required for `jobs`.")
            return 2
        connection = redis_from_url(broker_url)
        backend = RqJobBackend(connection)
        advertised = [w.worker_id for w in read_advertisements_checked(connection)[0]]
    else:
        advertised = getattr(backend, "advertised_workers", [])
    command = args.jobs_command
    as_json = bool(getattr(args, "json", False))
    if command == "list":
        records = filter_records(
            backend.list_jobs(limit_per_state=args.limit), worker_id=args.worker, state=args.state
        )
        if as_json:
            print(json.dumps([r.to_dict() for r in records], indent=2, sort_keys=True))
        elif not records:
            print("No jobs found.")
        else:
            print(render_table(records))
        return 0
    if command == "cancel":
        outcome = cancel_job(backend, args.job_id, advertised_workers=advertised)
        if as_json:
            print(json.dumps(asdict(outcome), indent=2, sort_keys=True))
        else:
            print(f"{outcome.job_id}: {outcome.action}: {outcome.message}")
        return 0 if outcome.action in {"canceled", "stop-requested"} else 1
    record = backend.get_job(args.job_id)
    if record is None:
        print(f"No such job {args.job_id!r} (expired or never run).")
        return 1
    if command == "status":
        if as_json:
            print(json.dumps(record.to_dict(), indent=2, sort_keys=True))
        else:
            for key, value in record.to_dict().items():
                print(f"{key}: {value}")
        return 0
    if command == "logs":
        info = log_locations(record)
        if as_json:
            print(json.dumps(info, indent=2, sort_keys=True))
        else:
            for key, value in info.items():
                print(f"{key}: {value}")
        return 0
    raise AssertionError(f"unhandled jobs command: {command}")


def load_shard_keys(path: Path) -> list[Any]:
    """Keys from a JSON list of scalars or of {"master_id": ...} objects, or a dict
    holding `master_ids` / `keys` / `candidates`."""
    payload = json.loads(path.read_text())
    if isinstance(payload, dict):
        for name in ("master_ids", "keys", "candidates"):
            if name in payload:
                payload = payload[name]
                break
        else:
            raise ValueError("keys file dict needs one of: master_ids, keys, candidates")
    if not isinstance(payload, list):
        raise ValueError("keys file must hold a JSON list")
    return [item["master_id"] if isinstance(item, dict) else item for item in payload]


def _shards_plan(args: argparse.Namespace, broker_url: str | None) -> int:
    from .digest import DigestError, checkout_runtime_digests
    from .scheduler import NoEligibleWorkerError, select_workers
    from .sharding import ShardPlanError, assign_preview, plan_shards
    from .workloads import load_workload

    try:
        keys = load_shard_keys(args.keys_file)
        plan = plan_shards(args.job_id, keys, args.shard_count)
    except (ShardPlanError, ValueError, OSError) as exc:
        print(f"cannot plan: {exc}")
        return 2
    payload: dict[str, Any] = {"dry_run": True, "plan": plan.to_dict()}
    if args.workload_id and broker_url:
        registered = load_workload(args.workload_id)
        if registered is None:
            payload["assignment_error"] = f"workload {args.workload_id!r} is not installed here"
        else:
            connection = redis_from_url(broker_url)
            advertisements, problems = read_advertisements_checked(connection)
            heartbeats = {
                w.worker_id: read_rq_worker_heartbeat(connection, w.worker_id)
                for w in advertisements
            }
            try:
                digest = checkout_runtime_digests(args.repo_root)[args.workload_id]
                eligible = select_workers(
                    advertisements,
                    len(plan.active) or 1,
                    registered.spec.capabilities,
                    workload_id=args.workload_id,
                    workload_version=registered.spec.version,
                    runtime_digest=digest,
                    rq_heartbeats=heartbeats,
                    problems=problems,
                )
                payload["eligible_workers"] = [w.worker_id for w in eligible]
                payload["assignment_preview"] = {
                    str(k): v for k, v in assign_preview(plan, eligible).items()
                }
            except (NoEligibleWorkerError, DigestError, KeyError) as exc:
                payload["assignment_error"] = str(exc)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"DRY RUN: nothing submitted. job {args.job_id}: {len(plan.key_order)} key(s)")
    print("SHARD\tRUN_ID\tKEYS\tWORKER")
    preview = payload.get("assignment_preview", {})
    for shard in plan.shards:
        worker = preview.get(str(shard.index), "-" if shard.keys else "(empty, not submitted)")
        print(f"{shard.index}\t{shard.run_id}\t{len(shard.keys)}\t{worker}")
    if "assignment_error" in payload:
        print(f"no assignment preview: {payload['assignment_error']}")
    return 0


def main(argv: list[str] | None = None, *, jobs_backend: JobBackend | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "cluster-status":
        broker_url = args.broker_url or os.environ.get("JOBS_BROKER_URL")
        return _cluster_status(
            args.state_dir, broker_url=broker_url, repo_root=args.repo_root, as_json=args.json
        )
    if args.command == "runtime-digests":
        from .digest import checkout_contracts_digest, checkout_runtime_digests, uv_lock_sha256

        payload = {
            "uv_lock_sha256": uv_lock_sha256(args.repo_root),
            "runtime_digests": checkout_runtime_digests(args.repo_root),
            "contracts_digest": checkout_contracts_digest(args.repo_root),
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "verify-wheels":
        import tempfile

        from .digest import verify_wheels

        with tempfile.TemporaryDirectory() as work:
            problems = verify_wheels(args.repo_root, args.wheels_dir, Path(work))
        for problem in problems:
            print(f"WHEEL/CHECKOUT MISMATCH: {problem}")
        if not problems:
            print("wheel digests match the checkout")
        return 1 if problems else 0
    if args.command == "shards":
        return _shards_plan(args, args.broker_url or os.environ.get("JOBS_BROKER_URL"))
    if args.command == "jobs":
        broker_url = args.broker_url or os.environ.get("JOBS_BROKER_URL")
        return _jobs(args, broker_url, jobs_backend)
    if args.command == "heartbeat":
        advertisement = heartbeat()
        print(json.dumps(advertisement.to_dict(), indent=2, sort_keys=True))
        return 0
    if args.command == "worker":
        return 0 if run_worker() else 1
    raise AssertionError(f"unhandled command: {args.command}")
