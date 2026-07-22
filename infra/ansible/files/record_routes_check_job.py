#!/usr/bin/env python3
"""Record Routes artifact checks for a constrained RQ worker.

Validation lives in the dependency-free `networked_players_contracts`
package (`record_routes_failures`, distinct from `rounds_failures`'s
legacy/undeployed contract and `connection_rounds_failures`'s unrelated
Connection Guesser contract -- see ADR 0043 Finding 8, ADR 0046). This
adapter only performs file I/O and returns an RQ-serializable result, so
worker behavior cannot drift from the catalog CLI's canonical validators.
Mirrors connection_rounds_check_job.py exactly, pointed at Record Routes'
real universe.v1/rounds.v1 pair.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from networked_players_contracts import record_routes_failures


def _resolve(path_str: str) -> Path:
    """A relative path resolves against THIS file's own directory (the
    persistent rq_jobs_dir a worker's queue actually runs from), not the RQ
    worker process's CWD -- same convention as every sibling check job."""
    path = Path(path_str)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    return path


def check_record_routes(universe_path: str, rounds_path: str) -> dict[str, Any]:
    universe = json.loads(_resolve(universe_path).read_text())
    rounds = json.loads(_resolve(rounds_path).read_text())
    failures = record_routes_failures(universe, rounds)
    return {"valid": not failures, "failures": failures}


def main() -> None:
    if len(sys.argv) != 3:
        print(
            "Usage: record_routes_check_job.py <universe_path> <rounds_path>",
            file=sys.stderr,
        )
        raise SystemExit(2)
    result = check_record_routes(sys.argv[1], sys.argv[2])
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
