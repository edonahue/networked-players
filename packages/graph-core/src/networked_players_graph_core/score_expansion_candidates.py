"""Score expansion candidates as a transparent data product (graph-expansion
Phase 2, plan section 5.2) -- never a scalar weighted sum, one explicit
component per candidate, so "why is this album here" always has a real
answer instead of a coefficient.

This is the first slice of section 5.2's scorer: the components that most
directly guard the measured hub trap (plan section 2: naive top-N selection
by raw new-performer count added ~122 performers/album, all from the same
handful of session-heavy records) --

- `eligibility` / `main_release_selection_reason`: reuses `master_eligibility`
  verbatim, never a second copy of the studio-album rule.
- `roster_size`: performer-qualifying credits on the candidate's own selected
  main release, via `pathfinding_graph.edge_eligible_membership_artist_ids`
  -- the exact same traversal-eligibility rule a catalog album's own roster
  would be judged by once published, not a looser candidate-only heuristic.
- `overlap_existing` / `new_performers` (raw and density): the roster split
  against the already-published graph's own real artist nodes.

Deliberately NOT in this slice (real, separate design work): `marginal_new_edges`
(needs the whole-pool greedy `marginal_evaluation.greedy_marginal_selection`,
which recomputes after each pick -- a pool-level computation, not an
independent per-candidate score the way everything else here is),
`bridge_span` (distinct catalog anchors within 1 hop of the roster), and
`coverage_delta` (needs a precomputed catalog-composition baseline). None of
those block this slice's fields from being real and useful on their own --
see the plan's section 5.2 table for the full component set.

Ineligible candidates are still scored and returned, never dropped here --
"never hidden from the packet" is this whole scoring system's own stated
discipline (plan section 5.2's `roster_size`/`overlap_existing` rows); lane
assembly (a separate, later step) is where an eligibility verdict actually
gates inclusion.
"""

from __future__ import annotations

import sys
import time
from typing import Any

from .graph import CreditGraph
from .master_eligibility import master_studio_eligibility_reason, select_master_main_release_id
from .pathfinding_graph import edge_eligible_membership_artist_ids


def _progress(quiet: bool, message: str) -> None:
    """Coarse per-phase progress -- stderr only, never stdout (graph-
    expansion Phase 1/2, plan section 18/slice 2-0b's own convention,
    reused here since a candidate pool can run to thousands of masters)."""
    if not quiet:
        print(message, file=sys.stderr)


def score_expansion_candidates(
    graph: CreditGraph,
    candidates: list[dict[str, Any]],
    *,
    existing_node_ids: frozenset[int],
    allowed_release_ids: frozenset[int],
    master_exclusions: frozenset[int] = frozenset(),
    editorial_master_ids: frozenset[int] = frozenset(),
    private_seed_master_ids: frozenset[int] = frozenset(),
    quiet: bool = False,
) -> list[dict[str, Any]]:
    """One row per candidate, in the same order given. `candidates` is a
    `rank-album-candidates`-shaped list (each carrying at least `master_id`;
    `artist_id`/`artist_name`/`sample_title` are carried through untouched
    if present, for a human-readable packet without a second lookup).

    `existing_node_ids` is the already-published pathfinding graph's own
    real (positive) artist node ids -- `overlap_existing` counts a
    candidate's roster against exactly what a player can already reach,
    not the whole one-hop corpus (which would make nearly every artist
    "existing" and the hub-trap guard meaningless).

    `editorial_master_ids`/`private_seed_master_ids` are pure pass-through
    flags this function does not interpret -- lane assembly (a separate,
    later step) decides what they mean for inclusion. `private_seed_master_ids`
    is documented local-only by the caller's own contract (plan section
    5.2's `in_private_seed`: "local-only flag; never leaves local/") --
    this function has no opinion on where its caller writes the result,
    only that the flag is carried through honestly.

    Eligibility and main-release selection happen per-master (cheap,
    single-master `CreditGraph` lookups, per `master_eligibility`'s own
    documented reasoning) but the roster query itself is ONE batched
    `credit_rows_for_releases` call across every eligible candidate's
    resolved main release, not one query per candidate."""
    start = time.monotonic()
    _progress(quiet, f"scoring {len(candidates)} expansion candidates...")

    verdicts: dict[int, tuple[str | None, int | None, str]] = {}
    for candidate in candidates:
        master_id = int(candidate["master_id"])
        reason = master_studio_eligibility_reason(
            graph,
            master_id,
            allowed_release_ids=allowed_release_ids,
            master_exclusions=master_exclusions,
        )
        if reason is not None:
            verdicts[master_id] = (reason, None, reason)
            continue
        main_release_id, release_reason = select_master_main_release_id(
            graph, master_id, allowed_release_ids=allowed_release_ids
        )
        if main_release_id is None:
            verdicts[master_id] = (release_reason, None, release_reason)
            continue
        verdicts[master_id] = (None, main_release_id, release_reason)

    eligible_release_ids = sorted(
        {
            main_release_id
            for _, main_release_id, _ in verdicts.values()
            if main_release_id is not None
        }
    )
    credits_by_release = graph.credit_rows_for_releases(eligible_release_ids)

    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        master_id = int(candidate["master_id"])
        eligibility_reason, main_release_id, release_reason = verdicts[master_id]
        row: dict[str, Any] = {
            "master_id": master_id,
            "artist_id": candidate.get("artist_id"),
            "artist_name": candidate.get("artist_name"),
            "sample_title": candidate.get("sample_title"),
            "eligibility": "eligible" if eligibility_reason is None else eligibility_reason,
            "main_release_id": main_release_id,
            "main_release_selection_reason": release_reason,
            "roster_size": None,
            "roster_artist_ids": None,
            "overlap_existing": None,
            "new_performers": None,
            "new_performer_density": None,
            "editorial": int(master_id in editorial_master_ids),
            "in_private_seed": int(master_id in private_seed_master_ids),
        }
        if main_release_id is not None:
            membership = {"credits": credits_by_release.get(main_release_id, [])}
            roster_artist_ids = edge_eligible_membership_artist_ids(membership)
            overlap = roster_artist_ids & existing_node_ids
            roster_size = len(roster_artist_ids)
            new_performers = roster_size - len(overlap)
            row.update(
                roster_size=roster_size,
                roster_artist_ids=sorted(roster_artist_ids),
                overlap_existing=len(overlap),
                new_performers=new_performers,
                new_performer_density=(new_performers / roster_size if roster_size else 0.0),
            )
        rows.append(row)

    _progress(
        quiet, f"scoring done in {time.monotonic() - start:.1f}s, {len(rows)} candidates scored"
    )
    return rows
