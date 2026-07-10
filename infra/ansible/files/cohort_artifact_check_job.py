#!/usr/bin/env python3
"""Cohort-artifact checks for a constrained RQ worker.

Validation lives in the dependency-free `networked_players_contracts` package.
This adapter only performs file I/O and returns an RQ-serializable result, so
worker behavior cannot drift from the catalog CLI's canonical validators.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from networked_players_contracts import connectivity_failures, playable_cohort_failures


def check_connectivity(artifact_path: str) -> dict[str, Any]:
    artifact = json.loads(Path(artifact_path).read_text())
    failures = connectivity_failures(artifact)
    return {"valid": not failures, "failures": failures}


def check_playable_cohort(artifact_path: str) -> dict[str, Any]:
    artifact = json.loads(Path(artifact_path).read_text())
    failures = playable_cohort_failures(artifact)
    return {"valid": not failures, "failures": failures}


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in ("connectivity", "playable-cohort"):
        print(
            "Usage: cohort_artifact_check_job.py <connectivity|playable-cohort> <artifact_path>",
            file=sys.stderr,
        )
        raise SystemExit(2)
    kind, artifact_path = sys.argv[1], sys.argv[2]
    result = (
        check_connectivity(artifact_path)
        if kind == "connectivity"
        else check_playable_cohort(artifact_path)
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
