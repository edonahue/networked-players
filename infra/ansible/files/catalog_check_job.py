#!/usr/bin/env python3
"""Public-album-catalog artifact checks for a constrained RQ worker.

Validation lives in the dependency-free `networked_players_contracts`
package (`public_album_catalog_failures`). This adapter only performs file
I/O and returns an RQ-serializable result, so worker behavior cannot drift
from the catalog CLI's canonical validators. Single-artifact shape (unlike
its universe/rounds-pair siblings) since the catalog is one file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from networked_players_contracts import public_album_catalog_failures


def _resolve(path_str: str) -> Path:
    """A relative path resolves against THIS file's own directory (the
    persistent rq_jobs_dir a worker's queue actually runs from), not the RQ
    worker process's CWD -- same convention as every sibling check job."""
    path = Path(path_str)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    return path


def check_catalog(catalog_path: str) -> dict[str, Any]:
    catalog = json.loads(_resolve(catalog_path).read_text())
    failures = public_album_catalog_failures(catalog)
    return {"valid": not failures, "failures": failures}


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: catalog_check_job.py <catalog_path>", file=sys.stderr)
        raise SystemExit(2)
    result = check_catalog(sys.argv[1])
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
