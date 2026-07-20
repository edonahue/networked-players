#!/usr/bin/env python3
"""Rounds-artifact checks for a constrained RQ worker.

Validation lives in the dependency-free `networked_players_contracts`
package. This adapter only performs file I/O and returns an RQ-serializable
result, so worker behavior cannot drift from the catalog CLI's canonical
validators. Mirrors cohort_artifact_check_job.py exactly, adapted for the
rounds contract's two-file (universe.v1/rounds.v1) shape.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from networked_players_contracts import rounds_failures


def _resolve(path_str: str) -> Path:
    """A relative path resolves against THIS file's own directory (the
    persistent rq_jobs_dir a worker's queue actually runs from), not the RQ
    worker process's CWD -- same convention as verify_challenge_job.py."""
    path = Path(path_str)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    return path


def check_rounds(universe_path: str, rounds_path: str) -> dict[str, Any]:
    universe = json.loads(_resolve(universe_path).read_text())
    rounds = json.loads(_resolve(rounds_path).read_text())
    failures = rounds_failures(universe, rounds)
    return {"valid": not failures, "failures": failures}


def main() -> None:
    if len(sys.argv) != 3:
        print(
            "Usage: rounds_check_job.py <universe_path> <rounds_path>",
            file=sys.stderr,
        )
        raise SystemExit(2)
    result = check_rounds(sys.argv[1], sys.argv[2])
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
