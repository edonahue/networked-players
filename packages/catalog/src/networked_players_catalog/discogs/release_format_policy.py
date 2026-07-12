"""Deterministic, explainable release-format classification."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

POLICY_NAME = "studio-album-v1"
POLICY_VERSION = 1

_EXCLUDE_DESCRIPTORS = {
    "compilation": "explicit_compilation",
    "sampler": "explicit_sampler",
    "single": "explicit_single",
    "maxi-single": "explicit_maxi_single",
    "ep": "explicit_ep",
    "mini-album": "explicit_mini_album",
    "mixtape": "explicit_mixtape",
    "live": "explicit_live",
    "bootleg": "explicit_bootleg",
    "unofficial release": "explicit_unofficial",
    "remix": "explicit_remix",
    "soundtrack": "explicit_soundtrack",
    "box set": "explicit_box_set",
}
_TITLE_SIGNAL_PATTERN = re.compile(
    r"\b(compilations?|samplers?|greatest hits|best of|antholog(?:y|ies)|"
    r"collections?|rarit(?:y|ies)|bootlegs?|mash[- ]?ups?|live(?:box)?|"
    r"remixes?|reissues?|soundtracks?|sound collages?|singles?|box sets?|mixtapes?)\b",
    re.IGNORECASE,
)


def _norm(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def classify_formats(formats: list[dict[str, Any]]) -> dict[str, Any]:
    """Classify one release's structured format rows.

    The policy deliberately requires the factual ``Album`` descriptor. A
    carrier such as LP or CD is not enough, and explicit Compilation wins over
    Album for this first curated cohort.
    """
    descriptors = [_norm(d) for row in formats for d in (row.get("descriptions") or [])]
    names = [_norm(row.get("format_name")) for row in formats if row.get("format_name")]
    signals: list[str] = []
    if not formats:
        return {
            "decision": "review",
            "shape": "unknown",
            "signals": ["missing_formats"],
            "format_names": [],
            "descriptors": [],
        }
    excluded = [
        signal for descriptor, signal in _EXCLUDE_DESCRIPTORS.items() if descriptor in descriptors
    ]
    if excluded:
        signals.extend(excluded)
        shape = "compilation" if "explicit_compilation" in excluded else "unknown"
        return {
            "decision": "exclude",
            "shape": shape,
            "signals": signals,
            "format_names": names,
            "descriptors": descriptors,
        }
    if "album" in descriptors:
        return {
            "decision": "allow",
            "shape": "studio_album",
            "signals": ["explicit_album"],
            "format_names": names,
            "descriptors": descriptors,
        }
    return {
        "decision": "review",
        "shape": "unknown",
        "signals": ["album_descriptor_missing"],
        "format_names": names,
        "descriptors": descriptors,
    }


def build_release_format_policy(
    dataset_root: Path, *, policy_name: str = POLICY_NAME
) -> dict[str, Any]:
    if policy_name != POLICY_NAME:
        raise ValueError(f"unsupported release format policy: {policy_name}")
    root = Path(dataset_root)
    manifest = json.loads((root / "manifest.json").read_text())
    connection = duckdb.connect(database=":memory:")
    try:
        release_glob = str(root / "table=releases" / "*.parquet")
        formats_glob = str(root / "table=release_formats" / "*.parquet")
        rows = connection.execute(
            f"""
            SELECT r.release_id, f.format_name, f.descriptions
            FROM read_parquet('{release_glob}', hive_partitioning = false) r
            LEFT JOIN read_parquet('{formats_glob}', hive_partitioning = false) f
              USING (release_id)
            ORDER BY r.release_id, f.format_index
            """
        ).fetchall()
    finally:
        connection.close()

    classifications: list[dict[str, Any]] = []
    by_release: dict[int, list[dict[str, Any]]] = {}
    for release_id, format_name, descriptions in rows:
        if format_name is not None:
            by_release.setdefault(int(release_id), []).append(
                {"format_name": format_name, "descriptions": descriptions or []}
            )
        else:
            by_release.setdefault(int(release_id), [])
    for release_id, normalized_rows in by_release.items():
        result = classify_formats(normalized_rows)
        classifications.append(
            {
                "snapshot_date": str(manifest["snapshot_date"]),
                "release_id": int(release_id),
                "policy_name": POLICY_NAME,
                "policy_version": POLICY_VERSION,
                **result,
            }
        )
    return {
        "schema_version": 1,
        "policy_name": POLICY_NAME,
        "policy_version": POLICY_VERSION,
        "snapshot_date": str(manifest["snapshot_date"]),
        "dataset_manifest_sha256": hashlib.sha256(
            (root / "manifest.json").read_bytes()
        ).hexdigest(),
        "parser_version": manifest.get("parser_version"),
        "generated_at": datetime.now(UTC).isoformat(),
        "classifications": classifications,
    }


def write_release_format_policy(policy: dict[str, Any], output: Path) -> None:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_name(f".{output.name}.tmp-{uuid.uuid4().hex}")
    try:
        staging.write_text(json.dumps(policy, indent=2, sort_keys=True) + "\n")
        staging.replace(output)
    except Exception:
        staging.unlink(missing_ok=True)
        raise


def build_release_format_scoring_index(policy: dict[str, Any]) -> dict[str, Any]:
    """Build the compact allow-list consumed by graph scoring.

    The full policy keeps reasons and normalized descriptors for editorial
    review. Scoring only needs the releases explicitly allowed by the policy,
    so this index avoids loading that larger review artifact on a worker.
    """
    canonical_policy = json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()
    allowed_release_ids = sorted(
        int(item["release_id"]) for item in policy["classifications"] if item["decision"] == "allow"
    )
    return {
        "schema_version": 1,
        "kind": "release-format-scoring-index",
        "policy_name": policy["policy_name"],
        "policy_version": policy["policy_version"],
        "snapshot_date": policy["snapshot_date"],
        "source_policy_sha256": hashlib.sha256(canonical_policy).hexdigest(),
        "allowed_release_count": len(allowed_release_ids),
        "allowed_release_ids": allowed_release_ids,
    }


def write_release_format_scoring_index(index: dict[str, Any], output: Path) -> None:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_name(f".{output.name}.tmp-{uuid.uuid4().hex}")
    try:
        staging.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")
        staging.replace(output)
    except Exception:
        staging.unlink(missing_ok=True)
        raise


def build_format_policy_shadow_report(dataset_root: Path, policy: dict[str, Any]) -> dict[str, Any]:
    """Compare the legacy title guard with a generated format policy."""
    root = Path(dataset_root)
    release_glob = str(root / "table=releases" / "*.parquet")
    connection = duckdb.connect(database=":memory:")
    try:
        releases = connection.execute(
            f"SELECT release_id, title FROM read_parquet('{release_glob}', hive_partitioning=false)"
        ).fetchall()
    finally:
        connection.close()
    classifications = {int(item["release_id"]): item for item in policy["classifications"]}
    disagreements: list[dict[str, Any]] = []
    counts = {
        "release_count": len(releases),
        "title_filtered_count": 0,
        "format_allow_count": 0,
        "format_exclude_count": 0,
        "format_review_count": 0,
        "title_only_allowed_format_excluded": 0,
        "title_filtered_format_allowed": 0,
    }
    for release_id, title in releases:
        title_filtered = bool(_TITLE_SIGNAL_PATTERN.search(str(title or "")))
        classification = classifications[int(release_id)]
        format_decision = classification["decision"]
        counts[f"format_{format_decision}_count"] += 1
        counts["title_filtered_count"] += int(title_filtered)
        if title_filtered and format_decision == "allow":
            counts["title_filtered_format_allowed"] += 1
            disagreements.append(
                {
                    "release_id": int(release_id),
                    "title": title,
                    "kind": "title_filtered_format_allowed",
                }
            )
        elif not title_filtered and format_decision == "exclude":
            counts["title_only_allowed_format_excluded"] += 1
            disagreements.append(
                {
                    "release_id": int(release_id),
                    "title": title,
                    "kind": "title_only_allowed_format_excluded",
                }
            )
    return {
        "schema_version": 1,
        "policy_name": policy.get("policy_name"),
        "policy_version": policy.get("policy_version"),
        "snapshot_date": policy.get("snapshot_date"),
        "generated_at": datetime.now(UTC).isoformat(),
        "counts": counts,
        "disagreements": disagreements,
    }
