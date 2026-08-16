"""Album-candidate review report: a human-facing decoration of
`rank_album_candidates`' output, not a second ranking and not an executor.

`rank_album_candidates` already answers "how graph-rich is this candidate
by variant/credit-row proxy" (see `analysis.py`). This module answers a
different question a human reviewer actually needs before promoting a
candidate into the editorial list: "if this candidate were added, how much
of what it credits is genuinely NEW to the published graph, and does its
own evidence carry any caveat worth knowing about first?" It never adds a
candidate to the catalog itself -- that stays a human editorial decision
via `data/albums/top-albums-v1.json`, exactly as today.

**Structural utility vs. evidence quality, kept explicitly separate:**
`new_contributor_count` is a structural signal (would this genuinely widen
the graph, or mostly re-touch names the graph already knows). Evidence
quality is a separate, unrelated question, expressed as `evidence_caveats`
sourced from the SAME format-descriptor caveat vocabulary the evidence
release registry already publishes (`networked_players_contracts.
evidence_release_registry`) -- never fused into one blended score. A
candidate can be structurally rich and evidence-caveated at once (a
box-set reissue with a huge, real credit list); this report reports both
facts and leaves the judgment call to the human reviewer.

**This is an approximation, not a graph-build simulation.** The
contributor counts below apply the same base eligibility filter
`credit_edges_sql` uses everywhere else (`playable_identity`, non-null
`artist_id`, not-a-placeholder-identity -- see `CreditGraph.
credit_rows_for_releases`), but deliberately omit `credit_edges_sql`'s
track-shape and compilation-clique guards (`compilation_track_artist_
threshold`, `max_artists_per_track`, the `album_shaped`/`single_billed`
classification). Replicating that machinery here would let a review report
silently drift out of sync with the real edge builder, or double the
surface area that has to agree with it. A directional "how many credited
names are new" signal is what a reviewer needs before doing more real
work, not a byte-exact prediction of the edges a future graph regeneration
would create.
"""

from __future__ import annotations

from typing import Any

from networked_players_contracts.evidence_release_registry import (
    CAVEAT_FLAG_NAMES,
    caveat_flags_for_descriptors,
)

from .graph import CreditGraph

__all__ = ["review_album_candidates"]


def _caveat_names(flags: int) -> list[str]:
    return [name for bit, name in enumerate(CAVEAT_FLAG_NAMES) if flags & (1 << bit)]


def _why(
    candidate: dict[str, Any],
    *,
    contributor_count: int,
    new_contributor_count: int,
    caveats: list[str],
) -> str:
    parts = [
        f"score {candidate['score']} ({candidate['variant_count']} release variant(s), "
        f"{candidate['credit_rows']} credit row(s) across the catalog)",
        f"main release credits {contributor_count} playable contributor(s); "
        f"{new_contributor_count} not already present in the published graph",
    ]
    if caveats:
        parts.append(f"main release format tagged: {', '.join(caveats)}")
    return "; ".join(parts)


def review_album_candidates(
    graph: CreditGraph,
    candidates: list[dict[str, Any]],
    *,
    published_graph_artist_ids: frozenset[int],
) -> dict[str, Any]:
    """Decorate `rank_album_candidates`' output with `contributor_count`,
    `new_contributor_count`, `evidence_caveats`, and a real-fact `why`
    string, sorted by `new_contributor_count` (the structural question a
    reviewer usually wants first), `score`, then `master_id` for a stable
    tie-break. Every input candidate reappears exactly once, unmodified
    except for the added keys -- this never drops or reorders which
    candidates exist, only how they're presented.
    """
    main_release_ids = [int(c["main_release_id"]) for c in candidates]
    credits_by_release = graph.credit_rows_for_releases(main_release_ids)
    descriptors_by_release = graph.format_descriptors_for_ids(main_release_ids)

    reviewed: list[dict[str, Any]] = []
    for candidate in candidates:
        release_id = int(candidate["main_release_id"])
        contributor_ids = {
            int(row["artist_id"])
            for row in credits_by_release.get(release_id, [])
            if row.get("artist_id") is not None
        }
        new_contributor_ids = contributor_ids - published_graph_artist_ids
        caveats = _caveat_names(
            caveat_flags_for_descriptors(descriptors_by_release.get(release_id, frozenset()))
        )
        reviewed.append(
            {
                **candidate,
                "contributor_count": len(contributor_ids),
                "new_contributor_count": len(new_contributor_ids),
                "evidence_caveats": caveats,
                "why": _why(
                    candidate,
                    contributor_count=len(contributor_ids),
                    new_contributor_count=len(new_contributor_ids),
                    caveats=caveats,
                ),
            }
        )

    reviewed.sort(key=lambda r: (-r["new_contributor_count"], -r["score"], r["master_id"]))

    return {
        "version": 1,
        "method_note": (
            "contributor_count/new_contributor_count are an approximate, directional "
            "signal (base credit-eligibility filter only, no track-shape/compilation-"
            "clique guards) -- not a prediction of exact post-regeneration graph edges. "
            "evidence_caveats reports the candidate's own main release format tags "
            "(reliable for exclusion, not for confirmation -- an empty list is not a "
            "positive quality claim). This report never adds a candidate to any "
            "catalog; promotion stays a human editorial decision."
        ),
        "candidate_count": len(reviewed),
        "candidates": reviewed,
    }
