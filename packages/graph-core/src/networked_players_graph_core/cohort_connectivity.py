"""Score real graph connectivity between every pair of resolved cohort albums
(PR 2's `album-cohort-resolved-v1.json`). See
data/contracts/album-cohort-connectivity-v1.md and
docs/decisions/0029-connectivity-scorer-flags-dont-fix-traversal-gap.md.

Important gap this module exists to catch: `CreditGraph`'s own traversal
(`NON_INDIVIDUAL_ARTIST_IDS`, `graph.py`) only excludes artist_id 194
("Various Artists") -- it is NOT the same exclusion set
`networked_players_catalog.discogs.onehop`'s `_NON_PLAYABLE_HUB_ARTIST_IDS`
(also excludes 151641, "Trad.") and `_NON_PERFORMER_ROLE_TOKENS` apply when
building the one-hop dataset itself. Those exclusions only control which
releases get *retained*; once a release is retained, ALL its credit rows
survive as evidence (by design -- evidence completeness), so a hop can still
traverse through a placeholder identity or a purely non-performer credit if
it happens to sit on an already-retained release. This module does not
change `CreditGraph`'s traversal (that would silently alter `challenge.py`'s
already-live behavior) -- it flags this class of connection post-hoc for
human review instead. See ADR 0029 for the full reasoning.

This module never imports from `networked_players_catalog` (graph-core's
standing rule: catalog -> graph-core only, never the reverse) -- the
placeholder-artist-ID set and non-performer role tokens below are kept as
our own copy, the same precedent `graph.py`'s own `NON_INDIVIDUAL_ARTIST_IDS`
already uses.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .graph import CreditGraph

CONNECTIVITY_SCHEMA_VERSION = 1
SCORER_VERSION = 1

_TOP_LEVEL_KEYS = frozenset(
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
_PAIR_KEYS = frozenset(
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
    }
)
_HOP_KEYS = frozenset({"release_id", "artist_a_id", "artist_b_id", "quality_flags"})
_STATUSES = frozenset({"found", "no_path"})
_DIFFICULTIES = frozenset({"easy", "medium", "hard", "very_hard"})
_STRENGTH_FLAGS = frozenset({"co_billed_release_artists", "performer_credit", "non_performer_only"})
_FORBIDDEN_SUBSTRINGS = ("/home/", "data/private", "local/", "DISCOGS_TOKEN", ".ssh")

# Discogs canonical placeholder identities -- kept as our own copy of
# onehop.py's _NON_PLAYABLE_HUB_ARTIST_IDS (not imported, per the
# no-reverse-dependency rule above). CreditGraph's own NON_INDIVIDUAL_ARTIST_IDS
# only excludes 194, so 151641 can still appear as a live hop endpoint.
_PLACEHOLDER_ARTIST_IDS = frozenset({194, 151641})

# Exact copy of onehop.py's _NON_PERFORMER_ROLE_TOKENS.
_NON_PERFORMER_ROLE_TOKENS = frozenset(
    {
        "written-by",
        "written by",
        "mastered by",
        "mixed by",
        "recorded by",
        "lacquer cut by",
        "arranged by",
        "liner notes",
        "composed by",
        "lyrics by",
        "music by",
        "words by",
        "engineer",
        "producer",
        "co-producer",
        "design",
        "design concept",
        "photography by",
    }
)

_BRACKET_SUFFIX_RE = re.compile(r"\[.*\]")

# Every generated sentence describing a connection must use this phrase, per
# docs/DATA_AND_RIGHTS.md's standing rule against inferring relationships
# from credits -- never "worked with"/"collaborated with".
_CONNECTION_PHRASE = "connected via a shared release credit"


class CohortConnectivityError(RuntimeError):
    """Raised when a connectivity artifact can't be built or violates its contract."""


def _album_id(entry: dict[str, Any]) -> str:
    master_id = entry.get("master_id")
    return f"master-{master_id}" if master_id else f"release-{entry['release_id']}"


def _is_non_performer_role(role_text: str | None) -> bool:
    """Python port of onehop.py's `_performer_credit_sql`, negated: True only
    when role_text is non-null and every comma-separated component is a known
    non-performer token. An unlisted component always means "keep" (False) --
    an incomplete list can only under-flag, never silently over-flag."""
    if role_text is None:
        return False
    components = role_text.split(",")
    for component in components:
        stripped = _BRACKET_SUFFIX_RE.sub("", component).strip().lower()
        if stripped not in _NON_PERFORMER_ROLE_TOKENS:
            return False
    return True


def _artist_credit_tier(rows: list[dict[str, Any]], artist_id: int) -> str:
    """One of "release_artist" / "performer" / "non_performer" for the given
    artist's credit(s) on the release these rows came from."""
    artist_rows = [row for row in rows if row["artist_id"] == artist_id]
    if any(row["credit_scope"] == "release_artist" for row in artist_rows):
        return "release_artist"
    if any(not _is_non_performer_role(row["role_text"]) for row in artist_rows):
        return "performer"
    return "non_performer"


def classify_hop_quality(
    rows_a: list[dict[str, Any]],
    rows_b: list[dict[str, Any]],
    *,
    artist_a_id: int,
    artist_b_id: int,
) -> list[str]:
    """Exactly one strength flag, plus an independent stackable placeholder flag."""
    tier_a = _artist_credit_tier(rows_a, artist_a_id)
    tier_b = _artist_credit_tier(rows_b, artist_b_id)

    if tier_a == "release_artist" and tier_b == "release_artist":
        flags = ["co_billed_release_artists"]
    elif "release_artist" in (tier_a, tier_b) or "performer" in (tier_a, tier_b):
        flags = ["performer_credit"]
    else:
        flags = ["non_performer_only"]

    if artist_a_id in _PLACEHOLDER_ARTIST_IDS or artist_b_id in _PLACEHOLDER_ARTIST_IDS:
        flags.append("placeholder_artist_hop")

    return flags


def _difficulty_for_hop_count(hop_count: int) -> str:
    return {1: "easy", 2: "medium", 3: "hard"}.get(hop_count, "very_hard")


def _pair_warnings(hops: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    for index, hop in enumerate(hops, start=1):
        if "non_performer_only" in hop["quality_flags"]:
            warnings.append(
                f"hop {index} (release {hop['release_id']}) connects artist "
                f"{hop['artist_a_id']} and {hop['artist_b_id']} only via "
                "non-performer-caliber credits (e.g. Mastered By, Producer) -- "
                "no performer-caliber evidence on this release"
            )
        if "placeholder_artist_hop" in hop["quality_flags"]:
            placeholder_id = next(
                a for a in (hop["artist_a_id"], hop["artist_b_id"]) if a in _PLACEHOLDER_ARTIST_IDS
            )
            warnings.append(
                f"hop {index} (release {hop['release_id']}) involves placeholder "
                f"artist {placeholder_id} -- should not normally survive as "
                "connecting evidence in a well-behaved one-hop dataset"
            )
    return warnings


def score_pairs(
    graph: CreditGraph, resolved_albums: list[dict[str, Any]], *, max_hops: int = 3
) -> list[dict[str, Any]]:
    """Every unordered pair of resolved albums, sorted by album_id (mirrors
    challenge.py's `ordered = sorted(matched, key=lambda m: m.album_id)` +
    `i, i+1:` loop). Never drops a pair -- unreachable pairs get
    `status="no_path"` rather than being silently omitted.
    """
    ordered = sorted(resolved_albums, key=_album_id)
    pairs: list[dict[str, Any]] = []

    for i, album_a in enumerate(ordered):
        for album_b in ordered[i + 1 :]:
            artist_a_id = album_a["artist_id"]
            artist_b_id = album_b["artist_id"]
            # PR 2 already guarantees unique artist_id across resolved[] --
            # documented here as a relied-upon invariant, not trusted silently.
            assert artist_a_id != artist_b_id, "resolved albums must have distinct artist_id"

            path = graph.find_path(artist_a_id, artist_b_id, max_hops=max_hops)
            if path is None:
                pairs.append(
                    {
                        "album_a_id": _album_id(album_a),
                        "album_b_id": _album_id(album_b),
                        "artist_a_id": artist_a_id,
                        "artist_b_id": artist_b_id,
                        "status": "no_path",
                        "hop_count": None,
                        "difficulty": None,
                        "hops": [],
                        "warnings": [],
                    }
                )
                continue

            hops: list[dict[str, Any]] = []
            for hop in path.hops:
                rows = graph.credit_rows(hop.release_id, {hop.artist_a_id, hop.artist_b_id})
                rows_a = [r for r in rows if r["artist_id"] == hop.artist_a_id]
                rows_b = [r for r in rows if r["artist_id"] == hop.artist_b_id]
                quality_flags = classify_hop_quality(
                    rows_a, rows_b, artist_a_id=hop.artist_a_id, artist_b_id=hop.artist_b_id
                )
                hops.append(
                    {
                        "release_id": hop.release_id,
                        "artist_a_id": hop.artist_a_id,
                        "artist_b_id": hop.artist_b_id,
                        "quality_flags": quality_flags,
                    }
                )

            pairs.append(
                {
                    "album_a_id": _album_id(album_a),
                    "album_b_id": _album_id(album_b),
                    "artist_a_id": artist_a_id,
                    "artist_b_id": artist_b_id,
                    "status": "found",
                    "hop_count": len(hops),
                    "difficulty": _difficulty_for_hop_count(len(hops)),
                    "hops": hops,
                    "warnings": _pair_warnings(hops),
                }
            )

    return pairs


def build_connectivity_cohort(
    graph: CreditGraph,
    resolved: dict[str, Any],
    *,
    dataset_snapshot_date: str,
    max_hops: int = 3,
    max_pairs: int = 1000,
) -> dict[str, Any]:
    if resolved.get("dataset_snapshot_date") != dataset_snapshot_date:
        raise CohortConnectivityError(
            f"resolved.json was resolved against snapshot "
            f"{resolved.get('dataset_snapshot_date')!r}, but this dataset is "
            f"snapshot {dataset_snapshot_date!r} -- refusing to score against a "
            "mismatched dataset vintage"
        )

    resolved_albums = resolved.get("resolved", [])
    pair_count = len(resolved_albums) * (len(resolved_albums) - 1) // 2
    if pair_count > max_pairs:
        raise CohortConnectivityError(
            f"cohort has {len(resolved_albums)} resolved albums ({pair_count} "
            f"unordered pairs), exceeding --max-pairs={max_pairs}; raise the "
            "bound explicitly or split the cohort -- pairs are never silently "
            "sampled or truncated"
        )

    pairs = score_pairs(graph, resolved_albums, max_hops=max_hops)

    return {
        "schema_version": CONNECTIVITY_SCHEMA_VERSION,
        "source": resolved.get("source", {}),
        "scorer_version": SCORER_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset_snapshot_date": dataset_snapshot_date,
        "max_hops": max_hops,
        "pairs": pairs,
        "unresolved": resolved.get("unresolved", []),
    }


def write_connectivity_cohort(artifact: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")


def validate_connectivity(artifact: dict[str, Any]) -> None:
    failures: list[str] = []

    if set(artifact.keys()) != _TOP_LEVEL_KEYS:
        failures.append(f"unexpected top-level keys: {sorted(artifact.keys())}")
    if artifact.get("schema_version") != CONNECTIVITY_SCHEMA_VERSION:
        failures.append(f"schema_version must be {CONNECTIVITY_SCHEMA_VERSION}")

    for pair in artifact.get("pairs", []):
        if set(pair.keys()) != _PAIR_KEYS:
            failures.append(f"pair has unexpected keys: {sorted(pair.keys())}")
            continue
        if pair.get("status") not in _STATUSES:
            failures.append(f"invalid status: {pair.get('status')!r}")
            continue
        if pair["status"] == "no_path":
            if pair.get("difficulty") is not None or pair.get("hop_count") is not None:
                failures.append("no_path pair must have null hop_count/difficulty")
        else:
            if pair.get("difficulty") not in _DIFFICULTIES:
                failures.append(f"invalid difficulty: {pair.get('difficulty')!r}")
            for hop in pair.get("hops", []):
                if set(hop.keys()) != _HOP_KEYS:
                    failures.append(f"hop has unexpected keys: {sorted(hop.keys())}")
                    continue
                strength_flags = [f for f in hop["quality_flags"] if f in _STRENGTH_FLAGS]
                if len(strength_flags) != 1:
                    failures.append(
                        f"hop on release {hop.get('release_id')} must have exactly one "
                        f"strength flag, got {strength_flags}"
                    )

    if failures:
        raise CohortConnectivityError("; ".join(failures))

    serialized = json.dumps(artifact)
    for forbidden in _FORBIDDEN_SUBSTRINGS:
        if forbidden in serialized:
            raise CohortConnectivityError(f"artifact contains forbidden substring: {forbidden!r}")


def summarize_connectivity(artifact: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    """Pure Python -- no CreditGraph/DuckDB anywhere in this function's call
    graph. This is deliberate: a future Pi ambient job can mirror this
    function standalone (the same relationship verify_challenge_job.py
    already has to verify.py) without needing the heavier graph dependency.
    """
    playable_pairs = sorted(
        (pair for pair in artifact["pairs"] if pair["status"] == "found"),
        key=lambda pair: (pair["hop_count"], pair["album_a_id"], pair["album_b_id"]),
    )

    found = [p for p in artifact["pairs"] if p["status"] == "found"]
    no_path = [p for p in artifact["pairs"] if p["status"] == "no_path"]
    flagged = [p for p in artifact["pairs"] if p["warnings"]]
    by_difficulty: dict[str, int] = {}
    for pair in found:
        by_difficulty[pair["difficulty"]] = by_difficulty.get(pair["difficulty"], 0) + 1

    lines = [
        "# Cohort connectivity review report",
        "",
        "## Header",
        "",
        f"- Source: {artifact['source'].get('page_title', '(unknown)')} "
        f"({artifact['source'].get('source_url', '(unknown)')})",
        f"- Generated at: {artifact['generated_at']}",
        f"- Dataset snapshot: {artifact['dataset_snapshot_date']}",
        f"- Scorer version: {artifact['scorer_version']}",
        f"- Max hops: {artifact['max_hops']}",
        "",
        "## Summary counts",
        "",
        f"- Total pairs: {len(artifact['pairs'])}",
        f"- Found: {len(found)}",
        f"- No path: {len(no_path)}",
        f"- Flagged for review: {len(flagged)}",
        "- Difficulty breakdown: "
        + ", ".join(f"{k}={v}" for k, v in sorted(by_difficulty.items())),
        "",
        "## Flagged pairs",
        "",
    ]
    if flagged:
        for pair in flagged:
            lines.append(
                f"- {pair['album_a_id']} <-> {pair['album_b_id']} "
                f"({_CONNECTION_PHRASE}, difficulty {pair['difficulty']}):"
            )
            for warning in pair["warnings"]:
                lines.append(f"  - {warning}")
    else:
        lines.append("None.")
    lines.append("")

    lines.append("## No-path pairs")
    lines.append("")
    if no_path:
        for pair in no_path:
            lines.append(
                f"- {pair['album_a_id']} <-> {pair['album_b_id']}: no documented "
                f"path found within {artifact['max_hops']} hops"
            )
    else:
        lines.append("None.")
    lines.append("")

    lines.append("## Unresolved albums carried forward")
    lines.append("")
    unresolved = artifact.get("unresolved", [])
    if unresolved:
        for entry in unresolved:
            lines.append(
                f"- {entry.get('artist')!r} / {entry.get('title')!r}: "
                f"{entry.get('reason', '(no reason recorded)')}"
            )
    else:
        lines.append("None.")
    lines.append("")

    return playable_pairs, "\n".join(lines) + "\n"
