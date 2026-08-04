#!/usr/bin/env python3
"""Contributor-index and pathfinding-graph artifact checks for a constrained
RQ worker.

Validation lives in the dependency-free `networked_players_contracts`
package (`contributor_index_failures`, `pathfinding_graph_failures` --
both, like `connection_rounds_failures`, validate an artifact against the
canonical catalog it claims to belong to). This adapter only performs file
I/O and returns an RQ-serializable result, so worker behavior cannot drift
from the catalog CLI's canonical validators. Both entry points share one
job body file (unlike connection_rounds/record_routes's one-file-per-pair
convention) since they're a genuinely small, closely related pair of
"published-artifact against the catalog" checks -- see the Phase 2 report's
own note that both validators were already pure-Python/Pi-safe by design,
just never wired into a fleet check job.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from networked_players_contracts.contributor_index import contributor_index_failures
from networked_players_contracts.pathfinding_graph import pathfinding_graph_failures


def _resolve(path_str: str) -> Path:
    """A relative path resolves against THIS file's own directory (the
    persistent rq_jobs_dir a worker's queue actually runs from), not the RQ
    worker process's CWD -- same convention as every sibling check job."""
    path = Path(path_str)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    return path


def check_contributor_index(index_path: str, catalog_path: str) -> dict[str, Any]:
    index = json.loads(_resolve(index_path).read_text())
    catalog = json.loads(_resolve(catalog_path).read_text())
    failures = contributor_index_failures(index, catalog)
    return {"valid": not failures, "failures": failures}


def check_pathfinding_graph(graph_path: str, catalog_path: str) -> dict[str, Any]:
    graph = json.loads(_resolve(graph_path).read_text())
    catalog = json.loads(_resolve(catalog_path).read_text())
    failures = pathfinding_graph_failures(graph, catalog)
    return {"valid": not failures, "failures": failures}


def main() -> None:
    if len(sys.argv) != 4 or sys.argv[1] not in ("contributor-index", "pathfinding-graph"):
        print(
            "Usage: public_artifact_check_job.py "
            "<contributor-index|pathfinding-graph> <artifact_path> <catalog_path>",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if sys.argv[1] == "contributor-index":
        result = check_contributor_index(sys.argv[2], sys.argv[3])
    else:
        result = check_pathfinding_graph(sys.argv[2], sys.argv[3])
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
