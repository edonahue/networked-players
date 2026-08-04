"""Findings and report generation from a run's analysis outputs.

`findings.json` entries are always typed `"kind": "fact"` (computed
directly from analysis output) or `"kind": "interpretation"` (a human or
LLM-suggested reading, recorded separately and never silently upgraded to
`fact` -- see ADR 0054). This module only ever writes `fact` entries;
`interpretation` entries are appended later, by a human, outside the
automated pipeline.

Report format (Markdown for now) is a deliberately minimal choice for
Slice A's fixture-proof pass -- Slice G decides the real Jamiroquai
research pack's format once Slice D's actual output shape is known, per
the Phase 3 plan.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_findings(analysis_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Derive a small set of computed, factual findings from whichever
    analyses actually ran. Every entry is `"kind": "fact"` -- this
    function never editorializes or infers relationships beyond a direct
    count/aggregate of what the analysis already computed."""
    findings: list[dict[str, Any]] = []

    timeline = analysis_results.get("personnel_timeline")
    if timeline is not None:
        albums = timeline["albums"]
        distinct_contributors = {
            contributor["artist_id"]
            for album in albums
            for contributor in album["contributors"]
            if contributor.get("artist_id") is not None
        }
        findings.append(
            {
                "kind": "fact",
                "analysis": "personnel_timeline",
                "statement": (
                    f"{len(albums)} release(s) with {len(distinct_contributors)} "
                    "distinct credited contributor(s)."
                ),
                "data": {
                    "release_count": len(albums),
                    "distinct_contributor_count": len(distinct_contributors),
                },
            }
        )

    return {"schema_version": 1, "findings": findings}


def write_findings(path: Path, analysis_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    findings = build_findings(analysis_results)
    path.write_text(json.dumps(findings, indent=2, sort_keys=True) + "\n")
    return findings


def write_promotion_candidates(path: Path, candidates: list[dict[str, Any]] | None = None) -> None:
    """Structured, human-reviewed TODO list -- never an automated pipeline
    stage. Empty by default; Slice D/G populate real candidates once real
    findings exist."""
    path.write_text(
        json.dumps({"schema_version": 1, "candidates": candidates or []}, indent=2, sort_keys=True)
        + "\n"
    )


def render_markdown_report(
    *,
    topic: str,
    run_id: str,
    questions: list[str],
    analysis_results: dict[str, dict[str, Any]],
    findings: dict[str, Any],
) -> str:
    lines = [f"# Research report: {topic}", "", f"Run: `{run_id}`", ""]
    if questions:
        lines.append("## Questions")
        lines.extend(f"- {q}" for q in questions)
        lines.append("")

    lines.append("## Findings")
    if findings["findings"]:
        for finding in findings["findings"]:
            lines.append(f"- **{finding['analysis']}** ({finding['kind']}): {finding['statement']}")
    else:
        lines.append("_No findings yet -- no implemented analysis ran for this request._")
    lines.append("")

    timeline = analysis_results.get("personnel_timeline")
    if timeline is not None:
        lines.append("## Personnel timeline")
        for album in timeline["albums"]:
            names = ", ".join(sorted({c["name"] for c in album["contributors"] if c.get("name")}))
            lines.append(f"- **{album['title']}** ({album['released'] or 'undated'}): {names}")
        lines.append("")

    return "\n".join(lines) + "\n"
