"""Fixture tests for Slice D's `report.py` extension: `build_findings`/
`render_markdown_report` covering all six analyses (not just
`personnel_timeline`), and the forbidden-phrase tripwire."""

from __future__ import annotations

import pytest

from networked_players_research.report import (
    ResearchReportError,
    build_findings,
    render_markdown_report,
    write_findings,
)

_ROLE_DISTRIBUTION = {
    "kind": "role_distribution",
    "overall": {"unknown": 10, "production": 2},
    "by_year": {"1990": {"unknown": 4}},
}

_TEMPORAL_COMPARISON = {
    "kind": "temporal_comparison",
    "turnover_threshold": 0.2,
    "year_similarity": [],
    "turnover_years": ["1995"],
    "eras": [
        {"start_year": "1990", "end_year_exclusive": "1995"},
        {"start_year": "1995", "end_year_exclusive": None},
    ],
}

_CONTRIBUTOR_NETWORK = {
    "kind": "contributor_network",
    "nodes": [{"artist_id": 100, "name": "Jane", "degree": 2}],
    "edges": [{"artist_a_id": 100, "artist_b_id": 200}],
}

_COMMUNITY_DETECTION = {
    "kind": "community_detection",
    "algorithm": "leiden",
    "params": {"objective_function": "modularity"},
    "community_count": 2,
    "assignments": [
        {
            "artist_id": 100,
            "name": "Jane",
            "community": "community 0 under algorithm leiden params {}",
        }
    ],
}

_BRIDGE_ANALYSIS = {
    "kind": "bridge_analysis",
    "signal": "betweenness_centrality",
    "ranked_contributors": [{"artist_id": 100, "name": "Jane", "betweenness": 1.0}],
}

_ALL_RESULTS = {
    "role_distribution": _ROLE_DISTRIBUTION,
    "temporal_comparison": _TEMPORAL_COMPARISON,
    "contributor_network": _CONTRIBUTOR_NETWORK,
    "community_detection": _COMMUNITY_DETECTION,
    "bridge_analysis": _BRIDGE_ANALYSIS,
}


def test_build_findings_covers_every_non_personnel_timeline_analysis() -> None:
    findings = build_findings(_ALL_RESULTS)
    analyses_with_findings = {f["analysis"] for f in findings["findings"]}
    assert analyses_with_findings == set(_ALL_RESULTS)
    for finding in findings["findings"]:
        assert finding["kind"] == "fact"


def test_build_findings_skips_analyses_that_did_not_run() -> None:
    findings = build_findings({"role_distribution": _ROLE_DISTRIBUTION})
    assert len(findings["findings"]) == 1
    assert findings["findings"][0]["analysis"] == "role_distribution"


def test_render_markdown_report_includes_a_section_per_analysis() -> None:
    findings = build_findings(_ALL_RESULTS)
    report_text = render_markdown_report(
        topic="Jamiroquai",
        run_id="v1-full",
        questions=["Which contributors bridge outside the band?"],
        analysis_results=_ALL_RESULTS,
        findings=findings,
    )
    assert "## Role distribution" in report_text
    assert "## Temporal comparison" in report_text
    assert "## Community detection" in report_text
    assert "## Bridge contributors" in report_text
    assert "Jane" in report_text


def test_forbidden_phrase_in_a_finding_statement_raises(tmp_path) -> None:
    tainted = {
        "kind": "bridge_analysis",
        "signal": "betweenness_centrality",
        "ranked_contributors": [
            {"artist_id": 1, "name": "collaborated with someone", "betweenness": 1.0}
        ],
    }
    with pytest.raises(ResearchReportError):
        write_findings(tmp_path / "findings.json", {"bridge_analysis": tainted})
