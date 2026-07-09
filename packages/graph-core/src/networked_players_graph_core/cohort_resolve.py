"""Resolve extracted cohort candidates (from a saved-source import; see
`networked_players_catalog.cohort_source`) against a real parsed Discogs
dataset. See data/contracts/album-cohort-resolved-v1.md.

This module never imports from `networked_players_catalog` (graph-core's
standing rule: catalog -> graph-core only, never the reverse) -- candidates
are plain dicts, the same convention `challenge.match_albums` already uses
for its editorial album list.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .graph import CreditGraph

RESOLVER_VERSION = 1
RESOLVED_SCHEMA_VERSION = 1

_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "source",
        "resolver_version",
        "generated_at",
        "dataset_snapshot_date",
        "resolved",
        "unresolved",
    }
)
_RESOLVED_KEYS = frozenset(
    {
        "rank",
        "artist_query",
        "title_query",
        "resolution_method",
        "master_id",
        "release_id",
        "title",
        "artist_id",
        "artist_name",
        "year",
        "extraction_confidence",
        "warnings",
    }
)
_RESOLUTION_METHODS = frozenset({"release_id_hint", "master_id_hint", "title_artist_match"})
_FORBIDDEN_SUBSTRINGS = ("/home/", "data/private", "local/", "DISCOGS_TOKEN", ".ssh")


class CohortResolveError(RuntimeError):
    """Raised when a resolved-cohort artifact violates its contract."""


def _year_from_released(released: str | None) -> int | None:
    if released and len(released) >= 4 and released[:4].isdigit():
        return int(released[:4])
    return None


@dataclass(slots=True)
class ResolvedAlbum:
    rank: int | None
    artist_query: str | None
    title_query: str | None
    resolution_method: str
    master_id: int | None
    release_id: int
    title: str
    artist_id: int
    artist_name: str
    year: int | None
    extraction_confidence: str
    warnings: list[str]

    @property
    def album_id(self) -> str:
        return f"master-{self.master_id}" if self.master_id else f"release-{self.release_id}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _text_mismatch_warnings(
    *,
    title: str,
    artist_name: str,
    title_query: str | None,
    artist_query: str | None,
) -> list[str]:
    """Flag when an ID-hint resolution's real title/artist doesn't resemble the
    extracted query text at all -- a strong signal the source HTML's link was
    mislinked to the wrong entry, or points at an unrelated real Discogs
    entity by coincidence. An ID hint is still trusted (never silently
    overridden by text), but a mismatch this large is surfaced for human
    review rather than accepted silently.
    """
    warnings: list[str] = []
    if title_query and title_query.strip().lower() != title.strip().lower():
        warnings.append("resolved title does not match extracted title_query")
    if artist_query and artist_query.strip().lower() != artist_name.strip().lower():
        warnings.append("resolved artist does not match extracted artist_query")
    return warnings


@dataclass(slots=True)
class _CandidateLookup:
    """The pure-lookup outcome for one candidate -- everything that depends
    only on that candidate's own data, never on another candidate or on
    processing order. `used_artist_ids` dedup is deliberately NOT here: it's
    inherently sequential/order-dependent (first candidate wins), applied in
    a second pass over these results, which is what makes the lookup itself
    safe to run concurrently."""

    row: dict[str, Any] | None
    method: str | None
    artist_name: str | None
    reason: str | None  # only set when row is None


def _lookup_candidate(graph: CreditGraph, candidate: dict[str, Any]) -> _CandidateLookup:
    artist_query = candidate.get("artist")
    title_query = candidate.get("title")
    master_id = candidate.get("master_id")
    release_id = candidate.get("release_id")

    row: dict[str, Any] | None = None
    method: str | None = None
    if release_id is not None:
        row = graph.find_release_by_id_hint(release_id=release_id, artist_hint=artist_query)
        method = "release_id_hint"
    elif master_id is not None:
        row = graph.find_release_by_id_hint(master_id=master_id, artist_hint=artist_query)
        method = "master_id_hint"

    if row is None:
        if artist_query and title_query:
            row = graph.find_release_by_title_artist(title_query, artist_query)
            method = "title_artist_match"
        elif master_id is None and release_id is None:
            return _CandidateLookup(None, None, None, "missing artist/title text and no id hint")
        else:
            reason = "id hint not found in dataset; no artist/title text to fall back on"
            return _CandidateLookup(None, None, None, reason)

    if row is None:
        return _CandidateLookup(None, None, None, "no id hint and no title/artist match")

    assert method is not None
    artist_name = graph.artist_name(row["artist_id"]) or row["name"]
    return _CandidateLookup(row, method, artist_name, None)


def _lookup_candidates_concurrently(
    graph: CreditGraph, candidates: list[dict[str, Any]], *, max_workers: int
) -> list[_CandidateLookup]:
    """Spreads each candidate's independent lookup across `max_workers`
    cursors -- same chunk-per-worker shape as `cohort_connectivity.score_pairs`
    and `challenge._find_paths_concurrently`. Returns results in the same
    order as `candidates`, so the caller's sequential dedup pass doesn't need
    to know concurrency happened at all."""
    worker_graphs = [graph.cursor() for _ in range(max_workers)]
    chunks: list[list[int]] = [[] for _ in range(max_workers)]
    for index in range(len(candidates)):
        chunks[index % max_workers].append(index)

    def _run_chunk(worker_index: int) -> list[tuple[int, _CandidateLookup]]:
        worker_graph = worker_graphs[worker_index]
        return [
            (index, _lookup_candidate(worker_graph, candidates[index]))
            for index in chunks[worker_index]
        ]

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        chunk_results = list(pool.map(_run_chunk, range(max_workers)))
    by_index = dict(result for chunk in chunk_results for result in chunk)
    return [by_index[i] for i in range(len(candidates))]


def resolve_candidates(
    graph: CreditGraph, candidates: list[dict[str, Any]], *, max_workers: int = 1
) -> tuple[list[ResolvedAlbum], list[dict[str, Any]]]:
    """Resolve each extracted candidate against the real dataset.

    Prefers an explicit `master_id`/`release_id` hint (never guessed --
    resolution fails cleanly if the hint doesn't exist in this dataset),
    falling back to `find_release_by_title_artist`'s exact text match when no
    hint is present or the hint doesn't resolve. A candidate whose resolved
    `artist_id` was already used by an earlier candidate in this cohort is
    reported unresolved rather than silently duplicated (find_path needs one
    artist per album). Returns `(resolved, unresolved)`; `unresolved` entries
    are the original candidate dict plus a `reason` string -- an ambiguity
    report for human review, nothing is ever silently dropped.

    `max_workers > 1` runs each candidate's own lookup concurrently (see
    `_lookup_candidates_concurrently`); the `used_artist_ids` dedup below
    still applies sequentially afterward in candidate order, so results are
    identical to the `max_workers=1` path regardless of concurrency.
    """
    lookups = (
        _lookup_candidates_concurrently(graph, candidates, max_workers=max_workers)
        if max_workers > 1
        else [_lookup_candidate(graph, candidate) for candidate in candidates]
    )

    resolved: list[ResolvedAlbum] = []
    unresolved: list[dict[str, Any]] = []
    used_artist_ids: set[int] = set()

    for candidate, lookup in zip(candidates, lookups, strict=True):
        if lookup.row is None:
            assert lookup.reason is not None
            unresolved.append({**candidate, "reason": lookup.reason})
            continue

        row = lookup.row
        if row["artist_id"] in used_artist_ids:
            unresolved.append(
                {
                    **candidate,
                    "reason": (
                        f"artist_id {row['artist_id']} already resolved by an "
                        "earlier candidate in this cohort"
                    ),
                }
            )
            continue
        used_artist_ids.add(row["artist_id"])

        assert lookup.method is not None
        artist_query = candidate.get("artist")
        title_query = candidate.get("title")
        artist_name = lookup.artist_name or row["name"]
        warnings = (
            _text_mismatch_warnings(
                title=row["title"],
                artist_name=artist_name,
                title_query=title_query,
                artist_query=artist_query,
            )
            if lookup.method != "title_artist_match"
            else []
        )
        resolved.append(
            ResolvedAlbum(
                rank=candidate.get("rank"),
                artist_query=artist_query,
                title_query=title_query,
                resolution_method=lookup.method,
                master_id=row["master_id"],
                release_id=row["release_id"],
                title=row["title"],
                artist_id=row["artist_id"],
                artist_name=artist_name,
                year=_year_from_released(row.get("released")) or candidate.get("year"),
                extraction_confidence=candidate.get("confidence", "low"),
                warnings=warnings,
            )
        )

    return resolved, unresolved


def build_resolved_cohort(
    graph: CreditGraph,
    extracted: dict[str, Any],
    *,
    dataset_snapshot_date: str,
    max_workers: int = 1,
) -> dict[str, Any]:
    resolved, unresolved = resolve_candidates(
        graph, extracted.get("candidates", []), max_workers=max_workers
    )
    return {
        "schema_version": RESOLVED_SCHEMA_VERSION,
        "source": extracted.get("source", {}),
        "resolver_version": RESOLVER_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset_snapshot_date": dataset_snapshot_date,
        "resolved": [album.to_dict() for album in resolved],
        "unresolved": unresolved,
    }


def write_resolved_cohort(artifact: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")


def validate_resolved_cohort(artifact: dict[str, Any]) -> None:
    failures: list[str] = []

    if set(artifact.keys()) != _TOP_LEVEL_KEYS:
        failures.append(f"unexpected top-level keys: {sorted(artifact.keys())}")
    if artifact.get("schema_version") != RESOLVED_SCHEMA_VERSION:
        failures.append(f"schema_version must be {RESOLVED_SCHEMA_VERSION}")

    seen_artist_ids: set[int] = set()
    for entry in artifact.get("resolved", []):
        if set(entry.keys()) != _RESOLVED_KEYS:
            failures.append(f"resolved entry has unexpected keys: {sorted(entry.keys())}")
            continue
        if entry.get("resolution_method") not in _RESOLUTION_METHODS:
            failures.append(f"invalid resolution_method: {entry.get('resolution_method')!r}")
        artist_id = entry.get("artist_id")
        if artist_id in seen_artist_ids:
            failures.append(f"artist_id {artist_id} appears more than once in resolved[]")
        seen_artist_ids.add(artist_id)

    if failures:
        raise CohortResolveError("; ".join(failures))

    serialized = json.dumps(artifact)
    for forbidden in _FORBIDDEN_SUBSTRINGS:
        if forbidden in serialized:
            raise CohortResolveError(f"artifact contains forbidden substring: {forbidden!r}")
