"""Sharded candidate scoring is byte-identical to a single-node run (Campaign Atlas I2).

Synthetic fixture only. The fleet is simulated in memory: `run_sharded` drives
`score_shard` through the real retry rule, including an injected lost worker.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from typing import Any

import pytest

from conftest import write_synthetic_dataset, write_synthetic_masters
from networked_players_graph_core.graph import CreditGraph
from networked_players_graph_core.score_expansion_candidates import score_expansion_candidates
from networked_players_graph_core.sharded_scoring import (
    merge_scored_shards,
    plan_score_shards,
    score_shard,
    scoring_payload,
    shard_candidates,
)
from networked_players_platform.models import CapabilityRequirement, WorkerAdvertisement
from networked_players_platform.retry import RunLostError, Selector, run_with_retries
from networked_players_platform.scheduler import select_workers
from networked_players_platform.sharding import (
    GatherError,
    ShardPlanError,
    ShardSpec,
    canonical_hash,
    run_sharded,
)
from test_score_expansion_candidates import _credit, _master_row, _release

MASTERS = list(range(900, 930))
NOW = datetime(2026, 11, 17, tzinfo=UTC)
DIGEST = "c" * 64


@pytest.fixture(scope="module")
def graph(tmp_path_factory: pytest.TempPathFactory) -> CreditGraph:
    tmp_path = tmp_path_factory.mktemp("sharded-scoring")
    releases = [_release(m - 890, master_id=m) for m in MASTERS]
    credits = []
    for m in MASTERS:
        release_id = m - 890
        credits.append(
            _credit(
                release_id,
                artist_id=1000 + m,
                name=f"Lead {m}",
                credit_scope="release_artist",
                role_text=None,
            )
        )
        # Shared sidemen so rosters overlap across masters (and so across shards).
        credits.append(
            _credit(
                release_id,
                artist_id=100 + (m % 4),
                name=f"Side {m % 4}",
                credit_scope="track_artist",
                role_text=None,
            )
        )
        if m % 5 == 0:
            credits.append(
                _credit(
                    release_id,
                    artist_id=300,
                    name="Producer",
                    credit_scope="release_credit",
                    role_text="Producer",
                )
            )
    dataset_root = write_synthetic_dataset(
        tmp_path / "snapshot=20260601", release_rows=releases, credit_rows=credits
    )
    masters_root = write_synthetic_masters(
        tmp_path / "masters",
        master_rows=[
            _master_row(
                m,
                main_release_id=m - 890,
                genres=["Rock"] if m % 3 else ["Jazz"],
                year=1960 + m % 40,
            )
            for m in MASTERS
        ],
    )
    g = CreditGraph.open(dataset_root)
    g.attach_masters(masters_root)
    yield g
    g.close()


CANDIDATES: list[dict[str, Any]] = [
    {"master_id": m, "artist_id": 1000 + m, "artist_name": f"Lead {m}", "sample_title": f"T{m}"}
    for m in reversed(MASTERS)  # deliberately not sorted: order must survive the merge
] + [{"master_id": 99999}]  # not in the corpus at all: still scored, as ineligible

KWARGS: dict[str, Any] = {
    "existing_node_ids": frozenset({100, 101, 1000 + 905}),
    "allowed_release_ids": frozenset(m - 890 for m in MASTERS if m != 912),
    "master_exclusions": frozenset({903}),
    "editorial_master_ids": frozenset({900, 929}),
    "private_seed_master_ids": frozenset({915}),
    "underrepresented_buckets": frozenset({("genres", "Jazz"), ("decades", "1980s")}),
    "pathfinding_graph": {
        "node_ids": [100, 101, -1, -2],
        "offsets": [0, 1, 2, 2, 2],
        "neighbors": [2, 3],
    },
}


def _single_node(graph: CreditGraph) -> dict[str, Any]:
    rows = score_expansion_candidates(graph, CANDIDATES, quiet=True, **KWARGS)
    return scoring_payload(rows, len(CANDIDATES))


def _bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


@pytest.mark.parametrize("shard_count", [1, 2, 3, 5, 8, 64])
def test_sharded_scoring_is_byte_identical_to_single_node(
    graph: CreditGraph, shard_count: int
) -> None:
    single = _single_node(graph)
    plan = plan_score_shards("score-job", CANDIDATES, shard_count)
    shard_rows = {
        s.index: score_shard(graph, shard_candidates(plan, CANDIDATES, s.index), **KWARGS)
        for s in plan.active
    }
    merged = scoring_payload(merge_scored_shards(plan, shard_rows), len(CANDIDATES))
    assert _bytes(merged) == _bytes(single)
    assert canonical_hash(merged) == canonical_hash(single)
    # The fixture really exercises the components, not an all-null table.
    eligible = [r for r in single["candidates"] if r["eligibility"] == "eligible"]
    assert len(eligible) > 20 and single["eligible_count"] == len(eligible)
    assert any(r["bridge_span"] for r in eligible) and any(r["coverage_delta"] for r in eligible)
    assert {r["eligibility"] for r in single["candidates"]} > {
        "eligible",
        "curated_master_exclusion",
    }


def test_shard_assignment_does_not_depend_on_candidate_order(graph: CreditGraph) -> None:
    forward = plan_score_shards("j", CANDIDATES, 4)
    backward = plan_score_shards("j", list(reversed(CANDIDATES)), 4)
    assert [set(s.keys) for s in forward.shards] == [set(s.keys) for s in backward.shards]


def _fleet() -> list[WorkerAdvertisement]:
    return [
        WorkerAdvertisement(
            schema_version=2,
            worker_id=worker_id,
            observed_at=NOW.isoformat(),
            architecture="aarch64",
            tags=("graph",),
            total_memory_mb=1024,
            max_job_memory_mb=768,
            runtime_commit="a" * 40,
            workloads={"candidate.score-shard": "1"},
            runtime_digests={"candidate.score-shard": DIGEST},
        )
        for worker_id in ("w-a", "w-b", "w-c")
    ]


def test_fan_out_with_an_injected_lost_worker_still_matches_single_node(
    graph: CreditGraph,
) -> None:
    single = _single_node(graph)
    workers = _fleet()
    requirement = CapabilityRequirement(architectures=("aarch64",), tags=("graph",))
    dead = {"w-a"}  # the first worker dies: every shard placed on it is re-queued
    failures_injected: list[str] = []

    def list_eligible(excluded: frozenset[str], floor: int | None) -> list[Any]:
        return select_workers(
            workers,
            len(workers),
            requirement,
            workload_id="candidate.score-shard",
            workload_version="1",
            runtime_digest=DIGEST,
            now=NOW,
            exclude=excluded,
            memory_above_mb=floor,
        )

    plan = plan_score_shards("score-job", CANDIDATES, 6)
    scoring_lock = threading.Lock()
    outputs: dict[str, list[dict[str, Any]]] = {}  # run_id -> rows (atomic: set on success only)

    def run_one(shard: ShardSpec, select: Selector) -> Any:
        def attempt(worker: Any, run_id: str, n: int, retry_of: Any) -> dict[str, Any]:
            if worker.worker_id in dead:
                failures_injected.append(run_id)
                raise RunLostError(f"{worker.worker_id} advertisement expired")
            with scoring_lock:  # one DuckDB connection stands in for N worker processes
                rows = score_shard(graph, shard_candidates(plan, CANDIDATES, shard.index), **KWARGS)
            outputs[run_id] = rows  # a lost attempt never reached here: nothing partial
            return {"status": "succeeded", "run_id": run_id}

        return run_with_retries(
            base_run_id=shard.run_id, max_retries=2, select=select, run_attempt=attempt
        )

    run = run_sharded(plan, run_one=run_one, list_eligible=list_eligible)
    assert failures_injected, "the fixture must actually lose a shard's first attempt"
    assert any(o.attempt == 2 for o in run.outcomes.values())
    pairs = [(i, outputs[o.run_id]) for i, o in run.outcomes.items()]
    merged = scoring_payload(merge_scored_shards(plan, pairs), len(CANDIDATES))
    assert _bytes(merged) == _bytes(single)
    # Retried attempts wrote under -aN ids, never over the lost attempt's id.
    assert all(run_id not in outputs for run_id in failures_injected)


def test_merge_rejects_missing_duplicate_and_foreign_shards(graph: CreditGraph) -> None:
    plan = plan_score_shards("score-job", CANDIDATES, 4)
    rows = {
        s.index: score_shard(graph, shard_candidates(plan, CANDIDATES, s.index), **KWARGS)
        for s in plan.active
    }
    first = plan.active[0].index
    with pytest.raises(GatherError, match="missing"):
        merge_scored_shards(plan, {i: r for i, r in rows.items() if i != first})
    with pytest.raises(GatherError, match="duplicated"):
        merge_scored_shards(plan, [*rows.items(), (first, rows[first])])
    # A shard that returns another shard's rows (or drops/extra rows) is refused.
    other = plan.active[1].index
    swapped = {**rows, first: rows[other]}
    with pytest.raises(GatherError, match="wrong keys"):
        merge_scored_shards(plan, swapped)
    with pytest.raises(GatherError, match="wrong keys"):
        merge_scored_shards(plan, {**rows, first: rows[first][1:]})


def test_duplicate_master_ids_are_refused_at_planning() -> None:
    with pytest.raises(ShardPlanError, match="duplicate"):
        plan_score_shards("j", [{"master_id": 1}, {"master_id": 1}], 2)
