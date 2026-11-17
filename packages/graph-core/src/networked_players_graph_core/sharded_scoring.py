"""Sharded expansion-candidate scoring (Campaign Atlas I2, ADR 0073 addendum).

Candidates are split by a stable hash of `master_id`; each shard runs the existing
`score_expansion_candidates` UNCHANGED on its subset; the gather verifies that every
shard arrived exactly once and returned exactly its own masters, then restores the
original candidate order. Scoring is per-candidate (the one batched roster query is
only an optimisation), so the merged output is byte-identical to a single-node run:
`scoring_payload` of both has the same `canonical_hash`.

This module is pure with respect to the fleet: it never submits anything. The platform
fan-out (`networked_players_platform.sharding`) drives `score_shard` on workers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from networked_players_platform.sharding import (
    GatherError,
    ShardPlan,
    plan_shards,
    verify_complete,
    verify_shard_keys,
)

from .graph import CreditGraph
from .score_expansion_candidates import score_expansion_candidates


def plan_score_shards(
    job_id: str, candidates: Sequence[dict[str, Any]], shard_count: int
) -> ShardPlan:
    """Shard `candidates` by `master_id`. A duplicate master id is rejected."""
    return plan_shards(job_id, [int(c["master_id"]) for c in candidates], shard_count)


def shard_candidates(
    plan: ShardPlan, candidates: Sequence[dict[str, Any]], index: int
) -> list[dict[str, Any]]:
    """The candidates of shard `index`, in their original relative order."""
    wanted = {int(k) for k in plan.shard(index).keys}
    return [c for c in candidates if int(c["master_id"]) in wanted]


def score_shard(
    graph: CreditGraph, shard: Sequence[dict[str, Any]], **scoring_kwargs: Any
) -> list[dict[str, Any]]:
    """One shard's rows: exactly what the single-node scorer returns for that subset."""
    scoring_kwargs.setdefault("quiet", True)
    return score_expansion_candidates(graph, list(shard), **scoring_kwargs)


def merge_scored_shards(
    plan: ShardPlan, shard_rows: Mapping[int, Sequence[dict[str, Any]]] | Sequence[tuple[int, Any]]
) -> list[dict[str, Any]]:
    """Rows for every candidate in the plan's original order.

    `shard_rows` is a mapping shard index -> rows, or (index, rows) pairs (use pairs
    when duplicates must be detected: a mapping cannot hold one). Raises `GatherError`
    for a missing, duplicated or unexpected shard, or a shard whose rows are not exactly
    its own masters.
    """
    pairs = list(shard_rows.items()) if isinstance(shard_rows, Mapping) else list(shard_rows)
    verify_complete(plan, pairs)
    by_master: dict[int, dict[str, Any]] = {}
    for index, rows in pairs:
        verify_shard_keys(plan, index, [int(row["master_id"]) for row in rows])
        for row in rows:
            by_master[int(row["master_id"])] = row
    if len(by_master) != len(plan.key_order):
        raise GatherError(
            f"merged {len(by_master)} distinct masters for a plan of {len(plan.key_order)}"
        )
    return [by_master[int(key)] for key in plan.key_order]


def scoring_payload(rows: list[dict[str, Any]], candidate_count: int) -> dict[str, Any]:
    """The `score-expansion-candidates` output document, built in one place so a
    single-node run and a gather produce the same bytes."""
    return {
        "candidate_count": candidate_count,
        "eligible_count": sum(1 for row in rows if row["eligibility"] == "eligible"),
        "candidates": rows,
    }
