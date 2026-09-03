"""Master-level studio-album eligibility (graph-expansion Phase 0, slice
0-B; see docs/decisions/0069-public-universe-model-and-expansion-policy.md).

Combines two existing, independently-tested gates instead of inventing a
third: `album_policy.master_non_studio_reason` (Discogs' own editorial
genre/style -- catches soundtracks and stage & screen recordings that carry
no format descriptor at all) and the release-format-policy allow-list built
upstream by `packages/catalog/.../release_format_policy.py` (studio-album-v1)
-- passed in here as `allowed_release_ids`, the same frozenset every other
graph-core eligibility check (`challenge.release_eligibility_reason`,
`analysis.assemble_album_catalog`) already takes as data, never recomputed.
Graph-core must never import from `networked_players_catalog`
(`graph.py`'s own module docstring) -- this module respects that boundary
by consuming the already-built allow-list rather than the classifier that
produced it.

Fixes a measured false negative (graph-expansion plan section 5.1): 18 of
the 179 catalog albums' `main_release_id` points at a Reissue/Remastered
pressing, which would fail a descriptor-only rule that only ever checks the
one release a catalog entry happens to cite. A master is eligible if its
genre/style passes AND at least one of its REAL releases in the working set
is format-allowed -- not just the specific pressing a candidate happened to
cite. `select_master_main_release_id` then prefers the master's own
`main_release_id` when that release is itself allowed, falling back to the
earliest-year allowed release under the master, exactly the plan's
"main_release_id selection" rule.

Deliberately per-master (a small handful of CreditGraph calls), not a bulk
DuckDB query with a Python mirror the way `album_policy` is: the genuinely
new logic here (enumerate a master's releases, pick a winner) is release
selection, not a predicate worth re-deriving in SQL, and `graph.master`/
`graph.release_ids_for_master` are already indexed single-master lookups.
`master_non_studio_reason` keeps its own existing SQL mirror unchanged; this
module never needs a second one. If a future bulk scoring pass over
thousands of candidate masters (Phase 2's `score-expansion-candidates`)
measures this to be too slow, that is a real, measured reason to add a
batched form then -- not guessed at here.
"""

from __future__ import annotations

from .album_policy import master_non_studio_reason
from .challenge import _year_from_released
from .graph import CreditGraph


def master_studio_eligibility_reason(
    graph: CreditGraph,
    master_id: int,
    *,
    allowed_release_ids: frozenset[int],
    master_exclusions: frozenset[int] = frozenset(),
) -> str | None:
    """`None` when the master is studio-eligible; otherwise a fail-closed
    reason string, checked in this order: curated exclusion, missing from
    the working set, non-studio genre/style, no format-allowed release
    under it anywhere in the working set."""
    if master_id in master_exclusions:
        return "curated_master_exclusion"
    master = graph.master(master_id)
    if master is None:
        return "master_not_in_working_set"
    genre_style_reason = master_non_studio_reason(master["genres"], master["styles"])
    if genre_style_reason:
        return genre_style_reason
    release_ids = graph.release_ids_for_master(master_id)
    if not any(release_id in allowed_release_ids for release_id in release_ids):
        return "no_format_allowed_release_under_master"
    return None


def select_master_main_release_id(
    graph: CreditGraph,
    master_id: int,
    *,
    allowed_release_ids: frozenset[int],
) -> tuple[int | None, str]:
    """Pick the release id a catalog entry for this master should cite.

    Prefers the master's own `main_release_id` (Discogs' canonical original
    pressing) when the working set has it and it is itself format-allowed.
    Otherwise falls back to the earliest-year format-allowed release under
    the master, ties broken by release_id for determinism. Returns
    `(None, "main_release_not_in_working_set")` when nothing under the
    master is format-allowed -- the RELEASE_FORMAT_RESEARCH coverage-gap
    class a wider working set (a future one-hop re-expansion) is expected to
    shrink over time, never guessed around here."""
    master = graph.master(master_id)
    if master is None:
        return None, "master_not_in_working_set"

    main_release_id = master.get("main_release_id")
    if main_release_id is not None and int(main_release_id) in allowed_release_ids:
        return int(main_release_id), "master_main_release"

    candidate_ids = [
        release_id
        for release_id in graph.release_ids_for_master(master_id)
        if release_id in allowed_release_ids
    ]
    if not candidate_ids:
        return None, "main_release_not_in_working_set"

    releases = graph.releases_for_ids(candidate_ids)
    ranked = sorted(
        candidate_ids,
        key=lambda release_id: (
            _year_from_released((releases.get(release_id) or {}).get("released")) or 9999,
            release_id,
        ),
    )
    return ranked[0], "earliest_allowed_release"
