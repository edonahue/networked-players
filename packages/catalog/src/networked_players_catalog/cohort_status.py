"""Read-only status summary for a cohort pipeline rehearsal.

This is a resume aid, not a validator. It checks for the presence of the
expected local artifacts, surfaces out-of-order states as warnings, and
prints the next step to take. It never writes, never opens DuckDB, never
parses source HTML, and never touches the network.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class StatusStage:
    name: str
    path: str
    present: bool | None
    required: bool
    note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _default_analysis_dir(source_id: str) -> Path:
    return Path("local/analysis/cohorts") / source_id


def _default_promoted_artifact(source_id: str) -> Path:
    return Path("data/albums/cohorts") / f"{source_id}-playable-v1.json"


def _status_label(value: bool | None) -> str:
    if value is True:
        return "present"
    if value is False:
        return "missing"
    return "unknown"


def _stage(
    name: str,
    path: Path,
    *,
    present: bool | None,
    required: bool,
    note: str,
) -> StatusStage:
    return StatusStage(
        name=name,
        path=str(path),
        present=present,
        required=required,
        note=note,
    )


def _load_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.is_file():
        return None, None
    try:
        return json.loads(path.read_text()), None
    except json.JSONDecodeError as exc:
        return None, f"could not parse JSON: {exc.msg}"


def _web_manifest_entry(
    manifest_path: Path, source_id: str, expected_artifact_path: str
) -> tuple[StatusStage, dict[str, Any] | None, list[str]]:
    warnings: list[str] = []
    manifest, parse_error = _load_json(manifest_path)
    if parse_error:
        return (
            _stage(
                "web_manifest",
                manifest_path,
                present=False,
                required=False,
                note=parse_error,
            ),
            None,
            [*warnings, f"web manifest {manifest_path} is malformed: {parse_error}"],
        )
    if manifest is None:
        return (
            _stage(
                "web_manifest",
                manifest_path,
                present=False,
                required=False,
                note="manifest file is missing",
            ),
            None,
            warnings,
        )

    entries = manifest.get("cohorts", [])
    entry = next((item for item in entries if item.get("cohort_id") == source_id), None)
    if entry is None:
        return (
            _stage(
                "web_manifest",
                manifest_path,
                present=False,
                required=False,
                note="no cohort entry found for this source_id",
            ),
            None,
            warnings,
        )

    note_bits = [f"entry found; status={entry.get('status')!r}"]
    artifact_path = entry.get("artifact_path")
    if artifact_path:
        note_bits.append(f"artifact_path={artifact_path}")
    if artifact_path != expected_artifact_path:
        warnings.append(
            f"web manifest entry points to {artifact_path!r}, expected {expected_artifact_path!r}"
        )
    if entry.get("status") not in {"reviewed", "synthetic"}:
        warnings.append(f"web manifest entry has unexpected status {entry.get('status')!r}")

    return (
        _stage(
            "web_manifest",
            manifest_path,
            present=True,
            required=False,
            note="; ".join(note_bits),
        ),
        entry,
        warnings,
    )


def _web_import_map_entry(import_map_path: Path, source_id: str) -> tuple[StatusStage, list[str]]:
    if not import_map_path.is_file():
        return (
            _stage(
                "web_import_map",
                import_map_path,
                present=False,
                required=False,
                note="import map file is missing",
            ),
            [],
        )

    raw = import_map_path.read_text()
    if re.search(rf'"{re.escape(source_id)}"\s*:', raw):
        return (
            _stage(
                "web_import_map",
                import_map_path,
                present=True,
                required=False,
                note="static import map entry found",
            ),
            [],
        )

    return (
        _stage(
            "web_import_map",
            import_map_path,
            present=False,
            required=False,
            note="no static import map entry found for this source_id",
        ),
        [],
    )


def _latest_matching_job_record(
    jobs_dir: Path, *, candidate_artifacts: list[Path]
) -> dict[str, Any] | None:
    if not jobs_dir.is_dir():
        return None

    candidate_strings = {str(path) for path in candidate_artifacts if path.exists()}
    if not candidate_strings:
        return None

    latest: tuple[str, Path, dict[str, Any]] | None = None
    for path in sorted(jobs_dir.glob("cohort-check-*.json")):
        try:
            record = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        if record.get("artifact") not in candidate_strings:
            continue
        if latest is None or path.name > latest[0]:
            latest = (path.name, path, record)

    if latest is None:
        return None

    record = latest[2]
    result_obj = record.get("result")
    result: dict[str, Any] = result_obj if isinstance(result_obj, dict) else {}
    return {
        "artifact": record.get("artifact"),
        "kind": record.get("kind"),
        "job_failed": record.get("job_failed"),
        "ok": record.get("ok"),
        "measured_at_utc": record.get("measured_at_utc"),
        "valid": result.get("valid"),
        "failures": result.get("failures", []),
    }


def build_status_report(
    *,
    source_id: str,
    analysis_dir: Path | None = None,
    review_dir: Path | None = None,
    promoted_artifact: Path | None = None,
    web_manifest: Path | None = None,
    web_import_map: Path | None = None,
    jobs_dir: Path | None = None,
) -> dict[str, Any]:
    analysis_dir = analysis_dir or _default_analysis_dir(source_id)
    review_dir = review_dir or Path("data/private/cohort-review")
    promoted_artifact = promoted_artifact or _default_promoted_artifact(source_id)
    web_manifest = web_manifest or Path("apps/web/public/data/cohorts/index.json")
    web_import_map = web_import_map or Path("apps/web/src/data/cohortArtifacts.ts")
    jobs_dir = jobs_dir or Path("local/jobs")

    source_html = Path("data/private/source-html") / f"{source_id}.html"
    extracted = analysis_dir / "extracted.json"
    resolved = analysis_dir / "resolved.json"
    connectivity = analysis_dir / "connectivity.json"
    playable_pairs = analysis_dir / "playable-pairs.json"
    review_report = analysis_dir / "review-report.md"
    selection_template = review_dir / f"{source_id}-selection.template.json"
    selection = review_dir / f"{source_id}-selection.json"

    stages: list[StatusStage] = [
        _stage(
            "saved_source",
            source_html,
            present=source_html.is_file(),
            required=True,
            note="operator-saved HTML in data/private/source-html/",
        ),
        _stage(
            "extracted",
            extracted,
            present=extracted.is_file(),
            required=True,
            note="output of import-cohort-source",
        ),
        _stage(
            "resolved",
            resolved,
            present=resolved.is_file(),
            required=True,
            note="output of resolve-cohort",
        ),
        _stage(
            "connectivity",
            connectivity,
            present=connectivity.is_file(),
            required=True,
            note="output of score-cohort-connectivity",
        ),
        _stage(
            "playable_pairs",
            playable_pairs,
            present=playable_pairs.is_file(),
            required=True,
            note="pair shortlist from score-cohort-connectivity",
        ),
        _stage(
            "review_report",
            review_report,
            present=review_report.is_file(),
            required=True,
            note="human review aid from score-cohort-connectivity",
        ),
        _stage(
            "selection_template",
            selection_template,
            present=selection_template.is_file(),
            required=True,
            note="draft template from draft-cohort-review",
        ),
        _stage(
            "selection",
            selection,
            present=selection.is_file(),
            required=True,
            note="operator-authored private review file",
        ),
        _stage(
            "promoted_artifact",
            promoted_artifact,
            present=promoted_artifact.is_file(),
            required=True,
            note="output of promote-playable-cohort",
        ),
    ]

    warnings: list[str] = []
    seen_missing_required = False
    for stage in stages:
        if stage.present is False and stage.required:
            seen_missing_required = True
            continue
        if stage.present is True and seen_missing_required:
            warnings.append(f"{stage.name} exists before an earlier required stage is complete")

    manifest_stage, manifest_entry, manifest_warnings = _web_manifest_entry(
        web_manifest, source_id, f"/data/cohorts/{source_id}-playable-v1.json"
    )
    import_map_stage, import_map_warnings = _web_import_map_entry(web_import_map, source_id)
    warnings.extend(manifest_warnings)
    warnings.extend(import_map_warnings)
    if manifest_stage.present is not True and import_map_stage.present is True:
        warnings.append("static import map references the cohort before the web manifest does")

    web_dist_root = Path("apps/web/dist/cohorts")
    web_route = web_dist_root / source_id / "index.html"
    if web_dist_root.exists():
        route_present: bool | None = web_route.is_file()
        route_note = "generated static route"
        if not route_present:
            warnings.append(
                f"generated route {web_route} is missing even though {web_dist_root} exists"
            )
        elif manifest_stage.present is not True or import_map_stage.present is not True:
            warnings.append(
                "generated route exists before the manifest/import map are both in place"
            )
    else:
        route_present = None
        route_note = "apps/web/dist/cohorts/ is absent, so the route is not checked"

    route_stage = _stage(
        "web_route",
        web_route,
        present=route_present,
        required=False,
        note=route_note,
    )

    if stages[-1].present is not True:
        if manifest_stage.present is True or import_map_stage.present is True:
            warnings.append(
                "web visibility artifacts exist before the promoted artifact is present"
            )
        if route_stage.present is True:
            warnings.append("generated route exists before the promoted artifact is present")

    pi_check = _latest_matching_job_record(
        jobs_dir,
        candidate_artifacts=[promoted_artifact, connectivity],
    )
    if pi_check and not pi_check.get("ok", False):
        warnings.append(f"latest Pi cohort-check for {pi_check['artifact']} failed")

    web_visible = (
        manifest_stage.present is True
        and import_map_stage.present is True
        and stages[-1].present is True
    )

    required_stages = stages
    if web_visible:
        pipeline_state = "web-visible"
        current_checkpoint = "web-visible"
        next_action = "Artifact is web-visible; proceed with final review and deploy."
    else:
        pipeline_state = "in progress"
        current_checkpoint = "none"
        next_action = "No required artifact is present yet."

        for stage in required_stages:
            if stage.present is True:
                current_checkpoint = stage.name
                continue

            if stage.name == "saved_source":
                next_action = (
                    f"Save the source HTML at {stage.path}, then rerun `cohort-pipeline-status`."
                )
            elif stage.name == "extracted":
                next_action = (
                    "Run `uv run networked-players-catalog import-cohort-source` "
                    f"to create {stage.path}."
                )
            elif stage.name == "resolved":
                next_action = (
                    f"Run `uv run networked-players-catalog resolve-cohort` to create {stage.path}."
                )
            elif stage.name == "connectivity":
                next_action = (
                    "Run `uv run networked-players-catalog score-cohort-connectivity` "
                    f"to create {stage.path}."
                )
            elif stage.name in {"playable_pairs", "review_report"}:
                next_action = (
                    "Rerun `uv run networked-players-catalog score-cohort-connectivity` "
                    "to regenerate connectivity.json, playable-pairs.json, and review-report.md."
                )
            elif stage.name == "selection_template":
                next_action = (
                    "Run `uv run networked-players-catalog draft-cohort-review` "
                    f"to create {stage.path}."
                )
            elif stage.name == "selection":
                next_action = f"Perform the human review step and save {stage.path}."
            elif stage.name == "promoted_artifact":
                next_action = (
                    "Run `uv run networked-players-catalog promote-playable-cohort` "
                    f"to create {stage.path}."
                )
            break
        else:
            # Core pipeline is complete but the web visibility checks are not.
            pipeline_state = "promoted, not web-visible"
            current_checkpoint = "promoted_artifact"
            missing_web = []
            if manifest_stage.present is not True:
                missing_web.append("apps/web/public/data/cohorts/index.json")
            if import_map_stage.present is not True:
                missing_web.append("apps/web/src/data/cohortArtifacts.ts")
            if missing_web:
                next_action = (
                    "Make the promoted artifact web-visible in a future explicit PR by "
                    f"updating {', '.join(missing_web)}."
                )
            else:
                next_action = (
                    "The cohort is promoted and web-visible; proceed with final review and deploy."
                )

    report: dict[str, Any] = {
        "source_id": source_id,
        "pipeline_state": pipeline_state,
        "current_checkpoint": current_checkpoint,
        "next_action": next_action,
        "warnings": warnings,
        "paths": {
            "source_html": str(source_html),
            "analysis_dir": str(analysis_dir),
            "review_dir": str(review_dir),
            "promoted_artifact": str(promoted_artifact),
            "web_manifest": str(web_manifest),
            "web_import_map": str(web_import_map),
            "jobs_dir": str(jobs_dir),
            "web_route": str(web_route),
        },
        "stages": [
            *[stage.to_dict() for stage in stages],
            manifest_stage.to_dict(),
            import_map_stage.to_dict(),
            route_stage.to_dict(),
        ],
        "web_visibility": {
            "manifest_entry": {
                "present": manifest_stage.present,
                "entry": manifest_entry,
                "path": manifest_stage.path,
            },
            "import_map_entry": {
                "present": import_map_stage.present,
                "path": import_map_stage.path,
            },
            "generated_route": {
                "present": route_stage.present,
                "path": route_stage.path,
            },
        },
        "pi_check": pi_check,
    }
    return report


def format_status_report(report: dict[str, Any]) -> str:
    lines: list[str] = [f"Cohort pipeline status for {report['source_id']}", ""]
    lines.append(f"Pipeline state: {report['pipeline_state']}")
    lines.append(f"Current checkpoint: {report['current_checkpoint']}")
    lines.append(f"Next action: {report['next_action']}")
    lines.append("")

    if report["warnings"]:
        lines.append("Warnings:")
        for warning in report["warnings"]:
            lines.append(f"  - {warning}")
        lines.append("")

    lines.append("Stages:")
    for stage in report["stages"]:
        if stage["name"] == "web_route" and stage["present"] is None:
            marker = "[unknown]"
        else:
            marker = f"[{_status_label(stage['present'])}]"
        lines.append(f"  {marker:<10} {stage['name']:<20} {stage['path']}")
        lines.append(f"             {stage['note']}")
    lines.append("")

    lines.append("Web visibility:")
    manifest = report["web_visibility"]["manifest_entry"]
    lines.append(f"  manifest entry: {_status_label(manifest['present'])}")
    if manifest["entry"] is not None:
        lines.append(f"    {json.dumps(manifest['entry'], sort_keys=True)}")
    import_map_present = report["web_visibility"]["import_map_entry"]["present"]
    route_present = report["web_visibility"]["generated_route"]["present"]
    lines.append(f"  import map entry: {_status_label(import_map_present)}")
    lines.append(f"  generated route: {_status_label(route_present)}")
    lines.append("")

    lines.append("Pi check:")
    if report["pi_check"] is None:
        lines.append("  no matching local/jobs/cohort-check-*.json record found")
    else:
        lines.append(f"  {json.dumps(report['pi_check'], sort_keys=True)}")
    lines.append("")

    return "\n".join(lines) + "\n"
