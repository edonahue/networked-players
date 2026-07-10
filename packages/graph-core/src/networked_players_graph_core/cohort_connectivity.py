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

Performance note, two generations deep:

1. ADR 0030: `score_pairs` stopped calling `CreditGraph.find_path` per pair
   (a hub's expensive fan-out query was repeated for every pair routing
   through it) and instead ran one Python-resident BFS per *unique cohort
   artist* with a shared memoized neighbor cache.
2. ADR 0033 (current): the Python-resident BFS itself was the next measured
   failure. On the real 47M-row one-hop dataset, ONE hub seed's hop-2
   neighbor payload is ~5.4M edges reaching 445k artists (~1-2GB of Python
   dicts), and the shared cache plus retained parent maps kept all of it for
   every seed -- a real scoring run swap-killed a 7.6GB host. `score_pairs`
   now scores through `_ReachScorer`: all search state lives in a DuckDB
   TEMP table, each hop is one INSERT..SELECT (so `memory_limit` +
   `temp_directory` spill genuinely bound the computation), each seed only
   expands to `ceil(max_hops/2)` hops, and pair distances are resolved
   bidirectionally where two seeds' reaches meet.

`find_path` remains graph-core's public single-pair API and this module's
tests assert the two produce identical results on small synthetic graphs.
`_bfs_from_seed` (the ADR 0030 implementation) is retained solely as the
reference the fleet-dispatch job body mirror is cross-checked against (ADR
0032) -- it is no longer on `score_pairs`'s local scoring path, and its
unbounded-cache design is why; do not re-adopt it for local scoring.
"""

from __future__ import annotations

import json
import math
import re
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import duckdb

from networked_players_contracts import CONNECTIVITY_SCHEMA_VERSION, connectivity_failures

from .graph import CreditGraph, EvidencePath, Hop

# 2: "skipped" status/skip_reason added alongside the cohort-scoped BFS
#    substrate (ADR 0030).
# 3: memory-bounded bidirectional reach scoring + recorded scoring_params
#    (ADR 0033) -- earlier artifacts recorded no parameters at all, which
#    made a crashed real run's settings unrecoverable.
SCORER_VERSION = 3

# Default per-seed bound on materialized reach rows: a seed exceeding it is
# reported skipped/reach_too_large rather than ground on. The worst real seed
# measured 445,161 rows at depth 2 (local memory profile, 2026-07-09); 2M
# leaves headroom for denser cohorts while still refusing runaway expansion.
DEFAULT_MAX_REACH_ROWS = 2_000_000

_STRENGTH_FLAGS = frozenset({"co_billed_release_artists", "performer_credit", "non_performer_only"})

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
    """Structural type for `_bfs_from_seed`'s memoized neighbor cache (a
    plain dict in every remaining caller -- the fleet-mirror cross-check test
    and this module's own reference tests). Retained with `_bfs_from_seed`
    itself; see the module docstring for why local scoring no longer uses
    either."""

    def __contains__(self, key: int) -> bool: ...
    def __getitem__(self, key: int) -> dict[int, tuple[int, ...]]: ...
    def __setitem__(self, key: int, value: dict[int, tuple[int, ...]]) -> None: ...


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


def expansion_depth(max_hops: int) -> int:
    """Per-seed reach depth for bidirectional scoring: each seed expands to
    ceil(max_hops/2) and a pair's distance is the minimum of dist_a + dist_b
    over artists both reaches contain. Halving the depth is what makes real
    cohorts tractable at all: hop 3 of the worst measured production seed
    would expand from a 445k-artist frontier -- effectively the whole graph.
    """
    return max(1, math.ceil(max_hops / 2))


def _rss_mb() -> float | None:
    """This process's resident set size, or None off-Linux. Diagnostics
    only -- never behavior."""
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return round(int(line.split()[1]) / 1024, 1)
    except OSError:
        return None
    return None


class _ReachTooLargeError(Exception):
    """A seed's materialized reach exceeded max_reach_rows. The seed's pairs
    are reported skipped/reach_too_large -- never silently truncated."""


class _ReachScorer:
    """DuckDB-resident bidirectional BFS over a whole cohort (ADR 0033).

    All search state lives in one TEMP table
    `(seed_id, artist_id, parent_id, release_id, dist)`; each hop is a single
    INSERT..SELECT, so DuckDB's `memory_limit` + `temp_directory` spill bound
    the entire computation and Python never materializes edge payloads. The
    frontier cap (`max_frontier_expansion`) never applies to the seed itself
    (dist 0): every real cohort seed measured is a hub by the release-count
    proxy (minimum 712 against the default cap of 300), so capping at dist 0
    means no cohort BFS can ever start. Because the cap no longer protects
    Python memory, it is purely a time knob here.

    A capped artist is still *reachable as a target* (ADR 0029/0030 wording)
    -- and bidirectionally that now includes pairs meeting AT a capped hub,
    since neither side needs to expand it to reach it. Only paths requiring
    travel *through* two consecutive capped artists stay unprovable.

    Uses `graph._connection` directly -- the same private-access precedent as
    this module's existing `CreditGraph._reconstruct_path` use: this class is
    the SQL half of the scoring path, which the public per-artist API can't
    express without hauling row payloads back into Python.
    """

    def __init__(
        self,
        graph: CreditGraph,
        *,
        max_hops: int,
        max_frontier_expansion: int | None,
        max_reach_rows: int,
    ):
        self._connection = graph._connection
        self._depth = expansion_depth(max_hops)
        self._cap = max_frontier_expansion
        self._max_reach_rows = max_reach_rows
        self._table = f"reach_{uuid.uuid4().hex}"
        self._connection.execute(
            f"CREATE TEMP TABLE {self._table} (seed_id BIGINT, artist_id BIGINT, "
            "parent_id BIGINT, release_id BIGINT, dist INTEGER)"
        )

    def close(self) -> None:
        self._connection.execute(f"DROP TABLE IF EXISTS {self._table}")

    def expand_seed(self, seed_artist_id: int, *, deadline: float | None) -> dict[str, Any]:
        """Populates this seed's reach rows out to the scorer's depth and
        returns per-seed stats for diagnostics. Raises TimeoutError
        (cooperatively, checked before each hop; an in-flight hop's own query
        is additionally interruptible via `CreditGraph.interrupt()`) or
        `_ReachTooLargeError` -- on either, the caller must `delete_seed()`
        so pair resolution never meets against a half-expanded reach."""
        self._connection.execute(
            f"INSERT INTO {self._table} VALUES (?, ?, NULL, NULL, 0)",
            [seed_artist_id, seed_artist_id],
        )
        reach_by_dist: dict[int, int] = {0: 1}
        capped_total = 0
        for dist in range(1, self._depth + 1):
            if deadline is not None and time.monotonic() > deadline:
                raise TimeoutError(f"seed {seed_artist_id} expansion exceeded its deadline")
            new_rows, capped = self._expand_hop(seed_artist_id, dist)
            reach_by_dist[dist] = new_rows
            capped_total += capped
            total = sum(reach_by_dist.values())
            if total > self._max_reach_rows:
                raise _ReachTooLargeError(
                    f"seed {seed_artist_id} reached {total} rows at dist {dist}, "
                    f"exceeding max_reach_rows={self._max_reach_rows}"
                )
            if new_rows == 0:
                break
        return {"reach_by_dist": reach_by_dist, "capped": capped_total}

    def _expand_hop(self, seed_artist_id: int, dist: int) -> tuple[int, int]:
        """One hop: everything reachable at `dist` from this seed's `dist - 1`
        frontier, excluding capped frontier artists' edges and
        already-reached artists. Parent/release choice is deterministic:
        min shared release per (parent, child), then min (release, parent)
        per child -- the same min-release rule `find_path`'s level query uses.
        """
        suffix = uuid.uuid4().hex
        frontier = f"reach_frontier_{suffix}"
        capped = f"reach_capped_{suffix}"
        connection = self._connection
        try:
            connection.execute(
                f"CREATE TEMP TABLE {frontier} AS SELECT artist_id FROM {self._table} "
                "WHERE seed_id = ? AND dist = ?",
                [seed_artist_id, dist - 1],
            )
            if dist == 1 or self._cap is None:
                # dist 1 expands the seed itself -- exempt from the cap, per
                # the class docstring.
                connection.execute(f"CREATE TEMP TABLE {capped} (artist_id BIGINT)")
            else:
                connection.execute(
                    f"CREATE TEMP TABLE {capped} AS SELECT artist_id FROM linked_credits "
                    f"WHERE artist_id IN (SELECT artist_id FROM {frontier}) "
                    f"GROUP BY artist_id HAVING count(*) > {int(self._cap)}"
                )
            connection.execute(
                f"INSERT INTO {self._table} "
                f"SELECT {int(seed_artist_id)}, artist_id, parent_id, release_id, {int(dist)} "
                "FROM ("
                "  SELECT b.artist_id AS artist_id, a.artist_id AS parent_id, "
                "         min(b.release_id) AS release_id, "
                "         row_number() OVER (PARTITION BY b.artist_id "
                "                            ORDER BY min(b.release_id), a.artist_id) AS rn "
                "  FROM linked_credits a "
                "  JOIN linked_credits b USING (release_id) "
                "  JOIN traversal_releases USING (release_id) "
                f"  JOIN {frontier} f ON f.artist_id = a.artist_id "
                "  WHERE b.artist_id != a.artist_id "
                f"    AND a.artist_id NOT IN (SELECT artist_id FROM {capped}) "
                f"    AND b.artist_id NOT IN (SELECT artist_id FROM {self._table} "
                f"                            WHERE seed_id = {int(seed_artist_id)}) "
                "  GROUP BY b.artist_id, a.artist_id "
                ") ranked WHERE rn = 1"
            )
            new_row = connection.execute(
                f"SELECT count(*) FROM {self._table} WHERE seed_id = ? AND dist = ?",
                [seed_artist_id, dist],
            ).fetchone()
            capped_row = connection.execute(f"SELECT count(*) FROM {capped}").fetchone()
            assert new_row is not None and capped_row is not None
            return int(new_row[0]), int(capped_row[0])
        finally:
            connection.execute(f"DROP TABLE IF EXISTS {frontier}")
            connection.execute(f"DROP TABLE IF EXISTS {capped}")

    def delete_seed(self, seed_artist_id: int) -> None:
        self._connection.execute(f"DELETE FROM {self._table} WHERE seed_id = ?", [seed_artist_id])

    def total_rows(self) -> int:
        row = self._connection.execute(f"SELECT count(*) FROM {self._table}").fetchone()
        assert row is not None
        return int(row[0])

    def pair_distances(self) -> dict[tuple[int, int], int]:
        """Every seed pair's minimum combined distance, from one self-join --
        the bidirectional meet. A pair with no shared reached artist is
        simply absent."""
        rows = self._connection.execute(
            f"SELECT r1.seed_id, r2.seed_id, min(r1.dist + r2.dist) "
            f"FROM {self._table} r1 JOIN {self._table} r2 USING (artist_id) "
            "WHERE r1.seed_id < r2.seed_id GROUP BY r1.seed_id, r2.seed_id"
        ).fetchall()
        return {(int(a), int(b)): int(d) for a, b, d in rows}

    def pair_path(self, from_artist_id: int, to_artist_id: int) -> EvidencePath:
        """The evidence path behind `pair_distances`'s minimum for this pair:
        pick the deterministic best meeting artist, then walk both sides'
        parent chains with point lookups. The minimal combined walk is always
        a simple path -- any repeated artist would itself be a meeting point
        with a strictly smaller combined distance, contradicting minimality.
        """
        row = self._connection.execute(
            f"SELECT r1.artist_id FROM {self._table} r1 "
            f"JOIN {self._table} r2 USING (artist_id) "
            "WHERE r1.seed_id = ? AND r2.seed_id = ? "
            "ORDER BY r1.dist + r2.dist, artist_id LIMIT 1",
            [from_artist_id, to_artist_id],
        ).fetchone()
        assert row is not None, "pair_path called for a pair with no meeting artist"
        meet = int(row[0])
        from_side = self._chain(from_artist_id, meet)
        to_side = self._chain(to_artist_id, meet)
        hops = from_side + [
            Hop(release_id=h.release_id, artist_a_id=h.artist_b_id, artist_b_id=h.artist_a_id)
            for h in reversed(to_side)
        ]
        return EvidencePath(
            from_artist_id=from_artist_id, to_artist_id=to_artist_id, hops=tuple(hops)
        )

    def _chain(self, seed_artist_id: int, artist_id: int) -> list[Hop]:
        """Hops from the seed out to `artist_id`, walking parent pointers."""
        hops: list[Hop] = []
        current = artist_id
        while True:
            row = self._connection.execute(
                f"SELECT parent_id, release_id, dist FROM {self._table} "
                "WHERE seed_id = ? AND artist_id = ?",
                [seed_artist_id, current],
            ).fetchone()
            assert row is not None, f"reach chain broken at artist {current}"
            parent_id, release_id, dist = row
            if int(dist) == 0:
                break
            hops.append(
                Hop(release_id=int(release_id), artist_a_id=int(parent_id), artist_b_id=current)
            )
            current = int(parent_id)
        hops.reverse()
        return hops


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


def _pair_record(
    graph: CreditGraph,
    album_a: dict[str, Any],
    album_b: dict[str, Any],
    path: EvidencePath | None,
    skip_reason: str | None,
) -> dict[str, Any]:
    """One pair's artifact record: skipped (reason given), no_path (no path,
    no reason -- a trusted absence), or found with per-hop evidence quality
    classified from the real credit rows."""
    base = {
        "album_a_id": _album_id(album_a),
        "album_b_id": _album_id(album_b),
        "artist_a_id": album_a["artist_id"],
        "artist_b_id": album_b["artist_id"],
    }
    if skip_reason is not None:
        return {
            **base,
            "status": "skipped",
            "hop_count": None,
            "difficulty": None,
            "hops": [],
            "warnings": [],
            "skip_reason": skip_reason,
        }
    if path is None:
        return {
            **base,
            "status": "no_path",
            "hop_count": None,
            "difficulty": None,
            "hops": [],
            "warnings": [],
            "skip_reason": None,
        }

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
    return {
        **base,
        "status": "found",
        "hop_count": len(hops),
        "difficulty": _difficulty_for_hop_count(len(hops)),
        "hops": hops,
        "warnings": _pair_warnings(hops),
        "skip_reason": None,
    }


def score_pairs(
    graph: CreditGraph,
    resolved_albums: list[dict[str, Any]],
    *,
    max_hops: int = 3,
    max_frontier_expansion: int | None = 300,
    pair_timeout_seconds: float | None = 30.0,
    max_workers: int = 1,
    precomputed_seed_results: dict[int, _SeedResult] | None = None,
    max_reach_rows: int = DEFAULT_MAX_REACH_ROWS,
    diagnostics: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Every unordered pair of resolved albums, sorted by album_id (mirrors
    challenge.py's `ordered = sorted(matched, key=lambda m: m.album_id)` +
    `i, i+1:` loop). Never drops a pair -- unreachable pairs get
    `status="no_path"`, and pairs whose reachability couldn't be confirmed
    within the guardrails get `status="skipped"` with a `skip_reason` --
    neither is silently omitted.

    Local scoring runs through `_ReachScorer` (see its docstring and ADR
    0033): each unique cohort artist expands to `expansion_depth(max_hops)`
    hops entirely inside DuckDB, and pair distances resolve where two seeds'
    reaches meet. `max_frontier_expansion` is a release-count proxy threshold
    (see `CreditGraph.credit_row_count`) that never applies to a seed itself;
    `pair_timeout_seconds` bounds each seed's own expansion, not each pair;
    `max_reach_rows` bounds each seed's materialized reach rows.

    `max_workers` is accepted for API compatibility but no longer fans local
    scoring out across cursors: with each hop running as a single DuckDB
    statement, intra-query parallelism (`CreditGraph.open(threads=...)`) is
    the effective lever, and the retained payloads that made Python-side
    fan-out attractive no longer exist.

    `precomputed_seed_results`, when given, skips local expansion entirely
    and reconstructs pairs from these already-computed per-artist results
    instead -- the fleet-dispatch path (see `seed_results_from_job_output`,
    ADR 0032), which still ships full-depth single-direction parent maps.
    `graph` is still used downstream for hop quality classification via
    `credit_rows`. Every unique cohort artist must be present -- a fleet
    dispatch that dropped a seed is a bug in that dispatch, not something
    this function should silently paper over.

    `diagnostics`, when given, is filled in place with local-only scoring
    telemetry (per-seed reach sizes and timings, RSS checkpoints) -- the
    CLI writes it as scoring-diagnostics.json next to connectivity.json.
    """
    del max_workers  # accepted for compatibility; see docstring
    ordered = sorted(resolved_albums, key=_album_id)
    artist_ids = sorted({album["artist_id"] for album in ordered})

    if precomputed_seed_results is not None:
        return _score_pairs_precomputed(graph, ordered, artist_ids, precomputed_seed_results)
    return _score_pairs_via_reach(
        graph,
        ordered,
        artist_ids,
        max_hops=max_hops,
        max_frontier_expansion=max_frontier_expansion,
        pair_timeout_seconds=pair_timeout_seconds,
        max_reach_rows=max_reach_rows,
        diagnostics=diagnostics,
    )


def _score_pairs_precomputed(
    graph: CreditGraph,
    ordered: list[dict[str, Any]],
    artist_ids: list[int],
    precomputed_seed_results: dict[int, _SeedResult],
) -> list[dict[str, Any]]:
    """Pair reconstruction from fleet-computed parent maps -- ADR 0032's
    dispatch path, deliberately unchanged by the local reach redesign (ADR
    0033): the job body and its cross-check test stay stable until the
    fleet unit itself is redesigned."""
    missing = [aid for aid in artist_ids if aid not in precomputed_seed_results]
    if missing:
        raise CohortConnectivityError(
            f"precomputed_seed_results is missing artist_id(s) {missing} -- "
            "a fleet dispatch must cover every unique cohort artist"
        )

    parent_by_seed: dict[int, dict[int, tuple[int, int]]] = {}
    capped_by_seed: dict[int, frozenset[int]] = {}
    failed_seeds: dict[int, str] = {}
    for artist_id in artist_ids:
        _, parent, capped, failure = precomputed_seed_results[artist_id]
        if failure is not None:
            failed_seeds[artist_id] = failure
            continue
        assert parent is not None
        parent_by_seed[artist_id] = parent
        capped_by_seed[artist_id] = capped

    pairs: list[dict[str, Any]] = []
    for i, album_a in enumerate(ordered):
        for album_b in ordered[i + 1 :]:
            # PR 2 already guarantees unique artist_id across resolved[] --
            # documented here as a relied-upon invariant, not trusted silently.
            assert album_a["artist_id"] != album_b["artist_id"], (
                "resolved albums must have distinct artist_id"
            )
            path, skip_reason = _pair_path(
                album_a["artist_id"],
                album_b["artist_id"],
                parent_by_seed=parent_by_seed,
                capped_by_seed=capped_by_seed,
                failed_seeds=failed_seeds,
            )
            pairs.append(_pair_record(graph, album_a, album_b, path, skip_reason))
    return pairs


def _score_pairs_via_reach(
    graph: CreditGraph,
    ordered: list[dict[str, Any]],
    artist_ids: list[int],
    *,
    max_hops: int,
    max_frontier_expansion: int | None,
    pair_timeout_seconds: float | None,
    max_reach_rows: int,
    diagnostics: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """The local scoring path (ADR 0033): expand every seed's reach in
    DuckDB, resolve all pair distances with one bidirectional meet query,
    then reconstruct evidence paths for found pairs via point lookups.

    Honesty rules, matching `_pair_path`'s single-direction originals: a
    found path is always trustworthy evidence regardless of capping
    elsewhere; `no_path` is only reported when both sides expanded completely
    (no failure, nothing capped) -- any other unmet pair is `skipped` with
    the most specific reason available."""
    wall_start = time.monotonic()
    rss_start = _rss_mb()
    scorer = _ReachScorer(
        graph,
        max_hops=max_hops,
        max_frontier_expansion=max_frontier_expansion,
        max_reach_rows=max_reach_rows,
    )
    failed_seeds: dict[int, str] = {}
    capped_any: dict[int, bool] = {}
    seed_entries: list[dict[str, Any]] = []
    try:
        seed_degrees = graph.credit_row_counts(artist_ids)
        for seed in artist_ids:
            deadline = time.monotonic() + pair_timeout_seconds if pair_timeout_seconds else None
            seed_start = time.monotonic()
            stats: dict[str, Any] = {"reach_by_dist": {}, "capped": 0}

            def _expand(seed: int = seed, deadline: float | None = deadline) -> dict[str, Any]:
                return scorer.expand_seed(seed, deadline=deadline)

            try:
                stats = _run_with_timeout(
                    graph.interrupt, _expand, timeout_seconds=pair_timeout_seconds
                )
            except TimeoutError:
                scorer.delete_seed(seed)
                failed_seeds[seed] = "seed_expansion_timeout"
            except _ReachTooLargeError:
                scorer.delete_seed(seed)
                failed_seeds[seed] = "reach_too_large"
            else:
                capped_any[seed] = stats["capped"] > 0
            seed_entries.append(
                {
                    "artist_id": seed,
                    "status": failed_seeds.get(seed, "ok"),
                    "seed_degree": seed_degrees.get(seed, 0),
                    "capped_count": stats["capped"],
                    "reach_rows_by_dist": {
                        str(dist): count for dist, count in stats["reach_by_dist"].items()
                    },
                    "elapsed_s": round(time.monotonic() - seed_start, 2),
                }
            )

        rss_after_expansion = _rss_mb()
        distance_start = time.monotonic()
        distances = scorer.pair_distances()
        distance_query_s = round(time.monotonic() - distance_start, 2)
        reach_total_rows = scorer.total_rows()

        pairs: list[dict[str, Any]] = []
        for i, album_a in enumerate(ordered):
            for album_b in ordered[i + 1 :]:
                artist_a_id = album_a["artist_id"]
                artist_b_id = album_b["artist_id"]
                # PR 2 already guarantees unique artist_id across resolved[]
                # -- documented as a relied-upon invariant, not trusted
                # silently.
                assert artist_a_id != artist_b_id, "resolved albums must have distinct artist_id"

                key = (min(artist_a_id, artist_b_id), max(artist_a_id, artist_b_id))
                distance = distances.get(key)
                if distance is not None and distance <= max_hops:
                    path = scorer.pair_path(artist_a_id, artist_b_id)
                    assert len(path.hops) == distance
                    record = _pair_record(graph, album_a, album_b, path, None)
                elif artist_a_id in failed_seeds or artist_b_id in failed_seeds:
                    reason = failed_seeds.get(artist_a_id) or failed_seeds.get(artist_b_id)
                    record = _pair_record(graph, album_a, album_b, None, reason)
                elif capped_any.get(artist_a_id) or capped_any.get(artist_b_id):
                    record = _pair_record(graph, album_a, album_b, None, "frontier_too_large")
                else:
                    record = _pair_record(graph, album_a, album_b, None, None)
                pairs.append(record)
    finally:
        scorer.close()

    if diagnostics is not None:
        diagnostics.update(
            {
                "diagnostics_version": 1,
                "strategy": "bidirectional_reach",
                "generated_at": datetime.now(UTC).isoformat(),
                "expansion_depth": expansion_depth(max_hops),
                "seed_count": len(artist_ids),
                "seeds": seed_entries,
                "reach_total_rows": reach_total_rows,
                "pair_distance_query_s": distance_query_s,
                "rss_mb": {
                    "start": rss_start,
                    "after_expansion": rss_after_expansion,
                    "end": _rss_mb(),
                },
                "wall_s": round(time.monotonic() - wall_start, 2),
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
    max_reach_rows: int = DEFAULT_MAX_REACH_ROWS,
    duckdb_settings: dict[str, Any] | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """`duckdb_settings` (e.g. {"memory_limit": "1GB", "threads": 2}) is
    recorded verbatim into the artifact's scoring_params so a run's settings
    are never unrecoverable again -- it must not contain filesystem paths
    (validate_connectivity's forbidden-substring check will reject them;
    pass the *fact* of a custom temp dir, never its location)."""
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
        max_reach_rows=max_reach_rows,
        diagnostics=diagnostics,
    )

    local_scoring = precomputed_seed_results is None
    scoring_params: dict[str, Any] = {
        "strategy": "bidirectional_reach" if local_scoring else "precomputed_seed_results",
        "max_hops": max_hops,
        "expansion_depth": expansion_depth(max_hops) if local_scoring else None,
        "max_frontier_expansion": max_frontier_expansion,
        "pair_timeout_seconds": pair_timeout_seconds,
        "max_reach_rows": max_reach_rows,
        "max_workers": max_workers,
        **(duckdb_settings or {}),
    }

    return {
        "schema_version": CONNECTIVITY_SCHEMA_VERSION,
        "source": resolved.get("source", {}),
        "scorer_version": SCORER_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset_snapshot_date": dataset_snapshot_date,
        "max_hops": max_hops,
        "scoring_params": scoring_params,
        "pairs": pairs,
        "unresolved": resolved.get("unresolved", []),
    }


def write_connectivity_cohort(artifact: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")


def validate_connectivity(artifact: dict[str, Any]) -> None:
    failures = connectivity_failures(artifact)
    if failures:
        raise CohortConnectivityError("; ".join(failures))


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
        *(
            [
                "- Scoring params: "
                + ", ".join(f"{k}={v}" for k, v in sorted(artifact["scoring_params"].items()))
            ]
            if artifact.get("scoring_params")
            else []
        ),
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
