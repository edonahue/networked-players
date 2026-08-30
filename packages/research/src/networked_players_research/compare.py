"""Album, artist, and scene comparison (Phase 7 PR D, Slices 1-3 -- the
private research workbench's first three comparison types). See docs plan
section 11: a local-only comparison layer over already-existing primitives,
not a new graph engine.

Every graph traversal here goes through `CreditGraph` (`.find_path`,
`.neighbors_batch`, `.degrees`, `.degree`, `.credit_rows_for_releases`,
`.credit_rows_for_artist`, `.release`, `.releases_for_ids`) -- this module
never re-derives BFS or edge SQL itself. Scope-tier comparison reuses
`scope_tier.measure_scope_tiers` directly. Role-category composition reuses
`role_taxonomy.classify_role`, the same taxonomy every other role-aware
feature in the repo uses.

The workbench server/UI (`apps/review/review_server.py --mode workbench`)
and its Explore search/evidence/pin slices are built on top of this module,
not in it -- `run_comparison_and_persist` below is the shared dispatch both
the CLI and the server call. Caveat-flag comparison is deliberately
deferred too: the public site's
caveat signal lives in the evidence-release-registry build path, which a
private corpus snapshot doesn't carry the same way -- reusing it correctly
needs its own investigation, not a guess bolted on here. `compare_artists`'s
"distinct documented routes" is also deferred to a single shortest route:
unlike the TS pathfinding client, `CreditGraph` has no `excludeEdgeKeys`-
style mechanism to force a second, genuinely distinct route, and inventing
one here would be new graph logic, not reuse.

`compare_scenes`'s "scope sensitivity" bullet (from the plan) is also
deferred: it's unclear how to aggregate per-member `measure_scope_tiers`
results across a whole scene without it becoming an unreadable wall of
per-member tables, and that aggregation shape needs a real decision, not a
guess. A scene member with zero credits in the corpus is reported as
"unresolved" rather than failing the whole comparison -- a scene is a
user-authored seed set, and one bad id in a set of ten shouldn't discard
the other nine.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from networked_players_graph_core.graph import (
    CreditGraph,
    EvidencePath,
    FrontierTooLargeError,
)
from networked_players_graph_core.role_taxonomy import RoleCategory, classify_role

from .analyses import _release_year
from .report import _scan_for_forbidden_phrases
from .runs import RESEARCH_ROOT, new_run_id, new_run_paths, write_run_manifest
from .scope_tier import ScopeTierError, measure_scope_tiers

DEFAULT_MAX_HOPS = 4
DEFAULT_MAX_ROUTE_CANDIDATE_PAIRS = 200
COMPARE_MODES = ("albums", "artists", "scenes")


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
    real distinct performer just because they appear on more rows. Correct
    at ALBUM scope (`credit_rows` is one release's worth of rows) -- for
    artist/scene scope, where `credit_rows` spans someone's whole
    discography, see `_role_category_counts_by_release` instead: this
    function would collapse every category to at most 1 per artist
    regardless of how many releases actually carry it, which is exactly
    the bug a real Jamiroquai-corpus check found (5,456 real credit rows
    for one artist producing `{"vocals": 1, "production": 1, ...}`)."""
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


def _role_category_counts_by_release(credit_rows: list[dict[str, Any]]) -> dict[str, int]:
    """`_role_category_counts`'s sibling for artist/scene scope: counts
    DISTINCT (release_id, artist_id, category) triples instead of
    (artist_id, category) pairs, so a role category's count reflects how
    many distinct releases actually carry it, not just whether the
    artist/scene ever held it once across an entire career."""
    triples: set[tuple[int, int, RoleCategory]] = set()
    for row in credit_rows:
        artist_id = row["artist_id"]
        if artist_id is None:
            continue
        release_id = int(row["release_id"])
        for category in classify_role(row["role_text"]):
            triples.add((release_id, int(artist_id), category))
    counts: dict[str, int] = {}
    for _release_id, _artist_id, category in triples:
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

    # `_with_evidence`, not the plain roster-only method: this album
    # evidence should retain non-linked credits (AGENTS.md), and every
    # helper below (`_credited_artist_ids`, `_role_category_counts`,
    # `_shared_and_unique`, `_primary_artist_id`) already skips
    # `artist_id is None` rows itself, so the broader row set is safe to
    # feed into graph-roster computation unchanged.
    credits_by_release = graph.credit_rows_for_releases_with_evidence(
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


@dataclass(frozen=True)
class CompareArtistsRequest:
    corpus_snapshot_root: Path
    artist_a_id: int
    artist_b_id: int
    max_hops: int = DEFAULT_MAX_HOPS


def _era_counts(
    credit_rows: list[dict[str, Any]], releases: dict[int, dict[str, Any]]
) -> dict[str, int]:
    """Distinct releases per decade (not credit-row counts -- an artist
    credited on every track of one album must not out-weigh a real distinct
    release). `_release_year` (analyses.py, already handles a missing/
    malformed `released` field) decides the year; a release with no
    resolvable year is counted under "unknown" rather than silently
    dropped, so the total across buckets always equals the release count."""
    release_ids = {int(row["release_id"]) for row in credit_rows}
    counts: dict[str, int] = {}
    for release_id in release_ids:
        release = releases.get(release_id)
        year = _release_year(release["released"]) if release else None
        bucket = f"{year[:3]}0s" if year else "unknown"
        counts[bucket] = counts.get(bucket, 0) + 1
    return counts


def corpus_coverage(corpus_snapshot_root: Path, artist_id: int) -> dict[str, Any]:
    """`measure_scope_tiers` for one artist, wrapped in the same
    "not_applicable" convention every other not-always-possible comparison
    field here uses -- public (not `_`-prefixed) since the workbench's
    Explore evidence view calls this directly for scope selection, not
    just `compare_artists` below."""
    try:
        return {"case": "measured", "tiers": measure_scope_tiers(corpus_snapshot_root, artist_id)}
    except ScopeTierError as exc:
        return _not_applicable(str(exc))


MAX_GRAPH_NEIGHBORS = 24  # mirrors apps/web's networkExplorer.ts MAX_NEIGHBORS
_MAX_JOINED_ROLE_LEN = 200


def _joined_role_text(rows: list[dict[str, Any]], artist_id: int) -> str:
    """Every distinct non-null `role_text` credited to `artist_id` within
    one release's rows, joined in first-seen order with the same ", "
    separator `role_taxonomy.classify_role` splits on -- a smaller,
    locally-bounded sibling of `pathfinding_graph.py`'s own `_joined_roles`
    (not imported directly: that module's helpers are private to the public
    static-artifact build, and this is a live per-request computation over
    the private corpus, not a shared identical code path)."""
    seen: dict[str, None] = {}
    for row in rows:
        if row.get("artist_id") != artist_id:
            continue
        text = row.get("role_text")
        if isinstance(text, str) and text:
            seen.setdefault(text, None)
    joined = ", ".join(seen)
    return joined[:_MAX_JOINED_ROLE_LEN] if len(joined) > _MAX_JOINED_ROLE_LEN else joined


def build_graph_view(
    graph: CreditGraph,
    center_artist_id: int,
    *,
    max_neighbors: int = MAX_GRAPH_NEIGHBORS,
    role_categories: frozenset[RoleCategory] | None = None,
) -> dict[str, Any]:
    """Bounded one-hop ego-network view of `center_artist_id` -- Phase 7 PR
    D's private mirror of `apps/web`'s `networkExplorer.ts` `buildView`.
    Deliberately the SAME single-hop, recenter-to-navigate shape: that
    component already proved a bounded, keyboard-accessible,
    non-force-directed graph doesn't need more than one hop per view (a
    click on a neighbor re-requests this endpoint centered there instead),
    so a second hop here would be new UX complexity the public version
    doesn't need either.

    `role_categories`, when given, is a HARD traversal filter -- a
    candidate neighbor whose edge role doesn't match any active category is
    excluded before ranking/truncation, never dimmed after the fact -- so a
    filtered view can never surface an edge that fails the predicate.
    Mirrors the *shape* of `roleTaxonomy.ts`'s category filtering, but
    classifies via the real corpus's own `role_text`
    (`role_taxonomy.classify_role`), not an assumed-identical vocabulary.

    Raises `CompareError` if `center_artist_id` has no credited presence in
    the corpus at all -- the same convention `compare_artists` uses."""
    center_name = graph.artist_name(center_artist_id)
    if center_name is None:
        raise CompareError(f"artist_id {center_artist_id} has no credited presence in corpus")

    raw_neighbors = graph.neighbors(center_artist_id)
    if not raw_neighbors:
        return {
            "center": {"artist_id": center_artist_id, "name": center_name, "degree": 0},
            "neighbors": [],
            "truncated": False,
        }

    release_ids = sorted({release_id for (release_id,) in raw_neighbors.values()})
    rows_by_release = graph.credit_rows_for_release_batch(release_ids)

    candidates: list[dict[str, Any]] = []
    for neighbor_id, (release_id,) in raw_neighbors.items():
        rows = rows_by_release.get(release_id, [])
        role_b = _joined_role_text(rows, neighbor_id)
        if role_categories is not None and not (role_categories & set(classify_role(role_b))):
            continue
        candidates.append(
            {
                "artist_id": neighbor_id,
                "release_id": release_id,
                "role_a": _joined_role_text(rows, center_artist_id),
                "role_b": role_b,
            }
        )

    degrees = graph.degrees([center_artist_id, *(c["artist_id"] for c in candidates)])
    candidates.sort(key=lambda c: degrees.get(c["artist_id"], 0), reverse=True)
    shown = candidates[:max_neighbors]

    neighbors = [
        {
            "artist_id": c["artist_id"],
            "name": graph.artist_name(c["artist_id"]) or f"Artist {c['artist_id']}",
            "degree": degrees.get(c["artist_id"], 0),
            "release_id": c["release_id"],
            "role_a": c["role_a"],
            "role_b": c["role_b"],
        }
        for c in shown
    ]
    return {
        "center": {
            "artist_id": center_artist_id,
            "name": center_name,
            "degree": degrees.get(center_artist_id, 0),
        },
        "neighbors": neighbors,
        "truncated": len(candidates) > max_neighbors,
    }


def compare_artists(graph: CreditGraph, request: CompareArtistsRequest) -> dict[str, Any]:
    """Compares two artists directly (no album/release resolution needed --
    unlike `compare_albums`, the artist ids are given, not derived). Raises
    `CompareError` if either artist has no credited presence in the corpus
    at all; every other outcome (no shared collaborators, no route within
    bound) is a valid, explicitly-labeled result, never an exception."""
    credits_a = graph.credit_rows_for_artist(request.artist_a_id)
    credits_b = graph.credit_rows_for_artist(request.artist_b_id)
    if not credits_a:
        raise CompareError(f"artist_id {request.artist_a_id} has no credits in corpus")
    if not credits_b:
        raise CompareError(f"artist_id {request.artist_b_id} has no credits in corpus")

    releases_a = graph.releases_for_ids([row["release_id"] for row in credits_a])
    releases_b = graph.releases_for_ids([row["release_id"] for row in credits_b])

    if request.artist_a_id == request.artist_b_id:
        raise CompareError("artist_a_id and artist_b_id must differ")

    route: dict[str, Any]
    try:
        found = graph.find_path(request.artist_a_id, request.artist_b_id, max_hops=request.max_hops)
    except FrontierTooLargeError:
        route = {"case": "search_bounded"}
    else:
        if found is None:
            route = {"case": "no_path_within_bound"}
        else:
            route = {
                "case": "found",
                "hops": [
                    {
                        "release_id": hop.release_id,
                        "artist_a_id": hop.artist_a_id,
                        "artist_b_id": hop.artist_b_id,
                    }
                    for hop in found.hops
                ],
            }

    return {
        "artist_a": {
            "artist_id": request.artist_a_id,
            "name": graph.artist_name(request.artist_a_id),
            "credit_rows": credits_a,
            "role_category_counts": _role_category_counts_by_release(credits_a),
            "era_counts": _era_counts(credits_a, releases_a),
            "hub_dependence": {"degree": graph.degree(request.artist_a_id)},
            "corpus_coverage": corpus_coverage(request.corpus_snapshot_root, request.artist_a_id),
        },
        "artist_b": {
            "artist_id": request.artist_b_id,
            "name": graph.artist_name(request.artist_b_id),
            "credit_rows": credits_b,
            "role_category_counts": _role_category_counts_by_release(credits_b),
            "era_counts": _era_counts(credits_b, releases_b),
            "hub_dependence": {"degree": graph.degree(request.artist_b_id)},
            "corpus_coverage": corpus_coverage(request.corpus_snapshot_root, request.artist_b_id),
        },
        # Reuses `_network_overlap` with single-artist "rosters" -- shared
        # collaborators is exactly the intersection of each artist's own
        # 1-hop neighborhood, with each artist excluded from being counted
        # as their own collaborator.
        "shared_collaborators": _network_overlap(
            graph, [request.artist_a_id], [request.artist_b_id]
        ),
        "route": route,
    }


@dataclass(frozen=True)
class CompareScenesRequest:
    corpus_snapshot_root: Path
    scene_a_artist_ids: tuple[int, ...]
    scene_b_artist_ids: tuple[int, ...]
    max_hops: int = DEFAULT_MAX_HOPS
    max_route_candidate_pairs: int = DEFAULT_MAX_ROUTE_CANDIDATE_PAIRS


def _resolve_scene(
    graph: CreditGraph, artist_ids: tuple[int, ...]
) -> tuple[list[int], list[int], list[dict[str, Any]]]:
    """Splits a scene's member ids into those with real corpus credits and
    those without (a user-authored seed set can legitimately name someone
    absent from this particular corpus), returning the resolved ids, the
    unresolved ids, and the union of every resolved member's own credit
    rows."""
    # One batched query for every member instead of one query per member --
    # `credit_rows_for_artist` in a loop here was measured elsewhere in this
    # codebase (`credit_rows_for_release_batch`'s own docstring) at
    # ~0.5-1s/query against the real corpus, and this path runs live in the
    # interactive workbench server with no cap on scene size.
    grouped = graph.credit_rows_for_artists(artist_ids)
    resolved: list[int] = []
    unresolved: list[int] = []
    all_credits: list[dict[str, Any]] = []
    for artist_id in artist_ids:
        rows = grouped.get(artist_id, [])
        if rows:
            resolved.append(artist_id)
            all_credits.extend(rows)
        else:
            unresolved.append(artist_id)
    return resolved, unresolved, all_credits


def compare_scenes(graph: CreditGraph, request: CompareScenesRequest) -> dict[str, Any]:
    """Compares two user-authored scenes (explicit, labelled artist-id seed
    sets -- see the plan doc's definition). Raises `CompareError` only if a
    scene is empty to begin with, or if EVERY member of a scene is
    unresolved (nothing at all to compare); a partially-unresolved scene is
    a valid, reported result, not an error."""
    if not request.scene_a_artist_ids or not request.scene_b_artist_ids:
        raise CompareError("scene_a_artist_ids and scene_b_artist_ids must both be non-empty")

    resolved_a, unresolved_a, credits_a = _resolve_scene(graph, request.scene_a_artist_ids)
    resolved_b, unresolved_b, credits_b = _resolve_scene(graph, request.scene_b_artist_ids)
    if not resolved_a:
        raise CompareError("no member of scene_a has any credits in corpus")
    if not resolved_b:
        raise CompareError("no member of scene_b has any credits in corpus")

    overlap_ids = sorted(set(resolved_a) & set(resolved_b))
    unique_to_a = sorted(set(resolved_a) - set(resolved_b))
    unique_to_b = sorted(set(resolved_b) - set(resolved_a))

    # "Connecting releases": a real, direct release-level intersection --
    # a scene_a member and a scene_b member (not necessarily the same
    # person; that's `overlap_ids` above) credited on the SAME documented
    # release. Distinct from `shared_collaborators` below, which is about
    # third parties connected to both scenes' 1-hop neighborhoods, not a
    # direct co-credit.
    release_ids_a = {int(row["release_id"]) for row in credits_a}
    release_ids_b = {int(row["release_id"]) for row in credits_b}
    connecting_release_ids = sorted(release_ids_a & release_ids_b)

    return {
        "scene_a": {
            "member_artist_ids": list(request.scene_a_artist_ids),
            "resolved_artist_ids": resolved_a,
            "unresolved_artist_ids": unresolved_a,
            "role_category_counts": _role_category_counts_by_release(credits_a),
        },
        "scene_b": {
            "member_artist_ids": list(request.scene_b_artist_ids),
            "resolved_artist_ids": resolved_b,
            "unresolved_artist_ids": unresolved_b,
            "role_category_counts": _role_category_counts_by_release(credits_b),
        },
        "overlap_and_separation": {
            "overlap_artist_ids": overlap_ids,
            "unique_to_scene_a": unique_to_a,
            "unique_to_scene_b": unique_to_b,
        },
        "connecting_releases": {
            "count": len(connecting_release_ids),
            "release_ids": connecting_release_ids,
        },
        # Reuses `_network_overlap` unchanged -- shared collaborators across
        # two scenes is the same third-party 1-hop-overlap computation as
        # for two albums or two artists, just with N-member rosters.
        "shared_collaborators": _network_overlap(graph, resolved_a, resolved_b),
        # Reuses `_route_between` unchanged -- bounded routes between two
        # sets of candidate artists is exactly what it already does for
        # compare_albums's indirect-route search.
        "routes_between_sets": _route_between(
            graph,
            resolved_a,
            resolved_b,
            max_hops=request.max_hops,
            max_route_candidate_pairs=request.max_route_candidate_pairs,
        ),
    }


def corpus_version_string(corpus_root: Path) -> str:
    """A real, content-derived identity for a corpus snapshot -- built from
    the manifest's own per-file `sha256` hashes (present under both a
    canonical full snapshot's manifest, `parquet.py`'s own writer, and a
    `research-build-corpus` topic corpus's manifest, `corpus.py`'s own
    writer -- both list `files: [{path, sha256, ...}, ...]`) plus
    `schema_version`/`parser_version`.

    A first attempt at this used `topic.corpus_version` instead (a real
    Codex-review finding against the ORIGINAL directory-name+snapshot_date
    identity: two different topic corpora sharing both would collide). That
    was still insufficient (a second, real Codex-review finding): a
    canonical snapshot has no `topic` key at all, and `topic.corpus_version`
    itself hashes only the corpus's declared *parameters* (topic, hop_tier,
    seed_artist_ids, source_snapshot_date) -- reparsing a canonical
    snapshot, or rebuilding a same-seed/same-date topic corpus over
    corrected input or a bumped parser/schema version, changes the actual
    Parquet bytes without changing any of those parameters. Hashing the
    manifest's own per-file content hashes catches exactly that case, for
    either corpus shape, with no dependence on which optional keys a given
    manifest happens to carry.

    Falls back to the old directory-name+snapshot_date scheme only for a
    manifest with no `files` list at all (e.g. hand-built test fixtures, or
    a manifest shape that predates per-file hashing)."""
    manifest_path = corpus_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
    files = manifest.get("files")
    if isinstance(files, list) and files:
        file_digest = hashlib.sha256(
            json.dumps(
                sorted((entry.get("path"), entry.get("sha256")) for entry in files),
                sort_keys=True,
            ).encode()
        ).hexdigest()
        return (
            f"{manifest.get('schema_version', 'unknown')}:"
            f"{manifest.get('parser_version', 'unknown')}:{file_digest}"
        )
    return f"{corpus_root.name}:{manifest.get('snapshot_date', 'unknown')}"


def _serialize_request(
    request: CompareAlbumsRequest | CompareArtistsRequest | CompareScenesRequest,
) -> dict[str, Any]:
    """The exact, directly-reusable input a request dataclass carries --
    literally what `build_compare_request` (the workbench server) or the
    CLI's own argument parsing would need to reproduce this run. `Path` is
    the only field across all three request dataclasses `asdict` can't
    serialize on its own; every other field (including
    `CompareScenesRequest`'s `tuple[int, ...]` id lists) is already
    JSON-native."""
    data = asdict(request)
    data["corpus_snapshot_root"] = str(data["corpus_snapshot_root"])
    return data


def run_comparison_and_persist(
    mode: str,
    request: CompareAlbumsRequest | CompareArtistsRequest | CompareScenesRequest,
    *,
    topic: str,
    research_root: Path = RESEARCH_ROOT,
    run_id: str | None = None,
    open_graph: Callable[[Path], AbstractContextManager[CreditGraph]] = CreditGraph.open,
) -> dict[str, Any]:
    """Opens a `CreditGraph` over the request's own corpus root, runs the
    right `compare_*` function for `mode`, and persists the result as a run
    under `research_root/<topic>/runs/<run-id>/` -- exactly the same
    bookkeeping `research-analyze` already uses. Shared by the CLI
    (`research-compare`) and the workbench server mode so both stay in
    lockstep rather than maintaining two copies of this dispatch.

    `open_graph` defaults to `CreditGraph.open` itself -- the CLI's
    existing one-shot behavior (open, compare, close), completely
    unchanged. The workbench server passes a cache-backed context manager
    instead (`WorkbenchGraphCache.checkout` in `apps/review/review_server.
    py`), so repeated comparisons against the SAME corpus reuse one
    already-materialized graph (skipping the ~2.5-minute credit_edges
    rebuild) via `CreditGraph.cursor()` rather than every request paying
    that cost fresh -- a real, independently-confirmed performance gap
    (Phase 7 closeout, sibling to PR #178's own uncached scope-tier
    finding, which the same closeout fixes separately)."""
    if mode not in COMPARE_MODES:
        raise CompareError(f"unrecognized mode: {mode!r}; must be one of {COMPARE_MODES}")

    started_at = datetime.now(UTC).isoformat()
    with open_graph(request.corpus_snapshot_root) as graph:
        if mode == "albums":
            if not isinstance(request, CompareAlbumsRequest):
                raise CompareError("mode 'albums' requires a CompareAlbumsRequest")
            comparison = compare_albums(graph, request)
        elif mode == "artists":
            if not isinstance(request, CompareArtistsRequest):
                raise CompareError("mode 'artists' requires a CompareArtistsRequest")
            comparison = compare_artists(graph, request)
        else:
            if not isinstance(request, CompareScenesRequest):
                raise CompareError("mode 'scenes' requires a CompareScenesRequest")
            comparison = compare_scenes(graph, request)

    resolved_run_id = run_id or new_run_id()
    run_paths = new_run_paths(topic, resolved_run_id, research_root=research_root)
    run_paths.ensure_dirs()
    (run_paths.root / "comparison.json").write_text(
        json.dumps(comparison, indent=2, sort_keys=True) + "\n"
    )
    (run_paths.root / "request.json").write_text(
        json.dumps({"mode": mode, **_serialize_request(request)}, indent=2, sort_keys=True) + "\n"
    )

    finished_at = datetime.now(UTC).isoformat()
    write_run_manifest(
        run_paths,
        topic=topic,
        run_id=resolved_run_id,
        corpus_version=corpus_version_string(request.corpus_snapshot_root),
        analyses=[f"compare_{mode}"],
        started_at=started_at,
        finished_at=finished_at,
    )
    return {"run_id": resolved_run_id, "run_root": str(run_paths.root), "comparison": comparison}
