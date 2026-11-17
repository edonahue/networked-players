#!/usr/bin/env python3
"""Submit sharded expansion-candidate scoring through the capability platform.

Campaign Atlas I2 (ADR 0073 addendum). The candidates are split by a stable hash of
`master_id`; each non-empty shard becomes its own platform job with its own retries on
any eligible worker (a shard whose worker is lost is re-queued on another one); the
gather verifies every shard arrived exactly once and writes the merged output
atomically, byte-identical to a single-node `score-expansion-candidates` run.

`--dry-run` prints the shard plan (and, if JOBS_BROKER_URL is set, the current
eligible workers) and submits nothing, stages nothing and touches no worker.

Status: the worker-side workload (`--workload-id`, default `candidate.score-shard`) is
NOT registered or deployed by this change. Until a plugin registers it, a real
submission stops at "not installed locally" (fail closed). See ADR 0073 addendum.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INVENTORY = REPO_ROOT / "infra/ansible/inventories/local/hosts.yml"
SHARD_OUTPUT = "scored.json"


def _arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, required=True, help="rank-album-candidates")
    parser.add_argument("--shard-count", type=int, required=True)
    parser.add_argument("--job-id", help="lowercase platform identifier (default: generated)")
    parser.add_argument("--workload-id", default="candidate.score-shard")
    parser.add_argument("--snapshot-date", help="discogs-onehop snapshot (needed to submit)")
    parser.add_argument("--pathfinding-graph", type=Path)
    parser.add_argument("--release-format-policy", type=Path)
    parser.add_argument(
        "--scoring-options",
        type=Path,
        help="JSON of the scorer's optional inputs (exclusions, flags, buckets)",
    )
    parser.add_argument("--output", type=Path, help="merged output; must be under local/")
    parser.add_argument("--worker-id", help="restrict every shard to this worker")
    parser.add_argument("--concurrency", type=int, default=None)
    parser.add_argument("--min-free-disk-gb", type=float, default=2.0)
    parser.add_argument("--keep-remote", action="store_true")
    parser.add_argument(
        "--dry-run", action="store_true", help="print the shard plan; submit nothing"
    )
    parser.add_argument("--max-retries", type=int, default=None)
    return parser.parse_args(argv)


def _job_id(args: argparse.Namespace) -> str:
    if args.job_id:
        return str(args.job_id)
    return f"score-shards-{datetime.now(UTC):%Y%m%dt%H%M%sz}-{uuid.uuid4().hex[:8]}"


def _dry_run(args: argparse.Namespace, job_id: str) -> int:
    from networked_players_platform.cli import main as platform_main

    argv = [
        "shards",
        "plan",
        "--keys-file",
        str(args.candidates),
        "--shard-count",
        str(args.shard_count),
        "--job-id",
        job_id,
        "--workload-id",
        args.workload_id,
        "--repo-root",
        str(REPO_ROOT),
    ]
    return platform_main(argv)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    job_id = _job_id(args)
    if args.dry_run:
        return _dry_run(args, job_id)

    # Imported late so --dry-run needs neither Ansible nor a broker.
    from _platform_client import (
        PlatformClientError,
        current_commit,
        current_runtime_digest,
        declared_max_retries,
        dispatch_shards,
        fetch_and_verify,
        inventory_hostvars,
        remove_remote_run,
        require_broker_url,
        require_clean_checkout,
    )
    from redis import Redis

    from networked_players_graph_core.sharded_scoring import (
        merge_scored_shards,
        plan_score_shards,
        scoring_payload,
    )
    from networked_players_platform.models import (
        CapabilityRequirement,
        DatasetIdentity,
        RunRequest,
    )
    from networked_players_platform.sharding import (
        MAX_SHARD_INPUT_BYTES,
        GatherError,
        ShardPlanError,
        canonical_json,
        plan_shards,
        write_atomic,
    )
    from networked_players_platform.staging import describe_artifact

    for required in ("snapshot_date", "pathfinding_graph", "release_format_policy", "output"):
        if getattr(args, required) is None:
            print(f"--{required.replace('_', '-')} is required to submit", file=sys.stderr)
            return 2
    parts = {part for part in args.output.resolve().parts}
    if "local" not in parts:
        print("--output must be under local/ (private scoring rows)", file=sys.stderr)
        return 2

    candidates = json.loads(args.candidates.read_text())
    shared = {
        "pathfinding-graph.json": args.pathfinding_graph,
        "release-format-policy.json": args.release_format_policy,
    }
    if args.scoring_options is not None:
        shared["scoring-options.json"] = args.scoring_options
    shared_bytes = sum(path.stat().st_size for path in shared.values())
    try:
        plan = plan_score_shards(job_id, candidates, args.shard_count)
        # Re-plan with the real byte bound: shared inputs ride along with every shard.
        budget = MAX_SHARD_INPUT_BYTES - shared_bytes
        if budget <= 0:
            raise ShardPlanError("shared inputs alone exceed the per-shard input bound")
        by_master = {int(c["master_id"]): len(json.dumps(c)) for c in candidates}
        plan = plan_shards(
            job_id,
            plan.key_order,
            args.shard_count,
            key_bytes=lambda k: by_master[int(k)],
            max_shard_input_bytes=budget,
        )
    except ShardPlanError as exc:
        print(f"cannot plan: {exc}", file=sys.stderr)
        return 2

    require_clean_checkout(REPO_ROOT)
    commit = current_commit(REPO_ROOT)
    digest = current_runtime_digest(REPO_ROOT, args.workload_id)
    max_retries = declared_max_retries(args.workload_id, args.max_retries)
    from networked_players_platform.workloads import load_workload

    registered = load_workload(args.workload_id)
    assert registered is not None  # declared_max_retries refused otherwise
    spec = registered.spec
    capabilities = CapabilityRequirement(
        architectures=spec.capabilities.architectures,
        tags=spec.capabilities.tags,
        min_memory_mb=spec.capabilities.min_memory_mb,
        datasets=(
            DatasetIdentity(
                name="discogs-onehop",
                snapshot=args.snapshot_date,
                manifest_sha256=_sha256(
                    REPO_ROOT
                    / "local/processed/discogs-onehop"
                    / f"snapshot={args.snapshot_date}"
                    / "manifest.json"
                ),
            ),
        ),
    )

    requests = {}
    for shard in plan.active:
        local_run = REPO_ROOT / "local/platform/runs" / shard.run_id
        input_dir = local_run / "input"
        input_dir.mkdir(parents=True)
        subset = [c for c in candidates if int(c["master_id"]) in {int(k) for k in shard.keys}]
        (input_dir / "candidates.json").write_text(json.dumps(subset, sort_keys=True) + "\n")
        for name, source in shared.items():
            shutil.copy2(source, input_dir / name)
        inputs = tuple(
            describe_artifact(input_dir, name, name=name.removesuffix(".json"), contract=contract)
            for name, contract in (
                ("candidates.json", "rank-album-candidates-local-v1"),
                *((n, "scoring-shared-input-v1") for n in shared),
            )
        )
        request = RunRequest(
            schema_version=2,
            run_id=shard.run_id,
            workload_id=args.workload_id,
            workload_version=spec.version,
            submitted_at=datetime.now(UTC).isoformat(),
            runtime_commit=commit,
            runtime_digest=digest,
            timeout_seconds=spec.default_timeout_seconds,
            max_retries=max_retries,
            capabilities=capabilities,
            inputs=inputs,
            expected_outputs=("scored",),
            parameters={"shard_index": shard.index, "shard_count": shard.shard_count},
        )
        (local_run / "request.json").write_text(
            json.dumps(request.to_dict(), indent=2, sort_keys=True) + "\n"
        )
        requests[shard.index] = (request, local_run)

    broker = Redis.from_url(require_broker_url())
    try:
        run, placements = dispatch_shards(
            broker=broker,
            plan=plan,
            requests=requests,
            inventory_path=INVENTORY,
            repo_root=REPO_ROOT,
            hostvars=inventory_hostvars(INVENTORY, REPO_ROOT),
            min_free_disk_gb=args.min_free_disk_gb,
            max_retries=max_retries,
            worker_id_filter=args.worker_id,
            concurrency=args.concurrency,
        )
        shard_rows = []
        for index, outcome in run.ordered_results():
            host, remote_run = placements[index]
            completed = fetch_and_verify(
                inventory_path=INVENTORY,
                repo_root=REPO_ROOT,
                host=host,
                remote_run=remote_run,
                local_run=requests[index][1],
                result=outcome.result,
            )
            shard_rows.append(
                (index, json.loads((completed / SHARD_OUTPUT).read_text())["candidates"])
            )
            if not args.keep_remote:
                remove_remote_run(
                    inventory_path=INVENTORY, repo_root=REPO_ROOT, host=host, remote_run=remote_run
                )
        merged = scoring_payload(merge_scored_shards(plan, shard_rows), len(candidates))
    except (PlatformClientError, GatherError) as exc:
        print(f"sharded scoring failed: {exc}", file=sys.stderr)
        return 1
    write_atomic(args.output, (json.dumps(merged, indent=2, sort_keys=True) + "\n").encode())
    print(
        json.dumps(
            {
                "job_id": job_id,
                "output": str(args.output),
                "candidate_count": merged["candidate_count"],
                "content_sha256": hashlib.sha256(canonical_json(merged).encode()).hexdigest(),
                "shards": run.report()["shards"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
