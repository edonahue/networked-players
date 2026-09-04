"""Derive expansion candidates from the operator's private collection seed
(graph-expansion Phase 2, plan section 4's "private candidate list", and the
corrected supply stage in plan section 21.3).

    seed releases -> masters -> master-level eligibility -> not already published

This is the editorial lane's candidate *supply*. Until this module existed the
lane had no pool at all: `score_expansion_candidates` and
`greedy_marginal_selection` are both CONSUMERS of a shortlist -- one annotates
it, the other re-ranks it -- and neither can introduce a candidate. Round 1
(2026-09-04) was consequently reported as "blocked on owner picks" when 195
unpublished collection masters were sitting one query away in the working set.

Composition, not new algorithms. Every gate here already exists and is reused
verbatim rather than re-derived:

- release -> master: `CreditGraph.releases_for_ids`, whose rows already carry
  `master_id` (the one-hop corpus preserves the column, `discogs/parquet.py`'s
  `RELEASE_SCHEMA`).
- eligibility and main-release selection: `master_eligibility`'s
  `master_studio_eligibility_reason` / `select_master_main_release_id` -- the
  same two functions `score_expansion_candidates` reuses, so a collection
  candidate is judged by exactly the rule a published album is.
- placeholder/playability handling: `CreditGraph.credit_rows_for_releases`
  already excludes placeholder identities ("Various" and friends), so the
  release-artist resolution below inherits it instead of re-filtering.

**Privacy.** The seed itself is read by the CLI through `SeedManifest.read`;
this function only ever receives already-extracted release ids. Its output is
collection membership and is therefore local-only by contract (plan section
5.2's `in_private_seed`: "local-only flag; never leaves local/") -- the CLI
enforces that with `_require_local_only_output`. Nothing here decides what a
candidate *means*; the owner picks from the scored list (plan section 4:
"The owner picks from it"), and membership never buys a slot by itself.

Ineligible candidates are returned with their reason, never dropped -- the same
"never hidden from the packet" discipline `score_expansion_candidates` states.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Sequence
from typing import Any

from .graph import CreditGraph
from .master_eligibility import master_studio_eligibility_reason, select_master_main_release_id


def _progress(quiet: bool, message: str) -> None:
    """Coarse per-phase progress -- stderr only, never stdout (plan section 18 /
    slice 2-0b's convention; the CLI writes its real artifact to `--output` and
    a JSON summary to stdout, both of which must stay unpolluted)."""
    if not quiet:
        print(message, file=sys.stderr)


def _release_artist(credit_rows: list[dict[str, Any]]) -> tuple[int | None, str | None]:
    """The billed release artist for a candidate's main release, matching
    `analysis.rank_album_candidates`' own rule: the first `release_artist`-scope
    credit. `credit_rows_for_releases` has already dropped placeholder and
    non-playable identities, so "Various Artists" can never head a candidate
    here any more than it can there."""
    for row in credit_rows:
        if row.get("credit_scope") != "release_artist":
            continue
        artist_id = row.get("artist_id")
        if artist_id is None:
            continue
        return int(artist_id), row.get("name")
    return None, None


def derive_collection_candidates(
    graph: CreditGraph,
    seed_release_ids: Sequence[int],
    *,
    allowed_release_ids: frozenset[int],
    master_exclusions: frozenset[int] = frozenset(),
    already_published_master_ids: frozenset[int] = frozenset(),
    quiet: bool = False,
) -> list[dict[str, Any]]:
    """One row per distinct unpublished master the seed releases belong to,
    sorted by `master_id` for determinism.

    Rows are `rank-album-candidates`-shaped (`master_id`, `artist_id`,
    `artist_name`, `sample_title`, `main_release_id`, `year`) so they drop into
    `score_expansion_candidates` and `greedy_marginal_selection` with no
    downstream change, plus this module's own `eligibility`,
    `main_release_selection_reason` and `seed_release_count` fields.

    Already-published masters are excluded *before* eligibility runs -- there is
    no point spending a per-master lookup on an album that cannot be added, and
    excluding at the source (rather than after) is what keeps every count
    downstream honest, exactly the reasoning `rank_album_candidates`'
    `already_published_master_ids` documents.

    `eligibility` is `"eligible"` or a fail-closed reason. A row whose
    `eligibility` is not `"eligible"`, or whose `artist_id`/`main_release_id`
    is `None`, must be filtered out by the caller before being fed to
    `greedy_marginal_selection`, which indexes those keys directly.
    """
    start = time.monotonic()
    _progress(quiet, f"mapping {len(seed_release_ids)} seed releases to masters...")

    releases = graph.releases_for_ids(list(seed_release_ids))
    seed_release_count: dict[int, int] = {}
    for release in releases.values():
        master_id = release.get("master_id")
        if master_id is None:
            continue
        seed_release_count[int(master_id)] = seed_release_count.get(int(master_id), 0) + 1

    candidate_master_ids = sorted(set(seed_release_count) - already_published_master_ids)
    _progress(
        quiet,
        f"{len(seed_release_count)} distinct masters, "
        f"{len(seed_release_count) - len(candidate_master_ids)} already published, "
        f"{len(candidate_master_ids)} candidates to check",
    )

    verdicts: dict[int, tuple[str, int | None, str]] = {}
    for master_id in candidate_master_ids:
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
        verdicts[master_id] = ("eligible", main_release_id, release_reason)

    # One batched credit query across every eligible candidate's own selected
    # main release, never one query per candidate (the same batching
    # `score_expansion_candidates` applies for `roster_size`).
    eligible_release_ids = sorted(
        {release_id for _, release_id, _ in verdicts.values() if release_id is not None}
    )
    credits_by_release = graph.credit_rows_for_releases(eligible_release_ids)

    rows: list[dict[str, Any]] = []
    for master_id in candidate_master_ids:
        eligibility, main_release_id, release_reason = verdicts[master_id]
        master = graph.master(master_id) or {}
        artist_id: int | None = None
        artist_name: str | None = None
        if main_release_id is not None:
            artist_id, artist_name = _release_artist(credits_by_release.get(main_release_id, []))
            if artist_id is None:
                # Real class, not a crash: a master whose selected main release
                # carries no playable release-artist credit has no identity to
                # publish under. `rank_album_candidates` drops these silently;
                # recording the reason keeps it reviewable instead.
                eligibility = "no_release_artist_credit"
        rows.append(
            {
                "master_id": master_id,
                "artist_id": artist_id,
                "artist_name": artist_name,
                "sample_title": master.get("title"),
                "main_release_id": main_release_id,
                "year": master.get("year"),
                "eligibility": eligibility,
                "main_release_selection_reason": release_reason,
                "seed_release_count": seed_release_count[master_id],
            }
        )

    eligible_count = sum(1 for row in rows if row["eligibility"] == "eligible")
    _progress(
        quiet,
        f"done in {time.monotonic() - start:.1f}s, "
        f"{eligible_count} of {len(rows)} candidates eligible",
    )
    return rows
