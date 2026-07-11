"""Shared whole-cohort scoring operation for CLI and platform workers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .cohort_connectivity import (
    DEFAULT_MAX_REACH_ROWS,
    build_connectivity_cohort,
    summarize_connectivity,
    validate_connectivity,
    write_connectivity_cohort,
)
from .graph import CreditGraph


def score_cohort_to_directory(
    *,
    resolved_path: Path,
    dataset_path: Path,
    output_dir: Path,
    memory_limit: str = "2GB",
    threads: int = 3,
    max_artists_per_release: int = 500,
    temp_dir: Path | None = None,
    max_hops: int = 3,
    max_pairs: int = 1000,
    max_frontier_expansion: int | None = 300,
    pair_timeout_seconds: float | None = 180.0,
    max_workers: int = 1,
    max_reach_rows: int = DEFAULT_MAX_REACH_ROWS,
    release_format_policy: Path | None = None,
) -> dict[str, Any]:
    """Score one resolved cohort and write its four local review artifacts."""
    resolved = json.loads(resolved_path.read_text())
    dataset_manifest = json.loads((dataset_path / "manifest.json").read_text())
    diagnostics: dict[str, Any] = {}
    policy_name = None
    if release_format_policy is not None:
        policy_name = json.loads(Path(release_format_policy).read_text()).get("policy_name")

    with CreditGraph.open(
        dataset_path,
        memory_limit=memory_limit,
        threads=threads,
        max_artists_per_release=max_artists_per_release,
        temp_dir=temp_dir,
        release_format_policy=release_format_policy,
    ) as graph:
        connectivity_artifact = build_connectivity_cohort(
            graph,
            resolved,
            dataset_snapshot_date=str(dataset_manifest["snapshot_date"]),
            max_hops=max_hops,
            max_pairs=max_pairs,
            max_frontier_expansion=max_frontier_expansion,
            pair_timeout_seconds=pair_timeout_seconds,
            max_workers=max_workers,
            max_reach_rows=max_reach_rows,
            duckdb_settings={
                "memory_limit": memory_limit,
                "threads": threads,
                "custom_temp_dir": temp_dir is not None,
                "release_format_policy": policy_name,
            },
            diagnostics=diagnostics,
        )
    diagnostics["params"] = connectivity_artifact["scoring_params"]
    validate_connectivity(connectivity_artifact)
    playable_pairs, report_markdown = summarize_connectivity(connectivity_artifact)

    output_dir.mkdir(parents=True, exist_ok=True)
    write_connectivity_cohort(connectivity_artifact, output_dir / "connectivity.json")
    (output_dir / "playable-pairs.json").write_text(
        json.dumps(playable_pairs, indent=2, sort_keys=True) + "\n"
    )
    (output_dir / "review-report.md").write_text(report_markdown)
    (output_dir / "scoring-diagnostics.json").write_text(
        json.dumps(diagnostics, indent=2, sort_keys=True) + "\n"
    )

    by_status = {"found": 0, "no_path": 0, "skipped": 0}
    by_difficulty = {"easy": 0, "medium": 0, "hard": 0, "very_hard": 0}
    flagged_pair_count = 0
    for pair in connectivity_artifact["pairs"]:
        by_status[pair["status"]] += 1
        if pair["status"] == "found":
            by_difficulty[pair["difficulty"]] += 1
        if pair["warnings"]:
            flagged_pair_count += 1

    return {
        "output_dir": str(output_dir),
        "pair_count": len(connectivity_artifact["pairs"]),
        "by_status": by_status,
        "by_difficulty": by_difficulty,
        "flagged_pair_count": flagged_pair_count,
        "wall_s": diagnostics.get("wall_s"),
        "reach_total_rows": diagnostics.get("reach_total_rows"),
        "peak_rss_mb": (diagnostics.get("rss_mb") or {}).get("after_expansion"),
    }
