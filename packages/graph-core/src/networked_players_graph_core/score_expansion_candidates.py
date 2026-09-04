"""Score expansion candidates as a transparent data product (graph-expansion
Phase 2, plan section 5.2) -- never a scalar weighted sum, one explicit
component per candidate, so "why is this album here" always has a real
answer instead of a coefficient.

Slice A (the hub-trap-guard components) --

- `eligibility` / `main_release_selection_reason`: reuses `master_eligibility`
  verbatim, never a second copy of the studio-album rule.
- `roster_size`: performer-qualifying credits on the candidate's own selected
  main release, via `pathfinding_graph.edge_eligible_membership_artist_ids`
  -- the exact same traversal-eligibility rule a catalog album's own roster
  would be judged by once published, not a looser candidate-only heuristic.
- `overlap_existing` / `new_performers` (raw and density): the roster split
  against the already-published graph's own real artist nodes.

Slice B (this addition) --

- `bridge_span`: distinct catalog albums (virtual anchor nodes, ADR 0058)
  reachable in one hop from any roster member who is already a real graph
  node. Computed directly against the published graph's own CSR adjacency
  -- deliberately NOT importing `packages/research`'s `PublishedGraph`
  (graph-core sits below both catalog and research in this project's layer
  order and must never import upward, `master_eligibility.py`'s own
  docstring makes the same point about the catalog boundary), so this is a
  small, purpose-built index-by-node-id + CSR-slot lookup local to this
  module rather than a shared abstraction that would invert that order.
  Optional: `None` when no `pathfinding_graph` is given.
- `coverage_delta`: how many of the candidate's own master genre/style/decade
  values land in an already-identified underrepresented bucket
  (`coverage_gaps.identify_underrepresented`'s own output, computed ONCE by
  the caller over the current catalog -- never re-derived per candidate,
  since that measurement needs the whole catalog, not one candidate).
  Optional: `None` when no `underrepresented_buckets` is given.

Deliberately NOT in this module (real, separate design work): `marginal_new_edges`
-- `marginal_evaluation.greedy_marginal_selection` already computes this
exact field, but as a POOL-LEVEL greedy selection recomputed after each
pick, not an independent per-candidate score the way every field above is.
It already has its own CLI (`select-graph-rich-candidates`); a later round-
assembly step merges its output with this module's by `master_id`, rather
than this module duplicating pool-level selection logic.

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

from .coverage_gaps import _decade
from .graph import CreditGraph
from .master_eligibility import master_studio_eligibility_reason, select_master_main_release_id
from .pathfinding_graph import edge_eligible_membership_artist_ids


def _progress(quiet: bool, message: str) -> None:
    """Coarse per-phase progress -- stderr only, never stdout (graph-
    expansion Phase 1/2, plan section 18/slice 2-0b's own convention,
    reused here since a candidate pool can run to thousands of masters)."""
    if not quiet:
        print(message, file=sys.stderr)


def _bridge_span(
    roster_artist_ids: set[int],
    *,
    node_ids: list[int],
    index_by_node_id: dict[int, int],
    offsets: list[int],
    neighbors: list[int],
) -> int:
    """Distinct virtual album-anchor node ids (negative, ADR 0058) reachable
    in one hop from any roster member who is already a real graph node --
    the roster members with no graph presence at all contribute nothing
    here, exactly as they contribute nothing to `overlap_existing` either.

    `neighbors[slot]` is an INDEX into `node_ids`, never the raw node id
    itself (the same CSR convention `networkExplorer.ts`'s `buildView` and
    this codebase's every other CSR walk already use) -- resolved through
    `node_ids[...]` before checking sign, not checked directly."""
    anchor_ids: set[int] = set()
    for artist_id in roster_artist_ids:
        index = index_by_node_id.get(artist_id)
        if index is None:
            continue
        for slot in range(offsets[index], offsets[index + 1]):
            neighbor_id = node_ids[neighbors[slot]]
            if neighbor_id < 0:
                anchor_ids.add(neighbor_id)
    return len(anchor_ids)


def _coverage_delta(
    master: dict[str, Any], underrepresented_buckets: frozenset[tuple[str, str]]
) -> int:
    """How many of this master's own decade/genre/style values land in an
    already-identified underrepresented bucket -- a real, if simple, count,
    never a synthesized "gap score" beyond what's directly checkable."""
    delta = 0
    if ("decades", _decade(master.get("year"))) in underrepresented_buckets:
        delta += 1
    for genre in master.get("genres") or []:
        if ("genres", genre) in underrepresented_buckets:
            delta += 1
    for style in master.get("styles") or []:
        if ("styles", style) in underrepresented_buckets:
            delta += 1
    return delta


def score_expansion_candidates(
    graph: CreditGraph,
    candidates: list[dict[str, Any]],
    *,
    existing_node_ids: frozenset[int],
    allowed_release_ids: frozenset[int],
    master_exclusions: frozenset[int] = frozenset(),
    editorial_master_ids: frozenset[int] = frozenset(),
    private_seed_master_ids: frozenset[int] = frozenset(),
    pathfinding_graph: dict[str, Any] | None = None,
    underrepresented_buckets: frozenset[tuple[str, str]] = frozenset(),
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

    `pathfinding_graph`, when given, is the full published `graph.v4.json`
    payload (not just its `node_ids` -- `bridge_span` needs the CSR
    adjacency too) -- `bridge_span` stays `None` per row without it.
    `underrepresented_buckets`, when given, is
    `coverage_gaps.identify_underrepresented`'s own output over the CURRENT
    catalog, reshaped into a `{(dimension, bucket), ...}` set -- computed
    ONCE by the caller, never re-derived here. `coverage_delta` stays `0`
    per row without it (an empty gap set and "no candidate closes any gap"
    are the same real answer, so `0` rather than `None` is honest here,
    unlike `bridge_span`/`roster_size`, which are genuinely unknown -- not
    just zero -- when their required input is absent).

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

    node_ids: list[int] | None = None
    index_by_node_id: dict[int, int] | None = None
    offsets: list[int] | None = None
    neighbors: list[int] | None = None
    if pathfinding_graph is not None:
        node_ids = [int(n) for n in pathfinding_graph["node_ids"]]
        index_by_node_id = {node_id: i for i, node_id in enumerate(node_ids)}
        offsets = [int(o) for o in pathfinding_graph["offsets"]]
        neighbors = [int(n) for n in pathfinding_graph["neighbors"]]

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
            "bridge_span": None,
            "coverage_delta": 0,
        }
        if underrepresented_buckets:
            master = graph.master(master_id)
            if master is not None:
                row["coverage_delta"] = _coverage_delta(master, underrepresented_buckets)
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
            if (
                node_ids is not None
                and index_by_node_id is not None
                and offsets is not None
                and neighbors is not None
            ):
                row["bridge_span"] = _bridge_span(
                    roster_artist_ids,
                    node_ids=node_ids,
                    index_by_node_id=index_by_node_id,
                    offsets=offsets,
                    neighbors=neighbors,
                )
        rows.append(row)

    _progress(
        quiet, f"scoring done in {time.monotonic() - start:.1f}s, {len(rows)} candidates scored"
    )
    return rows
