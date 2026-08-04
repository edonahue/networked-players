"""Findings and report generation from a run's analysis outputs.

`findings.json` entries are always typed `"kind": "fact"` (computed
directly from analysis output) or `"kind": "interpretation"` (a human or
LLM-suggested reading, recorded separately and never silently upgraded to
`fact` -- see ADR 0054). This module only ever writes `fact` entries;
`interpretation` entries are appended later, by a human, outside the
automated pipeline.

Report format (Markdown) was a deliberately minimal choice for Slice A's
fixture-proof pass; Slice D extends it to cover all six analyses, still
Markdown -- Slice G decides whether a real Jamiroquai research pack needs
a richer format once the full real output shape (this module) is in
hand.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_PERSONNEL_TIMELINE_DISPLAY_LIMIT = 30
_BRIDGE_DISPLAY_LIMIT = 15
_MOST_CONNECTED_DISPLAY_LIMIT = 15

# Same discipline as graph-core's connection_rounds.py/analysis.py and
# contracts' contributor_index.py: any generated text that smuggles in a
# relationship/influence claim the underlying analysis never computed is a
# bug, not a style issue -- see ADR 0054's fact-vs-interpretation split.
_FORBIDDEN_PHRASES = ("worked with", "collaborated with", "influenced")


class ResearchReportError(Exception):
    """Raised when generated findings/report text would assert an
    inference (collaboration, influence, relationship) as fact."""


def _scan_for_forbidden_phrases(text: str) -> None:
    lowered = text.lower()
    for phrase in _FORBIDDEN_PHRASES:
        if phrase in lowered:
            raise ResearchReportError(
                f"generated text contains forbidden inference-implying phrase: {phrase!r}"
            )


def _fact(analysis: str, statement: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "fact", "analysis": analysis, "statement": statement, "data": data}


def _personnel_timeline_finding(result: dict[str, Any]) -> dict[str, Any]:
    albums = result["albums"]
    distinct_contributors = {
        contributor["artist_id"]
        for album in albums
        for contributor in album["contributors"]
        if contributor.get("artist_id") is not None
    }
    return _fact(
        "personnel_timeline",
        f"{len(albums)} release(s) with {len(distinct_contributors)} "
        "distinct credited contributor(s).",
        {"release_count": len(albums), "distinct_contributor_count": len(distinct_contributors)},
    )


def _role_distribution_finding(result: dict[str, Any]) -> dict[str, Any]:
    overall = result["overall"]
    total = sum(overall.values())
    top_category = max(overall.items(), key=lambda pair: pair[1]) if overall else None
    statement = f"{total} classified role component(s) across {len(overall)} categories."
    if top_category is not None:
        statement += f" Most frequent: {top_category[0]} ({top_category[1]})."
    return _fact("role_distribution", statement, {"overall": overall, "total": total})


def _temporal_comparison_finding(result: dict[str, Any]) -> dict[str, Any]:
    turnover_years = result["turnover_years"]
    eras = result["eras"]
    return _fact(
        "temporal_comparison",
        f"{len(turnover_years)} year(s) crossed the {result['turnover_threshold']} "
        f"contributor-overlap turnover threshold, implying {len(eras)} candidate era(s).",
        {"turnover_year_count": len(turnover_years), "era_count": len(eras)},
    )


def _contributor_network_finding(result: dict[str, Any]) -> dict[str, Any]:
    nodes = result["nodes"]
    edges = result["edges"]
    return _fact(
        "contributor_network",
        f"{len(nodes)} contributor(s), {len(edges)} co-credit edge(s) in the corpus's 1-hop graph.",
        {"node_count": len(nodes), "edge_count": len(edges)},
    )


def _community_detection_finding(result: dict[str, Any]) -> dict[str, Any]:
    return _fact(
        "community_detection",
        f"{result['community_count']} communit(ies) found via {result['algorithm']} "
        f"({result['params']}).",
        {"community_count": result["community_count"], "algorithm": result["algorithm"]},
    )


def _bridge_analysis_finding(result: dict[str, Any]) -> dict[str, Any]:
    ranked = result["ranked_contributors"]
    top = ranked[0] if ranked else None
    statement = f"{len(ranked)} ranked contributor(s) by {result['signal']}."
    if top is not None and top.get("name"):
        statement += f" Highest: {top['name']}."
    return _fact("bridge_analysis", statement, {"ranked_count": len(ranked)})


_FINDING_BUILDERS = {
    "personnel_timeline": _personnel_timeline_finding,
    "role_distribution": _role_distribution_finding,
    "temporal_comparison": _temporal_comparison_finding,
    "contributor_network": _contributor_network_finding,
    "community_detection": _community_detection_finding,
    "bridge_analysis": _bridge_analysis_finding,
}


def build_findings(analysis_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Derive a small set of computed, factual findings from whichever
    analyses actually ran. Every entry is `"kind": "fact"` -- this
    function never editorializes or infers relationships beyond a direct
    count/aggregate of what the analysis already computed."""
    findings: list[dict[str, Any]] = []
    for name, result in analysis_results.items():
        builder = _FINDING_BUILDERS.get(name)
        if builder is not None:
            findings.append(builder(result))
    return {"schema_version": 1, "findings": findings}


def write_findings(path: Path, analysis_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    findings = build_findings(analysis_results)
    serialized = json.dumps(findings, indent=2, sort_keys=True, default=str)
    _scan_for_forbidden_phrases(serialized)
    path.write_text(serialized + "\n")
    return findings


def write_promotion_candidates(path: Path, candidates: list[dict[str, Any]] | None = None) -> None:
    """Structured, human-reviewed TODO list -- never an automated pipeline
    stage. Empty by default; Slice D/G populate real candidates once real
    findings exist."""
    path.write_text(
        json.dumps({"schema_version": 1, "candidates": candidates or []}, indent=2, sort_keys=True)
        + "\n"
    )


def _discography_overview(analysis_results: dict[str, dict[str, Any]]) -> str | None:
    """A one-paragraph, at-a-glance summary stitched from whichever
    analyses ran -- every number here is a direct read of an analysis's
    own output, never a new computation, so it carries no additional
    fact-vs-interpretation risk beyond what each analysis already
    established."""
    parts: list[str] = []
    timeline = analysis_results.get("personnel_timeline")
    if timeline is not None:
        parts.append(f"{len(timeline['albums'])} release(s) in this 1-hop corpus")
    network = analysis_results.get("contributor_network")
    if network is not None:
        parts.append(
            f"{len(network['nodes'])} co-credited contributor(s) connected by "
            f"{len(network['edges'])} edge(s)"
        )
    community = analysis_results.get("community_detection")
    if community is not None:
        parts.append(
            f"{community['community_count']} community/communities under {community['algorithm']}"
        )
    role_distribution = analysis_results.get("role_distribution")
    if role_distribution is not None and role_distribution["overall"]:
        top_category, top_count = max(
            role_distribution["overall"].items(), key=lambda pair: pair[1]
        )
        parts.append(f"most-classified role category: {top_category} ({top_count})")
    if not parts:
        return None
    return "; ".join(parts) + "."


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

    overview = _discography_overview(analysis_results)
    if overview:
        lines.append("## Discography overview")
        lines.append(overview)
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
        albums = timeline["albums"]
        lines.append("## Personnel timeline")
        if len(albums) > _PERSONNEL_TIMELINE_DISPLAY_LIMIT:
            lines.append(
                f"_{len(albums)} releases total -- showing the first "
                f"{_PERSONNEL_TIMELINE_DISPLAY_LIMIT}, chronologically._"
            )
        for album in albums[:_PERSONNEL_TIMELINE_DISPLAY_LIMIT]:
            names = ", ".join(sorted({c["name"] for c in album["contributors"] if c.get("name")}))
            lines.append(f"- **{album['title']}** ({album['released'] or 'undated'}): {names}")
        lines.append("")

    role_distribution = analysis_results.get("role_distribution")
    if role_distribution is not None:
        lines.append("## Role distribution")
        for category, count in sorted(
            role_distribution["overall"].items(), key=lambda pair: pair[1], reverse=True
        ):
            lines.append(f"- {category}: {count}")
        lines.append("")

    temporal = analysis_results.get("temporal_comparison")
    if temporal is not None:
        lines.append("## Temporal comparison")
        lines.append(
            f"Turnover threshold {temporal['turnover_threshold']} contributor-overlap "
            f"Jaccard similarity; {len(temporal['eras'])} candidate era(s) implied "
            "(chronological run boundaries only -- no descriptive label assigned)."
        )
        for era in temporal["eras"]:
            end = era["end_year_exclusive"] or "present"
            lines.append(f"- {era['start_year']}-{end}")
        lines.append("")

    community = analysis_results.get("community_detection")
    if community is not None:
        lines.append("## Community detection")
        lines.append(
            f"{community['community_count']} communit(ies) via "
            f"{community['algorithm']} ({community['params']})."
        )
        lines.append("")

    network = analysis_results.get("contributor_network")
    if network is not None:
        lines.append("## Most-connected contributors")
        lines.append(
            "Ranked by raw co-credit degree (distinct contributors sharing a "
            "recording, release, or co-performer credit) -- a different, "
            "simpler signal than bridge_analysis's betweenness ranking below:"
        )
        ranked_nodes = sorted(network["nodes"], key=lambda node: node["degree"], reverse=True)
        for node in ranked_nodes[:_MOST_CONNECTED_DISPLAY_LIMIT]:
            if node.get("name"):
                lines.append(f"- {node['name']} (degree {node['degree']})")
        lines.append("")

    bridge = analysis_results.get("bridge_analysis")
    if bridge is not None:
        lines.append("## Bridge contributors")
        lines.append(f"Ranked by {bridge['signal']}:")
        for entry in bridge["ranked_contributors"][:_BRIDGE_DISPLAY_LIMIT]:
            if entry.get("name"):
                lines.append(f"- {entry['name']} ({entry['betweenness']:.1f})")
        lines.append("")

    report_text = "\n".join(lines) + "\n"
    _scan_for_forbidden_phrases(report_text)
    return report_text
