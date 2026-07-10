"""Local inspection surface for platform state."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .models import WorkerAdvertisement


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="networked-players-platform")
    subparsers = parser.add_subparsers(dest="command", required=True)
    status = subparsers.add_parser("cluster-status", help="read worker advertisements")
    status.add_argument("--state-dir", type=Path, default=Path("local/platform"))
    status.add_argument("--json", action="store_true")
    return parser


def _cluster_status(state_dir: Path, *, as_json: bool) -> int:
    workers_dir = state_dir / "workers"
    workers = []
    if workers_dir.is_dir():
        for path in sorted(workers_dir.glob("*.json")):
            workers.append(WorkerAdvertisement.from_dict(json.loads(path.read_text())))
    payload = {
        "schema_version": 1,
        "worker_count": len(workers),
        "workers": [w.to_dict() for w in workers],
    }
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif not workers:
        print("No worker advertisements found.")
    else:
        print("WORKER\tARCH\tACTIVE\tMAX_JOB_MB\tWORKLOADS")
        for worker in workers:
            print(
                f"{worker.worker_id}\t{worker.architecture}\t{worker.active_jobs}\t"
                f"{worker.max_job_memory_mb}\t{','.join(sorted(worker.workloads))}"
            )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "cluster-status":
        return _cluster_status(args.state_dir, as_json=args.json)
    raise AssertionError(f"unhandled command: {args.command}")
