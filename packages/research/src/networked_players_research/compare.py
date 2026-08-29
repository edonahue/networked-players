"""Album comparison (Phase 7 PR D, Slice 1 -- the private research
workbench's first comparison type). See docs plan section 11: a local-only
comparison layer over already-existing primitives, not a new graph engine.

Every graph traversal here goes through `CreditGraph` (`.find_path`,
`.neighbors_batch`, `.degrees`, `.credit_rows_for_releases`, `.release`) --
this module never re-derives BFS or edge SQL itself. Scope-tier comparison
reuses `scope_tier.measure_scope_tiers` directly. Role-category composition
reuses `role_taxonomy.classify_role`, the same taxonomy every other
role-aware feature in the repo uses.

Compare-artists, compare-scenes, and the workbench server/UI are explicit
follow-up slices -- not built here. Caveat-flag comparison is deliberately
deferred too: the public site's caveat signal lives in the evidence-release-
registry build path, which a private corpus snapshot doesn't carry the same
way -- reusing it correctly needs its own investigation, not a guess bolted
on here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from networked_players_graph_core.graph import (
    CreditGraph,
    EvidencePath,
    FrontierTooLargeError,
)
from networked_players_graph_core.role_taxonomy import RoleCategory, classify_role

from .report import _scan_for_forbidden_phrases
from .scope_tier import ScopeTierError, measure_scope_tiers

DEFAULT_MAX_HOPS = 4
DEFAULT_MAX_ROUTE_CANDIDATE_PAIRS = 200


class _RouteSearchGraph(Protocol):
    """Structural type for `_route_between`'s dependency -- the minimal
    slice of `CreditGraph` it actually calls, so a test double can stand in
    for `CreditGraph` without needing a real corpus/connection to exercise
    the pair-budget/frontier-capped logic deterministically."""

    def degrees(self, artist_ids: list[int]) -> dict[int, int]: ...
    def find_path(
        self, from_artist_id: int, to_artist_id: int, *, max_hops: int
    ) -> EvidencePath | None: ...


class CompareError(RuntimeError):
    """Raised when a comparison can't be run at all (a release id doesn't
    resolve, etc.) -- distinct from a *result* that reports "not applicable"
    or "no path found," both of which are valid, informative outcomes."""


@dataclass(frozen=True)
class CompareAlbumsRequest:
    corpus_snapshot_root: Path
    album_a_release_id: int
    album_b_release_id: int
    max_hops: int = DEFAULT_MAX_HOPS
    max_route_candidate_pairs: int = DEFAULT_MAX_ROUTE_CANDIDATE_PAIRS


def _credited_artist_ids(credit_rows: list[dict[str, Any]]) -> list[int]:
    """Distinct, non-null credited artist ids from a release's credit rows,
    in a stable (sorted) order. `credit_rows_for_releases` already restricts
    to playable, non-placeholder, linked credits."""
    return sorted({int(row["artist_id"]) for row in credit_rows if row["artist_id"] is not None})


def _role_category_counts(credit_rows: list[dict[str, Any]]) -> dict[str, int]:
    """Counts DISTINCT (artist_id, category) pairs, not credit rows -- an
    artist credited on every track with the same role must not out-weigh a
    real distinct performer just because they appear on more rows."""
    pairs: set[tuple[int, RoleCategory]] = set()
    for row in credit_rows:
        artist_id = row["artist_id"]
        if artist_id is None:
            continue
        for category in classify_role(row["role_text"]):
            pairs.add((int(artist_id), category))
    counts: dict[str, int] = {}
    for _artist_id, category in pairs:
        counts[category.value] = counts.get(category.value, 0) + 1
    return counts


def _sorted_role_texts(rows: list[dict[str, Any]]) -> list[str | None]:
    """A release_artist-scope credit can legitimately carry no role_text
    (`None`) while another row for the SAME artist on the SAME release does
    (e.g. a track_artist row) -- real Discogs data, not a synthetic-fixture
    edge case (found running this against the real Jamiroquai topic corpus).
    `sorted()` on a plain set of `str | None` raises `TypeError` the moment
    both are present; sorting on `(is_none, value)` keeps `None` last
    without needing to silently drop it."""
    return sorted({row["role_text"] for row in rows}, key=lambda text: (text is None, text))


def _shared_and_unique(
    credits_a: list[dict[str, Any]], credits_b: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[int], list[int]]:
    ids_a = set(_credited_artist_ids(credits_a))
    ids_b = set(_credited_artist_ids(credits_b))
    shared_ids = sorted(ids_a & ids_b)
    unique_to_a = sorted(ids_a - ids_b)
    unique_to_b = sorted(ids_b - ids_a)

    rows_by_artist_a: dict[int, list[dict[str, Any]]] = {}
    for row in credits_a:
        if row["artist_id"] is not None:
            rows_by_artist_a.setdefault(int(row["artist_id"]), []).append(row)
    rows_by_artist_b: dict[int, list[dict[str, Any]]] = {}
    for row in credits_b:
        if row["artist_id"] is not None:
            rows_by_artist_b.setdefault(int(row["artist_id"]), []).append(row)

    recurring_personnel = [
        {
            "artist_id": artist_id,
            "name": rows_by_artist_a[artist_id][0]["name"],
            "album_a_credit_count": len(rows_by_artist_a[artist_id]),
            "album_a_roles": _sorted_role_texts(rows_by_artist_a[artist_id]),
            "album_b_credit_count": len(rows_by_artist_b[artist_id]),
            "album_b_roles": _sorted_role_texts(rows_by_artist_b[artist_id]),
        }
        for artist_id in shared_ids
    ]
    return recurring_personnel, unique_to_a, unique_to_b


def _primary_artist_id(credit_rows: list[dict[str, Any]]) -> int | None:
    """The release's sole `release_artist`-scope credited artist, or `None`
    if there isn't exactly one (a various-artists compilation, or none at
    all) -- callers report "not applicable" rather than guessing which one
    is "the" artist."""
    release_artist_ids = {
        int(row["artist_id"])
        for row in credit_rows
        if row["credit_scope"] == "release_artist" and row["artist_id"] is not None
    }
    if len(release_artist_ids) != 1:
        return None
    return next(iter(release_artist_ids))


def _route_between(
    graph: _RouteSearchGraph,
    candidates_a: list[int],
    candidates_b: list[int],
    *,
    max_hops: int,
    max_route_candidate_pairs: int,
) -> dict[str, Any]:
    """Tries `CreditGraph.find_path` across (artist from A, artist from B)
    pairs, cheapest (lowest-degree, most-specific) artists first on each
    side -- avoids high-degree hub artists dominating every result the way
    ADR 0029 already found they do elsewhere. Stops at the first hit, or
    after `max_route_candidate_pairs` pairs tried, whichever comes first.

    This orders candidates to avoid hub domination, not to find the
    globally shortest path across every possible pair -- the first pair
    that finds ANY path within `max_hops` wins, even if a later, higher-
    degree pair would have found a shorter one. Each individual `find_path`
    call is still exact BFS (shortest path for THAT pair); only the choice
    of which pair to search first is a heuristic.

    Three, and only three, outcomes:
    - "found": a real route was found -- pair and hops are the evidence.
    - "no_path_within_bound": every candidate pair was tried (the budget was
      never exhausted) and none found a path.
    - "search_bounded": either the pair budget ran out before every
      candidate was tried, or some pair's search itself was frontier-capped
      (`FrontierTooLargeError`) -- inconclusive, never reported as a
      confirmed no-path.
    """
    if max_route_candidate_pairs <= 0:
        return {"case": "search_bounded", "pairs_tried": 0}

    degrees_a = graph.degrees(candidates_a)
    degrees_b = graph.degrees(candidates_b)
    ordered_a = sorted(candidates_a, key=lambda a: degrees_a.get(a, 0))
    ordered_b = sorted(candidates_b, key=lambda b: degrees_b.get(b, 0))

    pairs_tried = 0
    was_capped = False
    for artist_a in ordered_a:
        for artist_b in ordered_b:
            if artist_a == artist_b:
                continue
            if pairs_tried >= max_route_candidate_pairs:
                return {"case": "search_bounded", "pairs_tried": pairs_tried}
            pairs_tried += 1
            try:
                result = graph.find_path(artist_a, artist_b, max_hops=max_hops)
            except FrontierTooLargeError:
                was_capped = True
                continue
            if result is not None:
                return {
                    "case": "found",
                    "pairs_tried": pairs_tried,
                    "from_artist_id": artist_a,
                    "to_artist_id": artist_b,
                    "hops": [
                        {
                            "release_id": hop.release_id,
                            "artist_a_id": hop.artist_a_id,
                            "artist_b_id": hop.artist_b_id,
                        }
                        for hop in result.hops
                    ],
                }

    if was_capped:
        return {"case": "search_bounded", "pairs_tried": pairs_tried}
    return {"case": "no_path_within_bound", "pairs_tried": pairs_tried}


def _network_overlap(
    graph: CreditGraph, roster_a: list[int], roster_b: list[int]
) -> dict[str, Any]:
    """Third-party artists (excluding each album's own credited roster) who
    are a documented 1-hop neighbor of BOTH albums' rosters -- distinct from
    "shared contributors" (already reported separately), this surfaces
    people connected to both albums without being credited on either."""
    own_rosters = set(roster_a) | set(roster_b)
    neighbors = graph.neighbors_batch(roster_a + roster_b)

    def neighborhood(roster: list[int]) -> set[int]:
        result: set[int] = set()
        for artist_id in roster:
            result.update(neighbors.get(artist_id, {}).keys())
        return result - own_rosters

    overlap = sorted(neighborhood(roster_a) & neighborhood(roster_b))
    return {"count": len(overlap), "artist_ids": overlap}


def _not_applicable(reason: str) -> dict[str, Any]:
    # The only free/generated text this module produces (every other field
    # is structured data or verbatim source content) -- scanned here, at its
    # one point of origin, per ADR 0054's fact-vs-interpretation discipline.
    _scan_for_forbidden_phrases(reason)
    return {"case": "not_applicable", "reason": reason}


def _scope_tier_comparison(
    corpus_snapshot_root: Path, primary_a: int | None, primary_b: int | None
) -> dict[str, Any]:
    if primary_a is None or primary_b is None:
        missing = []
        if primary_a is None:
            missing.append("album_a")
        if primary_b is None:
            missing.append("album_b")
        return _not_applicable(
            f"{' and '.join(missing)} do not resolve to exactly one "
            "release_artist-scope credited artist"
        )
    try:
        return {
            "case": "compared",
            "album_a": measure_scope_tiers(corpus_snapshot_root, primary_a),
            "album_b": measure_scope_tiers(corpus_snapshot_root, primary_b),
        }
    except ScopeTierError as exc:
        return _not_applicable(str(exc))


def compare_albums(graph: CreditGraph, request: CompareAlbumsRequest) -> dict[str, Any]:
    """Compares two releases already resolvable in the corpus `graph` was
    opened over. Raises `CompareError` if either release id doesn't resolve
    at all; every other outcome (no shared contributors, no route within
    bound, scope tiers not applicable) is a valid, explicitly-labeled result,
    never an exception."""
    release_a = graph.release(request.album_a_release_id)
    release_b = graph.release(request.album_b_release_id)
    if release_a is None:
        raise CompareError(f"release_id {request.album_a_release_id} not found in corpus")
    if release_b is None:
        raise CompareError(f"release_id {request.album_b_release_id} not found in corpus")

    credits_by_release = graph.credit_rows_for_releases(
        [request.album_a_release_id, request.album_b_release_id]
    )
    credits_a = credits_by_release.get(request.album_a_release_id, [])
    credits_b = credits_by_release.get(request.album_b_release_id, [])

    recurring_personnel, unique_to_a, unique_to_b = _shared_and_unique(credits_a, credits_b)

    roster_a = _credited_artist_ids(credits_a)
    roster_b = _credited_artist_ids(credits_b)

    if recurring_personnel:
        shared_artist_ids = [entry["artist_id"] for entry in recurring_personnel]
        direct_route: dict[str, Any] = {"connected": True, "shared_artist_ids": shared_artist_ids}
        indirect_route: dict[str, Any] | None = None
    else:
        direct_route = {"connected": False}
        indirect_route = _route_between(
            graph,
            roster_a,
            roster_b,
            max_hops=request.max_hops,
            max_route_candidate_pairs=request.max_route_candidate_pairs,
        )

    primary_a = _primary_artist_id(credits_a)
    primary_b = _primary_artist_id(credits_b)

    result: dict[str, Any] = {
        "album_a": {
            "release_id": request.album_a_release_id,
            "release": release_a,
            "credit_rows": credits_a,
            "role_category_counts": _role_category_counts(credits_a),
        },
        "album_b": {
            "release_id": request.album_b_release_id,
            "release": release_b,
            "credit_rows": credits_b,
            "role_category_counts": _role_category_counts(credits_b),
        },
        "shared_vs_unique": {
            "recurring_personnel": recurring_personnel,
            "unique_to_album_a": unique_to_a,
            "unique_to_album_b": unique_to_b,
        },
        "direct_route": direct_route,
        "indirect_route": indirect_route,
        "network_overlap": _network_overlap(graph, roster_a, roster_b),
        "scope_tier_comparison": _scope_tier_comparison(
            request.corpus_snapshot_root, primary_a, primary_b
        ),
    }
    return result
