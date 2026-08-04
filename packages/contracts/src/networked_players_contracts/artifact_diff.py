"""Structurally diff two artifact JSON payloads -- the publication train's
"semantic diff" stage (docs/PUBLIC_PRIVATE_BOUNDARY.md's pre-publication
checklist, docs/PHASE2_PLAN.md's spine table), which today is a manual
byte-for-byte diff against the prior committed file (ADR 0043's actual
practice). This formalizes that as a real, reusable command rather than
full CI automation -- still a manual step a publisher runs, just no longer
a manual eyeballed diff.

Reuses `canonical_json`/`content_hash` from `canonical.py` so key-order and
whitespace differences never produce a false-positive diff -- the same
guarantee content-hash-based `*_version` fields already depend on.
"""

from __future__ import annotations

from typing import Any

from .canonical import content_hash

# Fields treated as "version fields" across every artifact type in this
# repo, called out on their own in the report even when nested -- a
# version bump or mismatch is the single most actionable signal a
# publisher needs to see first, before wading into the full structural
# diff.
_VERSION_FIELD_NAMES = frozenset(
    {
        "catalog_version",
        "pool_version",
        "artifact_version",
        "exploration_corpus_version",
        "contributor_index_version",
        "pathfinding_graph_version",
    }
)


def _version_field_changes(old: Any, new: Any) -> dict[str, dict[str, Any]]:
    changes: dict[str, dict[str, Any]] = {}
    if not (isinstance(old, dict) and isinstance(new, dict)):
        return changes
    for key in sorted(_VERSION_FIELD_NAMES):
        if key not in old and key not in new:
            continue
        old_value = old.get(key)
        new_value = new.get(key)
        if old_value != new_value:
            changes[key] = {"old": old_value, "new": new_value}
    return changes


def _structural_diff(old: Any, new: Any, path: str = "$") -> list[dict[str, Any]]:
    """A recursive added/removed/changed report. Dict keys are compared by
    name. Lists of equal length are compared index-wise (so a change deep
    inside one element of a long array is reported precisely, not as one
    giant "changed" blob); a length change is reported directly, since
    every artifact in this repo is generated deterministically (sorted
    keys, stable ordering) -- an unexplained reorder is itself meaningful,
    not noise to suppress."""
    diffs: list[dict[str, Any]] = []
    if isinstance(old, dict) and isinstance(new, dict):
        old_keys = set(old)
        new_keys = set(new)
        for key in sorted(old_keys - new_keys):
            diffs.append({"path": f"{path}.{key}", "change": "removed", "old": old[key]})
        for key in sorted(new_keys - old_keys):
            diffs.append({"path": f"{path}.{key}", "change": "added", "new": new[key]})
        for key in sorted(old_keys & new_keys):
            diffs.extend(_structural_diff(old[key], new[key], f"{path}.{key}"))
    elif isinstance(old, list) and isinstance(new, list):
        if len(old) != len(new):
            diffs.append(
                {
                    "path": path,
                    "change": "list-length-changed",
                    "old_length": len(old),
                    "new_length": len(new),
                }
            )
        else:
            for index, (old_item, new_item) in enumerate(zip(old, new, strict=True)):
                diffs.extend(_structural_diff(old_item, new_item, f"{path}[{index}]"))
    else:
        if old != new:
            diffs.append({"path": path, "change": "changed", "old": old, "new": new})
    return diffs


def artifact_diff(old: Any, new: Any) -> dict[str, Any]:
    """Compare two artifact JSON payloads. Short-circuits to `identical` via
    `content_hash` equality (so a re-serialization with different key order
    or whitespace never reports a false diff); otherwise reports
    version-field changes specifically, plus a full structural diff of
    everything else."""
    old_hash = content_hash(old)
    new_hash = content_hash(new)
    if old_hash == new_hash:
        return {
            "identical": True,
            "content_hash": old_hash,
            "version_field_changes": {},
            "structural_diff": [],
        }
    return {
        "identical": False,
        "old_content_hash": old_hash,
        "new_content_hash": new_hash,
        "version_field_changes": _version_field_changes(old, new),
        "structural_diff": _structural_diff(old, new),
    }
