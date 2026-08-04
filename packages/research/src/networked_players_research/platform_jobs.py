"""Research domain workload registered with the generic platform (Phase 3
Slice E) -- mirrors `networked_players_catalog.platform_jobs`'s
`cohort_score_workload` shape exactly: a `RegisteredWorkload` discovered
via the `networked_players.workloads` entry point group, x86-preferred/
heavy.

Deliberately scoped to a bounded degree-distribution *metric*, not the
fuller community-detection/bridge-analysis primitives Slice D already
runs locally with igraph (`graph_analysis.py`) -- those stay an
interactive/local step per ADR 0054's research-lane discipline; dispatch
here is about a repeatable, boundable structural metric over a topic
corpus's real co-credit edges (`graph_bench.load_edges`, the same
production `credit_edges_sql` semantics), not full offline analytics.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from networked_players_platform.models import (
    ArtifactDescriptor,
    CapabilityRequirement,
    RunRequest,
    WorkloadSpec,
)
from networked_players_platform.staging import describe_artifact
from networked_players_platform.workloads import RegisteredWorkload

from .graph_bench import _undirected_dedup, load_edges


def _degree_distribution_handler(
    request: RunRequest, input_dir: Path, output_dir: Path
) -> tuple[ArtifactDescriptor, ...]:
    del request
    edges = load_edges(input_dir)
    pairs = _undirected_dedup(edges)

    degree: Counter[int] = Counter()
    for artist_a, artist_b in pairs:
        degree[artist_a] += 1
        degree[artist_b] += 1

    output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": 1,
        "kind": "degree_distribution",
        "node_count": len(degree),
        "edge_count": len(pairs),
        "max_degree": max(degree.values()) if degree else 0,
    }
    (output_dir / "degree-distribution.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    return (
        describe_artifact(
            output_dir,
            "degree-distribution.json",
            name="degree-distribution",
            contract="platform-research-degree-distribution-v1",
        ),
    )


def graph_metrics_workload() -> RegisteredWorkload:
    return RegisteredWorkload(
        spec=WorkloadSpec(
            workload_id="research.graph-metrics",
            version="1",
            default_timeout_seconds=600,
            max_retries=0,
            capabilities=CapabilityRequirement(
                architectures=("x86_64",),
                tags=("graph", "x86-heavy"),
                min_memory_mb=1024,
            ),
        ),
        handler=_degree_distribution_handler,
    )
