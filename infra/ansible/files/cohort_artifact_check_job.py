#!/usr/bin/env python3
"""Standalone cohort-artifact validation job bodies, for a Pi worker's RQ queue.

Self-contained (stdlib only) on purpose -- this repo is one monorepo
`pyproject.toml` with a single shared `dependencies = [duckdb, lxml, pyarrow]`
list covering both `networked_players_catalog` and
`networked_players_graph_core`, so importing *any* graph-core module at all
would require installing lxml/pyarrow on the Pi, which
`equip-workers.yml`'s lean venv (redis/rq/duckdb only) deliberately avoids --
regardless of whether the specific function needed actually touches those
dependencies (neither of the two mirrored here does).

These are hand-maintained MIRRORS of
`networked_players_graph_core.cohort_connectivity.validate_connectivity` and
`networked_players_graph_core.cohort_promote.validate_playable_cohort` -- the
real reference implementations, tested normally under packages/graph-core.
If either function's contract changes, mirror the change here too;
packages/graph-core/tests/test_cohort_check_job_body.py cross-checks the two
against the same synthetic inputs to catch drift.

Unlike the reference functions (which raise on the first accumulated set of
failures), these return a plain, always-complete
`{"valid": bool, "failures": list[str]}` dict -- an RQ job needs a
serializable result, and an ambient check exists to surface every problem at
once, not just the first.

Deployed by infra/ansible/playbooks/deploy-cohort-check-job.yml. Enqueued by
scripts/enqueue_cohort_check.py via
``Queue(...).enqueue("cohort_artifact_check_job.check_connectivity", artifact_path)``
or ``.check_playable_cohort``. Takes an artifact file path as its only
argument -- no dataset, no CreditGraph, no network; safe to run against any
already-produced artifact at any time.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# --- shared strength-flag vocabulary (mirrors cohort_connectivity._STRENGTH_FLAGS) ---
_STRENGTH_FLAGS = frozenset({"co_billed_release_artists", "performer_credit", "non_performer_only"})

# --- connectivity (mirrors cohort_connectivity.py's constants) ---
_CONNECTIVITY_SCHEMA_VERSION = 1
_CONNECTIVITY_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "source",
        "scorer_version",
        "generated_at",
        "dataset_snapshot_date",
        "max_hops",
        "pairs",
        "unresolved",
    }
)
_CONNECTIVITY_PAIR_KEYS = frozenset(
    {
        "album_a_id",
        "album_b_id",
        "artist_a_id",
        "artist_b_id",
        "status",
        "hop_count",
        "difficulty",
        "hops",
        "warnings",
        "skip_reason",
    }
)
_CONNECTIVITY_HOP_KEYS = frozenset({"release_id", "artist_a_id", "artist_b_id", "quality_flags"})
_CONNECTIVITY_STATUSES = frozenset({"found", "no_path", "skipped"})
_CONNECTIVITY_SKIP_REASONS = frozenset({"seed_expansion_timeout", "frontier_too_large"})
_DIFFICULTIES = frozenset({"easy", "medium", "hard", "very_hard"})

# --- playable-cohort (mirrors cohort_promote.py's constants) ---
_PLAYABLE_COHORT_SCHEMA_VERSION = 1
_PLAYABLE_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "cohort_id",
        "attribution_label",
        "source_url",
        "generated_from_scorer_version",
        "reviewed_at",
        "review_note",
        "albums",
        "pairs",
    }
)
_PLAYABLE_ALBUM_KEYS = frozenset({"id", "artist_id", "artist", "title", "year"})
_PLAYABLE_PAIR_KEYS = frozenset(
    {
        "album_a_id",
        "album_b_id",
        "artist_a_id",
        "artist_b_id",
        "difficulty",
        "hop_count",
        "hops",
        "warnings",
    }
)
_PLAYABLE_HOP_KEYS = frozenset({"release_id", "artist_a_id", "artist_b_id", "quality_flags"})

# Shared by both artifact types' leak scan.
_FORBIDDEN_SUBSTRINGS = ("/home/", "data/private", "local/", "DISCOGS_TOKEN", ".ssh")
# Only playable-cohort-v1 carries free-text (review_note) worth tone-scanning --
# connectivity.json's own validate_connectivity has no such scan either.
_FORBIDDEN_PHRASES = ("worked with", "collaborated with", "influenced")


def _check_connectivity_artifact(artifact: dict[str, Any]) -> list[str]:
    failures: list[str] = []

    if set(artifact.keys()) != _CONNECTIVITY_TOP_LEVEL_KEYS:
        failures.append(f"unexpected top-level keys: {sorted(artifact.keys())}")
    if artifact.get("schema_version") != _CONNECTIVITY_SCHEMA_VERSION:
        failures.append(f"schema_version must be {_CONNECTIVITY_SCHEMA_VERSION}")

    for pair in artifact.get("pairs", []):
        if set(pair.keys()) != _CONNECTIVITY_PAIR_KEYS:
            failures.append(f"pair has unexpected keys: {sorted(pair.keys())}")
            continue
        if pair.get("status") not in _CONNECTIVITY_STATUSES:
            failures.append(f"invalid status: {pair.get('status')!r}")
            continue
        if pair["status"] == "no_path":
            if pair.get("difficulty") is not None or pair.get("hop_count") is not None:
                failures.append("no_path pair must have null hop_count/difficulty")
            if pair.get("skip_reason") is not None:
                failures.append("no_path pair must have null skip_reason")
        elif pair["status"] == "skipped":
            if pair.get("difficulty") is not None or pair.get("hop_count") is not None:
                failures.append("skipped pair must have null hop_count/difficulty")
            if pair.get("skip_reason") not in _CONNECTIVITY_SKIP_REASONS:
                failures.append(f"invalid skip_reason: {pair.get('skip_reason')!r}")
        else:
            if pair.get("skip_reason") is not None:
                failures.append("found pair must have null skip_reason")
            if pair.get("difficulty") not in _DIFFICULTIES:
                failures.append(f"invalid difficulty: {pair.get('difficulty')!r}")
            for hop in pair.get("hops", []):
                if set(hop.keys()) != _CONNECTIVITY_HOP_KEYS:
                    failures.append(f"hop has unexpected keys: {sorted(hop.keys())}")
                    continue
                strength_flags = [f for f in hop["quality_flags"] if f in _STRENGTH_FLAGS]
                if len(strength_flags) != 1:
                    failures.append(
                        f"hop on release {hop.get('release_id')} must have exactly one "
                        f"strength flag, got {strength_flags}"
                    )

    serialized = json.dumps(artifact)
    for forbidden in _FORBIDDEN_SUBSTRINGS:
        if forbidden in serialized:
            failures.append(f"artifact contains forbidden substring: {forbidden!r}")

    return failures


def _check_playable_cohort_artifact(artifact: dict[str, Any]) -> list[str]:
    failures: list[str] = []

    if set(artifact.keys()) != _PLAYABLE_TOP_LEVEL_KEYS:
        failures.append(f"unexpected top-level keys: {sorted(artifact.keys())}")
    if artifact.get("schema_version") != _PLAYABLE_COHORT_SCHEMA_VERSION:
        failures.append(f"schema_version must be {_PLAYABLE_COHORT_SCHEMA_VERSION}")

    album_ids: set[Any] = set()
    for album in artifact.get("albums", []):
        if set(album.keys()) != _PLAYABLE_ALBUM_KEYS:
            failures.append(f"album {album.get('id')} has unexpected keys: {sorted(album.keys())}")
            continue
        album_ids.add(album.get("id"))

    for pair in artifact.get("pairs", []):
        if set(pair.keys()) != _PLAYABLE_PAIR_KEYS:
            failures.append(f"pair has unexpected keys: {sorted(pair.keys())}")
            continue
        if pair.get("album_a_id") not in album_ids or pair.get("album_b_id") not in album_ids:
            failures.append(
                f"pair {pair.get('album_a_id')} <-> {pair.get('album_b_id')} references an "
                "unpublished album"
            )
        if pair.get("difficulty") not in _DIFFICULTIES:
            failures.append(f"invalid difficulty: {pair.get('difficulty')!r}")
        for hop in pair.get("hops", []):
            if set(hop.keys()) != _PLAYABLE_HOP_KEYS:
                failures.append(f"hop has unexpected keys: {sorted(hop.keys())}")
                continue
            strength_flags = [f for f in hop["quality_flags"] if f in _STRENGTH_FLAGS]
            if len(strength_flags) != 1:
                failures.append(
                    f"hop on release {hop.get('release_id')} must have exactly one strength "
                    f"flag, got {strength_flags}"
                )

    serialized = json.dumps(artifact)
    for forbidden in _FORBIDDEN_SUBSTRINGS:
        if forbidden in serialized:
            failures.append(f"artifact contains forbidden substring: {forbidden!r}")

    lowered = serialized.lower()
    for phrase in _FORBIDDEN_PHRASES:
        if phrase in lowered:
            failures.append(f"artifact contains forbidden phrase: {phrase!r}")

    return failures


def check_connectivity(artifact_path: str) -> dict[str, Any]:
    artifact = json.loads(Path(artifact_path).read_text())
    failures = _check_connectivity_artifact(artifact)
    return {"valid": not failures, "failures": failures}


def check_playable_cohort(artifact_path: str) -> dict[str, Any]:
    artifact = json.loads(Path(artifact_path).read_text())
    failures = _check_playable_cohort_artifact(artifact)
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
