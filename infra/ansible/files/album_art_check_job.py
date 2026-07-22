#!/usr/bin/env python3
"""Album-art-registry artifact checks for a constrained RQ worker.

Validation lives in the dependency-free `networked_players_contracts`
package (`album_art_failures`, checked against the canonical public album
catalog it registers art for). This adapter only performs file I/O and
returns an RQ-serializable result, so worker behavior cannot drift from the
catalog CLI's canonical validators. Mirrors connection_rounds_check_job.py/
record_routes_check_job.py exactly.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from networked_players_contracts import album_art_failures


def _resolve(path_str: str) -> Path:
    """A relative path resolves against THIS file's own directory (the
    persistent rq_jobs_dir a worker's queue actually runs from), not the RQ
    worker process's CWD -- same convention as every sibling check job."""
    path = Path(path_str)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    return path


def check_album_art(registry_path: str, catalog_path: str) -> dict[str, Any]:
    registry = json.loads(_resolve(registry_path).read_text())
    catalog = json.loads(_resolve(catalog_path).read_text())
    failures = album_art_failures(registry, catalog)
    return {"valid": not failures, "failures": failures}


def main() -> None:
    if len(sys.argv) != 3:
        print(
            "Usage: album_art_check_job.py <registry_path> <catalog_path>",
            file=sys.stderr,
        )
        raise SystemExit(2)
    result = check_album_art(sys.argv[1], sys.argv[2])
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
