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

Performance note (see docs/decisions/0030-cohort-scoped-connectivity-substrate.md):
`score_pairs` does not call `CreditGraph.find_path` per pair. A real smoke
test found that hung indefinitely once a cohort touched a real, legitimately
prolific hub artist (thousands of co-credits) -- `find_path` has no caching
across the O(pairs) BFS calls a cohort needs, so a hub's expensive fan-out
query was repeated for every pair that happened to route through it. Instead,
`score_pairs` runs one BFS per *unique cohort artist* (not per pair), sharing
a single memoized `CreditGraph.neighbors()` cache across all of them, so a
hub touched from multiple directions is queried at most once. `find_path`
remains graph-core's public single-pair API and this module's tests assert
the two produce identical results on small synthetic graphs -- it's kept as
the reference implementation, not deleted.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import duckdb

from .graph import CreditGraph, EvidencePath

CONNECTIVITY_SCHEMA_VERSION = 1
# Bumped for the "skipped" status/skip_reason field added alongside the
# cohort-scoped BFS substrate -- see docs/decisions/0030-cohort-scoped-connectivity-substrate.md.
SCORER_VERSION = 2

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
        "skip_reason",
    }
)
_HOP_KEYS = frozenset({"release_id", "artist_a_id", "artist_b_id", "quality_flags"})
_STATUSES = frozenset({"found", "no_path", "skipped"})
# "skipped" means the absence of a path could not be confirmed -- never
# reported as "no_path", which is reserved for a search that completed
# without any capping or timeout and genuinely found nothing.
_SKIP_REASONS = frozenset({"seed_expansion_timeout", "frontier_too_large"})
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


def _run_with_timeout[T](
    interrupt: Callable[[], None], fn: Callable[[], T], *, timeout_seconds: float | None
) -> T:
    """Runs fn(), cancelling the graph's in-flight DuckDB query via
    `interrupt` (its own supported cancellation primitive -- confirmed by a
    real test to raise `duckdb.InterruptException` and leave the connection
    usable afterward) if fn() hasn't returned within timeout_seconds. Only
    ever raises `TimeoutError` when the interrupt actually fired, so a
    genuine, unrelated `duckdb.Error` is never misreported as a timeout."""
    if timeout_seconds is None:
        return fn()

    fired = threading.Event()

    def _fire() -> None:
        fired.set()
        interrupt()

    timer = threading.Timer(timeout_seconds, _fire)
    timer.start()
    try:
        return fn()
    except duckdb.Error:
        if fired.is_set():
            raise TimeoutError(f"exceeded {timeout_seconds}s and was interrupted") from None
        raise
    finally:
        timer.cancel()


class _NeighborCacheLike(Protocol):
    """Structural type satisfied by both a plain dict (sequential path,
    existing tests) and `_NeighborCache` (concurrent path) -- `_bfs_from_seed`
    only ever needs these three operations."""

    def __contains__(self, key: int) -> bool: ...
    def __getitem__(self, key: int) -> dict[int, tuple[int, ...]]: ...
    def __setitem__(self, key: int, value: dict[int, tuple[int, ...]]) -> None: ...


class _NeighborCache:
    """Thread-safe wrapper around the shared `neighbor_cache` dict, with the
    same `in`/`[]`/`[]=` interface `_bfs_from_seed` already uses (so it needs
    no changes). The lock only ever guards a dict read/write, never the
    `CreditGraph.neighbors()` call itself -- two workers racing on the same
    uncached artist may both query it once, which is wasted work, never a
    correctness problem, since `neighbors()` is a pure read."""

    def __init__(self) -> None:
        self._data: dict[int, dict[int, tuple[int, ...]]] = {}
        self._lock = threading.Lock()

    def __contains__(self, key: int) -> bool:
        with self._lock:
            return key in self._data

    def __getitem__(self, key: int) -> dict[int, tuple[int, ...]]:
        with self._lock:
            return self._data[key]

    def __setitem__(self, key: int, value: dict[int, tuple[int, ...]]) -> None:
        with self._lock:
            self._data[key] = value


def _bfs_from_seed(
    graph: CreditGraph,
    seed_artist_id: int,
    *,
    max_hops: int,
    max_frontier_expansion: int | None,
    neighbor_cache: _NeighborCacheLike,
    deadline: float | None,
) -> tuple[dict[int, tuple[int, int]], frozenset[int]]:
    """BFS from seed_artist_id out to max_hops, returning parent pointers
    {artist_id: (parent_artist_id, release_id)} for every artist reached,
    plus the set of artists excluded from expansion for exceeding
    `max_frontier_expansion` (see `CreditGraph.credit_row_count`) -- a
    non-empty set means an unreached target's absence here is inconclusive,
    not a confirmed no-path.

    `neighbor_cache` is shared across every seed artist in one
    `score_pairs` run: a hub reached from more than one seed's frontier is
    queried via `CreditGraph.neighbors_batch()` at most once, which is the
    actual fix for the confirmed cost of repeating a hub's expensive fan-out
    query once per pair that happens to route through it.

    Both the frontier-size check and the neighbor fetch are batched into one
    query per hop for the *whole* frontier (`CreditGraph.credit_row_counts`/
    `neighbors_batch`), not one query per frontier artist -- a hub's own
    hop-1 frontier can be thousands of artists, and checking each
    individually (the original shape here, still how `CreditGraph.find_path`
    -- a different, older BFS -- happened NOT to need fixing, since it
    already batched its own frontier check) was the dominant real cost a
    real hub-heavy cohort hit: even after the credits data materialization
    fix, one seed's own hop-2 expansion could still run well past a
    120-second budget purely from thousands of sequential round-trips.

    Raises TimeoutError (cooperatively, checked once per hop -- each hop is
    now one batched query, not a per-artist loop, so per-artist checking is
    no longer meaningful) if `deadline` (a `time.monotonic()` value) passes
    before the search completes. A single hop's own query running long is
    still caught by the caller's `_run_with_timeout`/`graph.interrupt()`,
    independent of this cooperative check.
    """
    visited = {seed_artist_id}
    parent: dict[int, tuple[int, int]] = {}
    capped_artist_ids: set[int] = set()
    frontier = [seed_artist_id]
    for _ in range(max_hops):
        if deadline is not None and time.monotonic() > deadline:
            raise TimeoutError(f"seed {seed_artist_id} expansion exceeded its deadline")

        if max_frontier_expansion is not None:
            counts = graph.credit_row_counts(frontier)
            safe_frontier = [a for a in frontier if counts.get(a, 0) <= max_frontier_expansion]
            capped_artist_ids.update(a for a in frontier if a not in safe_frontier)
        else:
            safe_frontier = frontier

        uncached = [a for a in safe_frontier if a not in neighbor_cache]
        if uncached:
            for artist_id, neighbors in graph.neighbors_batch(uncached).items():
                neighbor_cache[artist_id] = neighbors

        next_frontier: list[int] = []
        for artist_id in safe_frontier:
            for neighbor_id, release_ids in neighbor_cache[artist_id].items():
                if neighbor_id in visited:
                    continue
                visited.add(neighbor_id)
                parent[neighbor_id] = (artist_id, release_ids[0])
                next_frontier.append(neighbor_id)
        frontier = next_frontier
        if not frontier:
            break
    return parent, frozenset(capped_artist_ids)


def _reverse_evidence_path(path: EvidencePath) -> EvidencePath:
    return EvidencePath(
        from_artist_id=path.to_artist_id,
        to_artist_id=path.from_artist_id,
        hops=tuple(reversed(path.hops)),
    )


def _pair_path(
    artist_a_id: int,
    artist_b_id: int,
    *,
    parent_by_seed: dict[int, dict[int, tuple[int, int]]],
    capped_by_seed: dict[int, frozenset[int]],
    failed_seeds: dict[int, str],
) -> tuple[EvidencePath | None, str | None]:
    """Returns (path, skip_reason): skip_reason is None only when the
    result -- a real path, or a confirmed absence of one -- can be trusted.
    Tries both directions' BFS before giving up, since either seed's search
    can answer this pair; a pair is only reported "skipped" if the side(s)
    needed to answer it were never confirmed clean."""
    if artist_a_id in parent_by_seed and artist_b_id in parent_by_seed[artist_a_id]:
        parent = parent_by_seed[artist_a_id]
        return CreditGraph._reconstruct_path(artist_a_id, artist_b_id, parent), None
    if artist_b_id in parent_by_seed and artist_a_id in parent_by_seed[artist_b_id]:
        parent = parent_by_seed[artist_b_id]
        reverse = CreditGraph._reconstruct_path(artist_b_id, artist_a_id, parent)
        return _reverse_evidence_path(reverse), None

    a_confirmed = artist_a_id in parent_by_seed and not capped_by_seed.get(artist_a_id)
    b_confirmed = artist_b_id in parent_by_seed and not capped_by_seed.get(artist_b_id)
    if a_confirmed and b_confirmed:
        return None, None  # both sides searched cleanly and found nothing -- a real no_path

    reason = failed_seeds.get(artist_a_id) or failed_seeds.get(artist_b_id) or "frontier_too_large"
    return None, reason


_SeedResult = tuple[int, dict[int, tuple[int, int]] | None, frozenset[int], str | None]


def _score_one_seed(
    worker_graph: CreditGraph,
    artist_id: int,
    *,
    max_hops: int,
    max_frontier_expansion: int | None,
    neighbor_cache: _NeighborCacheLike,
    pair_timeout_seconds: float | None,
) -> _SeedResult:
    """Runs one seed's bounded BFS on `worker_graph` (its own cursor when
    called concurrently, or the shared connection in the sequential path)
    and returns a plain result tuple rather than mutating shared state --
    callers merge results themselves, so nothing here needs a lock beyond
    `neighbor_cache` itself."""
    deadline = time.monotonic() + pair_timeout_seconds if pair_timeout_seconds else None

    def _do_bfs() -> tuple[dict[int, tuple[int, int]], frozenset[int]]:
        return _bfs_from_seed(
            worker_graph,
            artist_id,
            max_hops=max_hops,
            max_frontier_expansion=max_frontier_expansion,
            neighbor_cache=neighbor_cache,
            deadline=deadline,
        )

    try:
        parent, capped = _run_with_timeout(
            worker_graph.interrupt, _do_bfs, timeout_seconds=pair_timeout_seconds
        )
    except TimeoutError:
        return artist_id, None, frozenset(), "seed_expansion_timeout"
    return artist_id, parent, capped, None


def seed_results_from_job_output(raw: dict[str, dict[str, Any]]) -> dict[int, _SeedResult]:
    """Converts a fleet-dispatched job's JSON-safe per-seed output --
    `infra/ansible/files/cohort_seed_bfs_job.py`'s own return shape, or
    `scripts/enqueue_cohort_seed_bfs.py`'s merged `per_seed_results` -- into
    the plain `_SeedResult` tuples `score_pairs`'s merge loop already
    expects. This is the one place a fleet-computed result and a
    locally-computed one become indistinguishable to the rest of this
    module -- see ADR 0032. JSON can't have int dict keys, so the job body
    encodes `parent` as a list of `[artist_id, parent_artist_id,
    release_id]` triples rather than a dict; this reverses that."""
    results: dict[int, _SeedResult] = {}
    for seed_key, entry in raw.items():
        artist_id = int(seed_key)
        if entry.get("status") == "timeout":
            results[artist_id] = (artist_id, None, frozenset(), "seed_expansion_timeout")
            continue
        parent = {int(a): (int(p), int(r)) for a, p, r in entry["parent"]}
        capped = frozenset(int(a) for a in entry["capped"])
        results[artist_id] = (artist_id, parent, capped, None)
    return results


def score_pairs(
    graph: CreditGraph,
    resolved_albums: list[dict[str, Any]],
    *,
    max_hops: int = 3,
    max_frontier_expansion: int | None = 300,
    pair_timeout_seconds: float | None = 30.0,
    max_workers: int = 1,
    precomputed_seed_results: dict[int, _SeedResult] | None = None,
) -> list[dict[str, Any]]:
    """Every unordered pair of resolved albums, sorted by album_id (mirrors
    challenge.py's `ordered = sorted(matched, key=lambda m: m.album_id)` +
    `i, i+1:` loop). Never drops a pair -- unreachable pairs get
    `status="no_path"`, and pairs whose reachability couldn't be confirmed
    within the guardrails get `status="skipped"` with a `skip_reason` --
    neither is silently omitted.

    Runs one BFS per unique cohort artist (not per pair) via `_bfs_from_seed`,
    sharing a single neighbor cache across all of them -- see this module's
    docstring for why `CreditGraph.find_path` is not called here directly.
    `max_frontier_expansion` is a release-count proxy threshold (see
    `CreditGraph.credit_row_count`) seeded from real hub fan-out observed
    against the production one-hop dataset, not a precise percentile --
    operators should tune it per cohort/dataset. `pair_timeout_seconds`
    bounds each seed's own BFS, not each pair.

    `max_workers > 1` dispatches each unique artist's own BFS concurrently,
    each on its own `graph.cursor()` (an independent DuckDB cursor sharing
    the same already-materialized tables) -- safe because each seed's search
    is otherwise independent, and `neighbor_cache` is the one piece of state
    genuinely shared across workers (see `_NeighborCache`). Results are
    merged into `parent_by_seed`/`capped_by_seed`/`failed_seeds` back on the
    calling thread as each seed finishes, so those dicts never need a lock.

    `precomputed_seed_results`, when given, skips local BFS computation
    entirely (both the sequential and `max_workers` paths) and uses these
    already-computed per-artist results instead -- the fleet-dispatch path
    (see `seed_results_from_job_output`, ADR 0032). `graph` is still used for
    everything downstream of this (hop quality classification via
    `credit_rows`), so a live connection to the same dataset is still
    required; only the expensive traversal itself is skipped. Every unique
    cohort artist must be present in `precomputed_seed_results` -- a fleet
    dispatch that dropped a seed is a bug in that dispatch, not something
    this function should silently paper over.
    """
    ordered = sorted(resolved_albums, key=_album_id)
    artist_ids = sorted({album["artist_id"] for album in ordered})

    neighbor_cache: _NeighborCacheLike = _NeighborCache() if max_workers > 1 else {}
    parent_by_seed: dict[int, dict[int, tuple[int, int]]] = {}
    capped_by_seed: dict[int, frozenset[int]] = {}
    failed_seeds: dict[int, str] = {}

    def _run(worker_graph: CreditGraph, artist_id: int) -> _SeedResult:
        return _score_one_seed(
            worker_graph,
            artist_id,
            max_hops=max_hops,
            max_frontier_expansion=max_frontier_expansion,
            neighbor_cache=neighbor_cache,
            pair_timeout_seconds=pair_timeout_seconds,
        )

    results: list[_SeedResult]
    if precomputed_seed_results is not None:
        missing = [aid for aid in artist_ids if aid not in precomputed_seed_results]
        if missing:
            raise CohortConnectivityError(
                f"precomputed_seed_results is missing artist_id(s) {missing} -- "
                "a fleet dispatch must cover every unique cohort artist"
            )
        results = [precomputed_seed_results[aid] for aid in artist_ids]
    elif max_workers > 1:
        # Cursors are created here, sequentially, on this thread -- never
        # inside a worker, since concurrent `graph.cursor()` calls on the
        # same source connection aren't a documented-safe DuckDB operation.
        # Each of the `max_workers` cursors is then owned by exactly one
        # pool thread for its entire chunk of artist_ids (one task per
        # worker, not one task per artist) -- a cursor is never touched by
        # more than one thread, which `ThreadPoolExecutor.map` alone
        # wouldn't guarantee if tasks outnumbered workers.
        worker_graphs = [graph.cursor() for _ in range(max_workers)]
        chunks: list[list[int]] = [[] for _ in range(max_workers)]
        for index, artist_id in enumerate(artist_ids):
            chunks[index % max_workers].append(artist_id)

        def _run_chunk(worker_index: int) -> list[_SeedResult]:
            return [_run(worker_graphs[worker_index], aid) for aid in chunks[worker_index]]

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            chunk_results = list(pool.map(_run_chunk, range(max_workers)))
        results = [result for chunk in chunk_results for result in chunk]
    else:
        results = [_run(graph, artist_id) for artist_id in artist_ids]

    for artist_id, parent, capped, failure in results:
        if failure is not None:
            failed_seeds[artist_id] = failure
            continue
        assert parent is not None
        parent_by_seed[artist_id] = parent
        capped_by_seed[artist_id] = capped

    pairs: list[dict[str, Any]] = []

    for i, album_a in enumerate(ordered):
        for album_b in ordered[i + 1 :]:
            artist_a_id = album_a["artist_id"]
            artist_b_id = album_b["artist_id"]
            # PR 2 already guarantees unique artist_id across resolved[] --
            # documented here as a relied-upon invariant, not trusted silently.
            assert artist_a_id != artist_b_id, "resolved albums must have distinct artist_id"

            path, skip_reason = _pair_path(
                artist_a_id,
                artist_b_id,
                parent_by_seed=parent_by_seed,
                capped_by_seed=capped_by_seed,
                failed_seeds=failed_seeds,
            )

            if skip_reason is not None:
                pairs.append(
                    {
                        "album_a_id": _album_id(album_a),
                        "album_b_id": _album_id(album_b),
                        "artist_a_id": artist_a_id,
                        "artist_b_id": artist_b_id,
                        "status": "skipped",
                        "hop_count": None,
                        "difficulty": None,
                        "hops": [],
                        "warnings": [],
                        "skip_reason": skip_reason,
                    }
                )
                continue

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
                        "skip_reason": None,
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
                    "skip_reason": None,
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
    max_frontier_expansion: int | None = 300,
    pair_timeout_seconds: float | None = 30.0,
    max_workers: int = 1,
    precomputed_seed_results: dict[int, _SeedResult] | None = None,
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

    pairs = score_pairs(
        graph,
        resolved_albums,
        max_hops=max_hops,
        max_frontier_expansion=max_frontier_expansion,
        pair_timeout_seconds=pair_timeout_seconds,
        max_workers=max_workers,
        precomputed_seed_results=precomputed_seed_results,
    )

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
            if pair.get("skip_reason") is not None:
                failures.append("no_path pair must have null skip_reason")
        elif pair["status"] == "skipped":
            if pair.get("difficulty") is not None or pair.get("hop_count") is not None:
                failures.append("skipped pair must have null hop_count/difficulty")
            if pair.get("skip_reason") not in _SKIP_REASONS:
                failures.append(f"invalid skip_reason: {pair.get('skip_reason')!r}")
        else:
            if pair.get("skip_reason") is not None:
                failures.append("found pair must have null skip_reason")
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
    skipped = [p for p in artifact["pairs"] if p["status"] == "skipped"]
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
        f"- Skipped (reachability not confirmed): {len(skipped)}",
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

    lines.append("## Skipped pairs")
    lines.append("")
    if skipped:
        for pair in skipped:
            lines.append(
                f"- {pair['album_a_id']} <-> {pair['album_b_id']}: reachability not "
                f"confirmed within the scoring guardrails ({pair['skip_reason']}) -- "
                "not a documented no-path, re-run with a larger guardrail to resolve"
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
