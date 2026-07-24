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


def _resolve(path_str: str) -> Path:
    """A relative path resolves against THIS file's own directory (the
    persistent rq_jobs_dir a worker's queue actually runs from), not the RQ
    worker process's CWD -- same convention as every sibling check job.
    A bare `Path(artifact_path).read_text()` with no resolution was the
    original bug here: the artifact was never actually staged anywhere the
    resulting relative path would resolve to."""
    path = Path(path_str)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    return path


def _load_artifact(artifact_path: str) -> tuple[dict[str, Any] | None, list[str]]:
    """Read + parse the artifact, returning a structured failure list instead
    of letting a missing/malformed file surface as a bare RQ traceback --
    the same failure shape a real contract violation produces, so a staging
    race or an operator typo shows up in local/jobs/*.json as a readable
    `failures` entry."""
    try:
        return json.loads(_resolve(artifact_path).read_text()), []
    except OSError as exc:
        return None, [f"could not read artifact {artifact_path!r}: {exc}"]
    except json.JSONDecodeError as exc:
        return None, [f"could not parse artifact {artifact_path!r} as JSON: {exc}"]


def check_connectivity(artifact_path: str) -> dict[str, Any]:
    artifact, failures = _load_artifact(artifact_path)
    if artifact is not None:
        failures = connectivity_failures(artifact)
    return {"valid": not failures, "failures": failures}


def check_playable_cohort(artifact_path: str) -> dict[str, Any]:
    artifact, failures = _load_artifact(artifact_path)
    if artifact is not None:
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
