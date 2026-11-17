"""Shard planning, worker selection, fan-out and gather (Campaign Atlas I2).

Pure in-memory: no Redis, RQ, Ansible or worker is touched.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from networked_players_platform.cli import main as cli_main
from networked_players_platform.models import CapabilityRequirement, WorkerAdvertisement
from networked_players_platform.retry import (
    RetriesExhaustedError,
    RetryOutcome,
    RunFailedError,
    RunLostError,
    Selector,
    run_with_retries,
)
from networked_players_platform.scheduler import (
    NoEligibleWorkerError,
    select_worker,
    select_workers,
)
from networked_players_platform.sharding import (
    GatherError,
    ShardedRunError,
    ShardPlanError,
    ShardSpec,
    assign_preview,
    canonical_hash,
    plan_shards,
    run_sharded,
    shard_for_key,
    verify_complete,
    verify_shard_keys,
    write_atomic,
)

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
DIGEST = "d" * 64
OTHER_DIGEST = "e" * 64
COMMIT = "a" * 40


def _ad(
    worker_id: str,
    *,
    memory: int = 768,
    digest: str = DIGEST,
    active: int = 0,
    workload: str = "score.shard",
) -> WorkerAdvertisement:
    return WorkerAdvertisement(
        schema_version=2,
        worker_id=worker_id,
        observed_at=NOW.isoformat(),
        architecture="aarch64",
        tags=("graph",),
        total_memory_mb=1024,
        max_job_memory_mb=memory,
        runtime_commit=COMMIT,
        workloads={workload: "1"},
        runtime_digests={workload: digest},
        active_jobs=active,
    )


REQ = CapabilityRequirement(architectures=("aarch64",), tags=("graph",), min_memory_mb=512)


def _select(workers: list[WorkerAdvertisement], n: int, **kwargs: Any) -> list[WorkerAdvertisement]:
    return select_workers(
        workers,
        n,
        REQ,
        workload_id="score.shard",
        workload_version="1",
        runtime_digest=DIGEST,
        now=NOW,
        **kwargs,
    )


# --- select_workers ------------------------------------------------------------------


def test_select_workers_returns_up_to_n_distinct_least_loaded_first() -> None:
    workers = [_ad("w-c", active=2), _ad("w-a", active=1), _ad("w-b", active=0)]
    assert [w.worker_id for w in _select(workers, 2)] == ["w-b", "w-a"]
    assert [w.worker_id for w in _select(workers, 9)] == ["w-b", "w-a", "w-c"]


def test_select_workers_ties_break_by_worker_id_and_select_worker_agrees() -> None:
    workers = [_ad("w-b"), _ad("w-a")]
    assert [w.worker_id for w in _select(workers, 2)] == ["w-a", "w-b"]
    single = select_worker(
        workers,
        REQ,
        workload_id="score.shard",
        workload_version="1",
        runtime_digest=DIGEST,
        now=NOW,
    )
    assert single.worker_id == "w-a"


def test_select_workers_refuses_digest_skew_and_low_memory_never_relaxing_either() -> None:
    workers = [
        _ad("w-ok"),
        _ad("w-skewed", digest=OTHER_DIGEST),
        _ad("w-small", memory=256),
    ]
    assert [w.worker_id for w in _select(workers, 3)] == ["w-ok"]
    with pytest.raises(NoEligibleWorkerError) as exc:
        _select([workers[1], workers[2]], 2)
    assert "runtime digest mismatch" in "; ".join(exc.value.reasons["w-skewed"])
    assert "below required 512 MB" in "; ".join(exc.value.reasons["w-small"])


def test_select_workers_honours_exclude_and_rq_liveness_and_rejects_bad_n() -> None:
    workers = [_ad("w-a"), _ad("w-b"), _ad("w-c")]
    chosen = _select(
        workers,
        3,
        exclude=frozenset({"w-a"}),
        rq_heartbeats={"w-a": NOW, "w-b": NOW, "w-c": None},
    )
    assert [w.worker_id for w in chosen] == ["w-b"]
    with pytest.raises(ValueError):
        _select(workers, 0)


# --- planning ------------------------------------------------------------------------


def test_shard_hash_is_stable_across_runs_and_independent_of_input_order() -> None:
    # A pinned value: any change to the hashing silently re-partitions every future plan.
    assert [shard_for_key(k, 4) for k in (900, 901, 902, "x")] == [
        shard_for_key(900, 4),
        shard_for_key("901", 4),
        shard_for_key(902, 4),
        shard_for_key("x", 4),
    ]
    assert shard_for_key(12345, 7) == 6
    keys = list(range(1000, 1200))
    forward = plan_shards("job-a", keys, 5)
    backward = plan_shards("job-a", list(reversed(keys)), 5)
    assert [set(s.keys) for s in forward.shards] == [set(s.keys) for s in backward.shards]
    assert sorted(k for s in forward.shards for k in s.keys) == keys


def test_plan_rejects_duplicates_bad_counts_bad_ids_and_oversized_shards() -> None:
    with pytest.raises(ShardPlanError, match="duplicate"):
        plan_shards("job", [1, 2, 2], 2)
    with pytest.raises(ShardPlanError):
        plan_shards("job", [1], 0)
    with pytest.raises(ShardPlanError):
        plan_shards("Bad Job", [1], 2)
    with pytest.raises(ShardPlanError, match="more shards"):
        plan_shards("job", [1, 2, 3], 1, key_bytes=lambda k: 100, max_shard_input_bytes=250)
    # The cure the error names works.
    ok = plan_shards("job", [1, 2, 3], 8, key_bytes=lambda k: 100, max_shard_input_bytes=250)
    assert max(s.input_bytes for s in ok.shards) <= 250


def test_empty_shards_are_not_active_and_run_ids_are_unique_and_valid() -> None:
    plan = plan_shards("job-x", [1, 2], 16)
    assert len(plan.shards) == 16
    assert 1 <= len(plan.active) <= 2
    ids = [s.run_id for s in plan.shards]
    assert len(set(ids)) == 16
    from networked_players_platform.models import _identifier  # type: ignore[attr-defined]

    for run_id in ids:
        _identifier(run_id + "-a3", "run_id")


def test_assign_preview_is_round_robin_over_active_shards() -> None:
    plan = plan_shards("job", list(range(40)), 4)
    preview = assign_preview(plan, [_ad("w-a"), _ad("w-b")])
    workers = [preview[s.index] for s in plan.active]
    assert workers == ["w-a", "w-b", "w-a", "w-b"][: len(workers)]
    assert assign_preview(plan, []) == {s.index: None for s in plan.active}


# --- gather --------------------------------------------------------------------------


def test_verify_complete_orders_by_shard_index_and_requires_exactly_once() -> None:
    plan = plan_shards("job", list(range(40)), 3)
    indexes = [s.index for s in plan.active]
    shuffled = [(i, f"payload-{i}") for i in reversed(indexes)]
    assert verify_complete(plan, shuffled) == [f"payload-{i}" for i in indexes]

    with pytest.raises(GatherError) as missing:
        verify_complete(plan, shuffled[1:])
    assert missing.value.missing == (indexes[-1],) or len(missing.value.missing) == 1
    with pytest.raises(GatherError) as dup:
        verify_complete(plan, [*shuffled, shuffled[0]])
    assert dup.value.duplicates
    with pytest.raises(GatherError) as extra:
        verify_complete(plan, [*shuffled, (99, "stray")])
    assert extra.value.unexpected == (99,)


def test_verify_shard_keys_rejects_missing_extra_and_foreign_keys() -> None:
    plan = plan_shards("job", list(range(40)), 3)
    shard = plan.active[0]
    verify_shard_keys(plan, shard.index, list(reversed(shard.keys)))
    with pytest.raises(GatherError):
        verify_shard_keys(plan, shard.index, list(shard.keys)[1:])
    with pytest.raises(GatherError):
        verify_shard_keys(plan, shard.index, [*shard.keys, 10_000])


def test_write_atomic_replaces_whole_file_and_leaves_no_partial(tmp_path: Path) -> None:
    target = tmp_path / "out" / "merged.json"
    write_atomic(target, b"one")
    write_atomic(target, b"two")
    assert target.read_bytes() == b"two"
    assert [p.name for p in target.parent.iterdir()] == ["merged.json"]


def test_canonical_hash_ignores_key_order() -> None:
    assert canonical_hash({"a": 1, "b": [1, 2]}) == canonical_hash({"b": [1, 2], "a": 1})
    assert canonical_hash([1, 2]) != canonical_hash([2, 1])


# --- fan-out -------------------------------------------------------------------------


class Fleet:
    """In-memory fleet: advertisements, a set of dead workers and a per-shard script."""

    def __init__(self, workers: list[WorkerAdvertisement]) -> None:
        self.workers = workers
        self.dead: set[str] = set()
        self.lock = threading.Lock()
        self.attempts: list[tuple[int, str, str, int]] = []  # shard, run_id, worker, attempt
        self.fail_with: dict[int, Exception] = {}

    def list_eligible(self, excluded: frozenset[str], floor: int | None) -> list[Any]:
        return select_workers(
            self.workers,
            len(self.workers),
            REQ,
            workload_id="score.shard",
            workload_version="1",
            runtime_digest=DIGEST,
            now=NOW,
            exclude=excluded,
            memory_above_mb=floor,
        )

    def run_one(self, max_retries: int) -> Any:
        def run_one(shard: ShardSpec, select: Selector) -> Any:
            def run_attempt(worker: Any, run_id: str, attempt: int, retry_of: Any) -> Any:
                with self.lock:
                    self.attempts.append((shard.index, run_id, worker.worker_id, attempt))
                if worker.worker_id in self.dead:
                    raise RunLostError(f"{worker.worker_id} lost")
                if shard.index in self.fail_with:
                    raise self.fail_with[shard.index]
                return {"status": "succeeded", "shard": shard.index, "worker": worker.worker_id}

            return run_with_retries(
                base_run_id=shard.run_id,
                max_retries=max_retries,
                select=select,
                run_attempt=run_attempt,
            )

        return run_one


def test_run_sharded_spreads_shards_over_workers_and_gathers_in_order() -> None:
    fleet = Fleet([_ad("w-a"), _ad("w-b"), _ad("w-c")])
    plan = plan_shards("job", list(range(60)), 6)
    run = run_sharded(plan, run_one=fleet.run_one(1), list_eligible=fleet.list_eligible)
    gathered = verify_complete(plan, run.ordered_results())
    assert [g["shard"] for g in gathered] == [s.index for s in plan.active]
    assert len({a[2] for a in fleet.attempts}) == 3  # all three workers used
    assert all(a[3] == 1 for a in fleet.attempts)


def test_lost_worker_shard_is_requeued_on_another_worker_with_a_fresh_run_id() -> None:
    fleet = Fleet([_ad("w-a"), _ad("w-b")])
    fleet.dead = {"w-a"}
    plan = plan_shards("job", list(range(60)), 4)
    run = run_sharded(plan, run_one=fleet.run_one(1), list_eligible=fleet.list_eligible)
    verify_complete(plan, run.ordered_results())
    retried = [a for a in fleet.attempts if a[3] == 2]
    assert retried, "at least one shard must have been on the dead worker first"
    for shard_index, run_id, worker, _ in retried:
        assert worker == "w-b"
        assert run_id == f"{plan.shard(shard_index).run_id}-a2"
    for outcome in run.outcomes.values():
        assert outcome.worker.worker_id == "w-b"
    assert "attempts" in run.report()["shards"][0]


def test_lost_worker_with_no_retries_left_fails_that_shard_but_keeps_the_others() -> None:
    fleet = Fleet([_ad("w-a"), _ad("w-b")])
    fleet.dead = {"w-a"}
    plan = plan_shards("job", list(range(60)), 4)
    with pytest.raises(ShardedRunError) as exc:
        run_sharded(plan, run_one=fleet.run_one(0), list_eligible=fleet.list_eligible)
    assert exc.value.failures
    assert set(exc.value.failures) | set(exc.value.completed) == {s.index for s in plan.active}
    assert all("RetriesExhaustedError" in why for why in exc.value.failures.values())


def test_deterministic_failure_is_not_retried_and_never_picks_a_second_worker() -> None:
    fleet = Fleet([_ad("w-a"), _ad("w-b")])
    plan = plan_shards("job", list(range(10)), 2)
    victim = plan.active[0].index
    fleet.fail_with[victim] = RunFailedError("boom", retryable=False)
    with pytest.raises(ShardedRunError):
        run_sharded(plan, run_one=fleet.run_one(3), list_eligible=fleet.list_eligible)
    assert [a for a in fleet.attempts if a[0] == victim] == [
        a for a in fleet.attempts if a[0] == victim and a[3] == 1
    ]


def test_no_eligible_worker_fails_up_front_without_attempting_anything() -> None:
    fleet = Fleet([_ad("w-a", digest=OTHER_DIGEST)])
    plan = plan_shards("job", list(range(10)), 2)
    with pytest.raises(NoEligibleWorkerError):
        run_sharded(plan, run_one=fleet.run_one(1), list_eligible=fleet.list_eligible)
    assert fleet.attempts == []


def test_all_workers_lost_exhausts_retries_with_attempt_records() -> None:
    fleet = Fleet([_ad("w-a"), _ad("w-b")])
    fleet.dead = {"w-a", "w-b"}
    plan = plan_shards("job", [1], 1)
    with pytest.raises(ShardedRunError) as exc:
        run_sharded(plan, run_one=fleet.run_one(5), list_eligible=fleet.list_eligible)
    assert "no worker left" in str(exc.value) or "RetriesExhaustedError" in str(exc.value)
    assert isinstance(RetriesExhaustedError("x", []), RuntimeError)


def test_concurrency_never_exceeds_the_eligible_worker_count() -> None:
    fleet = Fleet([_ad("w-a"), _ad("w-b")])
    state = {"in_flight": 0, "peak": 0}
    lock = threading.Lock()

    def run_one(shard: ShardSpec, select: Selector) -> RetryOutcome:
        worker = select(frozenset(), None)
        with lock:
            state["in_flight"] += 1
            state["peak"] = max(state["peak"], state["in_flight"])
        time.sleep(0.02)
        with lock:
            state["in_flight"] -= 1
        return RetryOutcome({"status": "succeeded"}, worker, shard.run_id, 1)

    plan = plan_shards("job", list(range(80)), 8)
    run_sharded(plan, run_one=run_one, list_eligible=fleet.list_eligible)
    assert 1 <= state["peak"] <= 2


# --- CLI -----------------------------------------------------------------------------


def test_shards_plan_cli_is_a_dry_run_that_prints_the_plan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    keys = tmp_path / "candidates.json"
    keys.write_text(json.dumps([{"master_id": i, "artist_name": "x"} for i in range(30)]))
    code = cli_main(
        [
            "shards",
            "plan",
            "--keys-file",
            str(keys),
            "--shard-count",
            "3",
            "--job-id",
            "dry-job",
            "--json",
        ]
    )
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["dry_run"] is True
    assert out["plan"]["key_count"] == 30
    assert sum(s["key_count"] for s in out["plan"]["shards"]) == 30
    assert "assignment_preview" not in out  # no broker given: nothing was read

    code = cli_main(
        ["shards", "plan", "--keys-file", str(keys), "--shard-count", "3", "--job-id", "dry-job"]
    )
    text = capsys.readouterr().out
    assert code == 0 and text.startswith("DRY RUN: nothing submitted")


def test_shards_plan_cli_rejects_duplicates(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    keys = tmp_path / "k.json"
    keys.write_text(json.dumps({"master_ids": [1, 1]}))
    code = cli_main(
        ["shards", "plan", "--keys-file", str(keys), "--shard-count", "2", "--job-id", "j"]
    )
    assert code == 2
    assert "duplicate" in capsys.readouterr().out


def test_submit_script_dry_run_prints_the_plan_and_submits_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    monkeypatch.delenv("JOBS_BROKER_URL", raising=False)
    scripts = str(Path(__file__).resolve().parents[3] / "scripts")
    monkeypatch.syspath_prepend(scripts)
    sys.modules.pop("submit_sharded_score", None)
    import submit_sharded_score

    candidates = tmp_path / "c.json"
    candidates.write_text(json.dumps([{"master_id": i} for i in range(12)]))
    code = submit_sharded_score.main(
        ["--candidates", str(candidates), "--shard-count", "4", "--job-id", "dry-1", "--dry-run"]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert out.startswith("DRY RUN: nothing submitted") and "dry-1-s000of004" in out


def test_balancer_never_double_books_a_worker_even_when_a_retry_needs_one() -> None:
    """Shard A is lost on w-a and retries. w-b holds shard B, so A must WAIT for it to
    free up instead of stacking behind B (where its deadline would run un-started)."""
    from networked_players_platform.sharding import ShardBalancer

    fleet = Fleet([_ad("w-a"), _ad("w-b")])
    balancer = ShardBalancer(fleet.list_eligible, poll_seconds=0.01)
    pick_a = balancer.selector(0, 0)
    pick_b = balancer.selector(1, 1)
    first = pick_a(frozenset(), None)
    held_by_b = pick_b(frozenset(), None)
    assert {first.worker_id, held_by_b.worker_id} == {"w-a", "w-b"}

    got: list[str] = []
    thread = threading.Thread(
        target=lambda: got.append(pick_a(frozenset({first.worker_id}), None).worker_id)
    )
    thread.start()
    time.sleep(0.1)
    assert got == [], "retry must wait while the only other worker is occupied"
    balancer.release(1)  # shard B finishes
    thread.join(timeout=5)
    assert got == [held_by_b.worker_id]
    # And nothing is ever double-booked.
    assert max(balancer._in_flight.values()) == 1  # type: ignore[attr-defined]


def test_balancer_gives_up_with_a_clear_error_if_no_worker_ever_frees() -> None:
    from networked_players_platform.sharding import ShardBalancer

    fleet = Fleet([_ad("w-a")])
    balancer = ShardBalancer(fleet.list_eligible, poll_seconds=0.01, max_wait_seconds=0.05)
    balancer.selector(0, 0)(frozenset(), None)
    with pytest.raises(TimeoutError, match="no unoccupied eligible worker"):
        balancer.selector(1, 1)(frozenset(), None)


def test_submit_script_output_guard_accepts_only_this_repos_local_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    scripts = str(Path(__file__).resolve().parents[3] / "scripts")
    monkeypatch.syspath_prepend(scripts)
    sys.modules.pop("submit_sharded_score", None)
    import submit_sharded_score as script

    repo = script.REPO_ROOT
    assert script._is_local_output(repo / "local" / "analysis" / "x.json")
    assert not script._is_local_output(Path("/usr/local/share/x.json"))
    assert not script._is_local_output(repo / "apps" / "web" / "local" / "x.json")
    assert not script._is_local_output(repo / "local" / ".." / "apps" / "x.json")
    import re

    job_id = script._job_id(type("A", (), {"job_id": None})())
    assert re.fullmatch(r"score-shards-\d{8}t\d{6}z-[0-9a-f]{8}", job_id)
