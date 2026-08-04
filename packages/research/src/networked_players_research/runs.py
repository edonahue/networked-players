"""Research run bookkeeping: paths, run-id generation, and the run manifest
-- the thin, private-lane sibling of every public artifact's `manifest.json`
provenance discipline. A run always names the `corpus_version` it read
(never rebuilding the corpus itself), the code commit that produced it, and
which analyses ran.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RESEARCH_ROOT = Path("local/research")


def topic_root(topic_slug: str, *, research_root: Path = RESEARCH_ROOT) -> Path:
    return research_root / topic_slug


def corpus_root(topic_slug: str, *, research_root: Path = RESEARCH_ROOT) -> Path:
    return topic_root(topic_slug, research_root=research_root) / "corpus"


def runs_root(topic_slug: str, *, research_root: Path = RESEARCH_ROOT) -> Path:
    return topic_root(topic_slug, research_root=research_root) / "runs"


def new_run_id(now: datetime | None = None) -> str:
    """A readable, sortable run id -- an ISO-ish UTC timestamp, matching the
    existing `local/backups/swarm-manager/<timestamp>/` convention rather
    than inventing a new id shape."""
    moment = now or datetime.now(UTC)
    return moment.strftime("%Y%m%dT%H%M%SZ")


def code_commit() -> str | None:
    """The current git commit, for run-manifest provenance. Returns None
    (never raises) outside a git checkout -- a research run must not fail
    just because provenance couldn't be captured."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


@dataclass(frozen=True)
class RunPaths:
    root: Path

    @property
    def request_path(self) -> Path:
        return self.root / "request.json"

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    @property
    def analysis_dir(self) -> Path:
        return self.root / "analysis"

    @property
    def report_dir(self) -> Path:
        return self.root / "report"

    @property
    def findings_path(self) -> Path:
        return self.root / "findings.json"

    @property
    def promotion_candidates_path(self) -> Path:
        return self.root / "promotion_candidates.json"

    @property
    def metrics_path(self) -> Path:
        return self.root / "metrics.json"

    def ensure_dirs(self) -> None:
        self.analysis_dir.mkdir(parents=True, exist_ok=True)
        self.report_dir.mkdir(parents=True, exist_ok=True)


def new_run_paths(
    topic_slug: str, run_id: str | None = None, *, research_root: Path = RESEARCH_ROOT
) -> RunPaths:
    rid = run_id or new_run_id()
    return RunPaths(root=runs_root(topic_slug, research_root=research_root) / rid)


def write_run_manifest(
    paths: RunPaths,
    *,
    topic: str,
    run_id: str,
    corpus_version: str,
    analyses: list[str],
    started_at: str,
    finished_at: str,
) -> dict[str, Any]:
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "topic": topic,
        "corpus_version": corpus_version,
        "code_commit": code_commit(),
        "analyses": sorted(analyses),
        "started_at": started_at,
        "finished_at": finished_at,
    }
    paths.manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest
