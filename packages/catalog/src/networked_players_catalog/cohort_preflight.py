"""Read-only preflight check for a real cohort pipeline rehearsal. See
docs/OPERATOR_SETUP.md's "Real cohort rehearsal (first source)" runbook --
this module exists to reduce operator mistakes before that rehearsal, not to
replace it: it checks that the expected inputs exist and prints the exact
next commands, but runs none of them and inspects no dataset content beyond
a manifest.json's presence.

Deliberately dependency-free beyond stdlib: no `networked_players_graph_core`
import, no DuckDB, no network. This is filesystem-path checking and command
string formatting only.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_OUTPUT_FILENAMES = (
    "extracted.json",
    "resolved.json",
    "connectivity.json",
    "playable-pairs.json",
    "review-report.md",
)


@dataclass(frozen=True, slots=True)
class PreflightCheck:
    name: str
    path: Path
    present: bool
    note: str


def _check(name: str, path: Path, *, present: bool, note: str) -> PreflightCheck:
    return PreflightCheck(name=name, path=path, present=present, note=note)


def build_preflight_report(
    *,
    source_id: str,
    source_html: Path,
    parsed_dataset: Path,
    onehop_dataset: Path,
    source_url: str,
    source_title: str,
) -> dict[str, Any]:
    """Pure, read-only: three filesystem checks, two informational target
    directories, a scan for outputs a re-run would overwrite, and the exact
    next commands -- never runs any of them, never guesses a missing value.
    """
    source_html_ok = source_html.is_file()
    parsed_dataset_ok = parsed_dataset.is_dir() and (parsed_dataset / "manifest.json").is_file()
    onehop_dataset_ok = onehop_dataset.is_dir() and (onehop_dataset / "manifest.json").is_file()

    required_checks = [
        _check(
            "source_html",
            source_html,
            present=source_html_ok,
            note="the saved page the operator manually captured -- never fetched by any command",
        ),
        _check(
            "parsed_dataset",
            parsed_dataset,
            present=parsed_dataset_ok,
            note="a parsed dataset root (directory plus manifest.json), used for resolution",
        ),
        _check(
            "onehop_dataset",
            onehop_dataset,
            present=onehop_dataset_ok,
            note="a one-hop dataset root (directory plus manifest.json), used for scoring",
        ),
    ]
    ready = all(check.present for check in required_checks)

    analysis_dir = Path("local/analysis/cohorts") / source_id
    review_dir = Path("data/private/cohort-review")

    existing_outputs: list[str] = []
    for filename in _OUTPUT_FILENAMES:
        candidate = analysis_dir / filename
        if candidate.exists():
            existing_outputs.append(str(candidate))
    for suffix in ("selection.template.json", "selection.json"):
        candidate = review_dir / f"{source_id}-{suffix}"
        if candidate.exists():
            existing_outputs.append(str(candidate))

    extracted_path = analysis_dir / "extracted.json"
    resolved_path = analysis_dir / "resolved.json"
    connectivity_path = analysis_dir / "connectivity.json"
    selection_template_path = review_dir / f"{source_id}-selection.template.json"
    selection_path = review_dir / f"{source_id}-selection.json"
    playable_cohort_path = Path("data/albums/cohorts") / f"{source_id}-playable-v1.json"

    quoted_url = shlex.quote(source_url)
    quoted_title = shlex.quote(source_title)

    commands = [
        "1) Import:\n"
        "   uv run networked-players-catalog import-cohort-source \\\n"
        f"     --input {source_html} \\\n"
        f"     --output {extracted_path} \\\n"
        f"     --source-url {quoted_url} \\\n"
        f"     --source-title {quoted_title}",
        "2) Resolve:\n"
        "   uv run networked-players-catalog resolve-cohort \\\n"
        f"     --extracted {extracted_path} \\\n"
        f"     --dataset {parsed_dataset} \\\n"
        f"     --output {resolved_path}",
        "3) Score:\n"
        "   uv run networked-players-catalog score-cohort-connectivity \\\n"
        f"     --resolved {resolved_path} \\\n"
        f"     --dataset {onehop_dataset} \\\n"
        f"     --output-dir {analysis_dir}/",
        "4) Draft a review template:\n"
        "   uv run networked-players-catalog draft-cohort-review \\\n"
        f"     --connectivity {connectivity_path} \\\n"
        f"     --output {selection_template_path}",
        "5) Human review (manual -- no command does this step):\n"
        f"   Open {selection_template_path}, read review-report.md alongside\n"
        "   candidate_pairs[], move entries you approve into approved_pairs[],\n"
        f"   and save as {selection_path} -- never promote the raw .template.json.",
        "6) Promote (only after step 5):\n"
        "   uv run networked-players-catalog promote-playable-cohort \\\n"
        f"     --resolved {resolved_path} \\\n"
        f"     --connectivity {connectivity_path} \\\n"
        f"     --selection {selection_path} \\\n"
        f"     --cohort-id {source_id} \\\n"
        f"     --output {playable_cohort_path}",
        "7) Optional -- validate the promoted artifact:\n"
        "   uv run networked-players-catalog validate-playable-cohort \\\n"
        f"     --input {playable_cohort_path}",
        "8) Optional -- ask the Pi fleet to ambient-check it too:\n"
        "   ./scripts/enqueue-cohort-check.sh --kind playable-cohort \\\n"
        f"     --artifact {playable_cohort_path}",
    ]

    return {
        "ready": ready,
        "required_checks": [
            {"name": c.name, "path": str(c.path), "present": c.present, "note": c.note}
            for c in required_checks
        ],
        "target_directories": {
            "analysis_dir": str(analysis_dir),
            "review_dir": str(review_dir),
        },
        "existing_outputs": existing_outputs,
        "commands": commands,
    }


def format_preflight_report(report: dict[str, Any]) -> str:
    lines: list[str] = ["Cohort pipeline preflight", ""]

    lines.append("Required:")
    for check in report["required_checks"]:
        marker = "[ok]     " if check["present"] else "[MISSING]"
        lines.append(f"  {marker} {check['name']:<16} {check['path']}")
    lines.append("")

    lines.append("Target directories (informational -- may not exist yet):")
    for label, path in report["target_directories"].items():
        lines.append(f"  {label}: {path}")
    lines.append("")

    lines.append("Existing outputs (a re-run of the matching step will overwrite these):")
    if report["existing_outputs"]:
        for path in report["existing_outputs"]:
            lines.append(f"  - {path}")
    else:
        lines.append("  none")
    lines.append("")

    lines.append("Next commands:")
    for command in report["commands"]:
        lines.append(command)
        lines.append("")

    if report["ready"]:
        lines.append("READY: all required inputs are present.")
    else:
        lines.append("NOT READY: fix the missing required input(s) above before continuing.")

    return "\n".join(lines) + "\n"
