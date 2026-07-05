"""Validate an extracted-candidates artifact. See
data/contracts/album-cohort-extracted-v1.md.
"""

from __future__ import annotations

import json
from typing import Any

_FORBIDDEN_SUBSTRINGS = ("/home/", "data/private", "local/", "DISCOGS_TOKEN", ".ssh")
_TOP_LEVEL_KEYS = frozenset(
    {"schema_version", "source", "extractor_version", "generated_at", "notes", "candidates"}
)
_SOURCE_KEYS = frozenset({"source_url", "page_title", "saved_at", "operator_note"})
_CANDIDATE_KEYS = frozenset(
    {"rank", "artist", "title", "year", "master_id", "release_id", "confidence", "warnings"}
)
_CONFIDENCE_VALUES = frozenset({"high", "medium", "low"})


class CohortSourceValidationError(RuntimeError):
    """Raised when an extracted-candidates artifact violates its contract."""


def validate_extracted_candidates(artifact: dict[str, Any]) -> None:
    failures: list[str] = []

    if set(artifact.keys()) != _TOP_LEVEL_KEYS:
        failures.append(f"unexpected top-level keys: {sorted(artifact.keys())}")
    if artifact.get("schema_version") != 1:
        failures.append("schema_version must be 1")

    source = artifact.get("source")
    if not isinstance(source, dict) or set(source.keys()) != _SOURCE_KEYS:
        described = sorted(source) if isinstance(source, dict) else source
        failures.append(f"source has unexpected keys: {described!r}")

    for candidate in artifact.get("candidates", []):
        if not isinstance(candidate, dict) or set(candidate.keys()) != _CANDIDATE_KEYS:
            described = sorted(candidate) if isinstance(candidate, dict) else candidate
            failures.append(f"candidate has unexpected keys: {described!r}")
            continue
        if candidate.get("confidence") not in _CONFIDENCE_VALUES:
            failures.append(f"candidate has invalid confidence: {candidate.get('confidence')!r}")
        for id_field in ("master_id", "release_id"):
            value = candidate.get(id_field)
            if value is not None and (not isinstance(value, int) or value <= 0):
                failures.append(f"candidate {id_field} must be a positive int or null: {value!r}")

    if failures:
        raise CohortSourceValidationError("; ".join(failures))

    serialized = json.dumps(artifact)
    for forbidden in _FORBIDDEN_SUBSTRINGS:
        if forbidden in serialized:
            raise CohortSourceValidationError(
                f"artifact contains forbidden substring: {forbidden!r}"
            )
