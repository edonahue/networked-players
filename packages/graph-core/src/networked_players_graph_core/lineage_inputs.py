"""Stamp `provenance.inputs` (ADR 0072 section 1) on a freshly built artifact.

The artifact-name -> version-field table lives in
`networked_players_contracts.artifact_lineage`, the same module the validator
reads, so what a builder declares and what the rule later checks cannot drift.
This lives in graph-core (not next to the catalog package's
`build_parameters.py`) because the builders that stamp are graph-core
functions, and graph-core must not import `networked_players_catalog`.

A missing upstream version is recorded as `None`, never invented: e.g. a
challenge committed before `challenge_version` existed.
"""

from __future__ import annotations

from typing import Any

from networked_players_contracts.artifact_lineage import artifact_content_version


def lineage_inputs(**upstream: Any) -> dict[str, str | None]:
    """`{artifact_name: content_version}` for the given upstream payloads,
    keyed by `PUBLIC_ARTIFACT_GROUPS` name (e.g. `catalog=...`,
    `record_routes=<routes universe>`)."""
    return {name: artifact_content_version(name, payload) for name, payload in upstream.items()}


def stamp_inputs(artifact: dict[str, Any], inputs: dict[str, str | None]) -> None:
    """Set `artifact["provenance"]["inputs"]`, creating a top-level
    `provenance` object for artifacts that had none."""
    provenance = artifact.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}
        artifact["provenance"] = provenance
    provenance["inputs"] = inputs
