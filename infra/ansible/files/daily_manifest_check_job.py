#!/usr/bin/env python3
"""Connection-daily-manifest artifact checks for a constrained RQ worker.

Validation lives in the dependency-free `networked_players_contracts`
package (`connection_daily_manifest_failures`, checked against its paired
Connection Guesser rounds artifact -- see that module's docstring for what
it does and deliberately does not check). This adapter only performs file
I/O and returns an RQ-serializable result, so worker behavior cannot drift
from the catalog CLI's canonical validators. Mirrors
connection_rounds_check_job.py/record_routes_check_job.py exactly.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from networked_players_contracts import connection_daily_manifest_failures


def _resolve(path_str: str) -> Path:
    """A relative path resolves against THIS file's own directory (the
    persistent rq_jobs_dir a worker's queue actually runs from), not the RQ
    worker process's CWD -- same convention as every sibling check job."""
    path = Path(path_str)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    return path


def check_connection_daily_manifest(manifest_path: str, rounds_path: str) -> dict[str, Any]:
    manifest = json.loads(_resolve(manifest_path).read_text())
    rounds = json.loads(_resolve(rounds_path).read_text())
    failures = connection_daily_manifest_failures(manifest, rounds)
    return {"valid": not failures, "failures": failures}


def main() -> None:
    if len(sys.argv) != 3:
        print(
            "Usage: daily_manifest_check_job.py <manifest_path> <rounds_path>",
            file=sys.stderr,
        )
        raise SystemExit(2)
    result = check_connection_daily_manifest(sys.argv[1], sys.argv[2])
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
