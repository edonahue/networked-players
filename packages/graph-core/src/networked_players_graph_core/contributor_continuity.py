"""Compare a rebuilt challenge/contributor pair against the previously published
one and report what a round actually did to `/contributors/` URLs.

Nothing in this repo previously caught a contributor page disappearing: there is
no sitemap diff, no persistence test, no redirect, and `contributor_index_failures`
would happily pass an index that had lost 500 people (it validates one file in
isolation). The only related test pins that an *unknown* contributor id should
404. Both times this bit -- Phase 7's unexplained 549 -> 521, and Round 1's
530 -> 518 -- it was noticed a round later, by hand.

**What is guaranteed, and what is not** (owner decision, 2026-09-05). Contributor
pages are *derived*: a page exists because that person is on a currently
documented path, so pages may legitimately appear and disappear as the graph
improves and better routes are found. That is the documented precedent, not a
regression -- `PERFORMER_GRAPH_MIGRATION_REPORT.md` records a contributor 404 as
a verified success, and `PHASE7_REPORT.md` states "521 is not itself evidence of
an error -- a curated-path-driven index legitimately changes membership when the
curated paths themselves change."

What IS guaranteed is narrower and checkable: a **path endpoint** that was
documented in a published round stays documented. Endpoints are what
`--carry-forward-challenge` protects, and losing one means a connection the site
previously asserted has silently stopped being asserted.

So this module fails on lost endpoints and *reports* index churn without failing
on it -- a large movement stays visible in the round log instead of being
discovered later, which is how both previous incidents surfaced.
"""

from __future__ import annotations

from typing import Any


def _path_endpoints(challenge: dict[str, Any]) -> set[int]:
    """Both ends of every documented path. Interior hop artists are deliberately
    excluded -- they are the population that may churn."""
    endpoints: set[int] = set()
    for path in challenge.get("paths", []):
        for key in ("from_artist_id", "to_artist_id"):
            value = path.get(key)
            if value is not None:
                endpoints.add(int(value))
    return endpoints


def _index_ids(index: dict[str, Any]) -> set[int]:
    return {int(c["artist_id"]) for c in index.get("contributors", [])}


def contributor_continuity_report(
    *,
    previous_challenge: dict[str, Any],
    current_challenge: dict[str, Any],
    previous_index: dict[str, Any],
    current_index: dict[str, Any],
) -> dict[str, Any]:
    """What this round did to contributor URLs.

    `ok` is False only when a previously documented path endpoint is no longer
    documented. Index churn is measured and returned either way.
    """
    previous_endpoints = _path_endpoints(previous_challenge)
    current_endpoints = _path_endpoints(current_challenge)
    lost_endpoints = sorted(previous_endpoints - current_endpoints)

    previous_ids = _index_ids(previous_index)
    current_ids = _index_ids(current_index)
    lost_ids = previous_ids - current_ids

    # Name the lost endpoints where possible -- an id alone is not reviewable.
    names = {
        int(a["artist_id"]): a.get("name")
        for a in previous_challenge.get("artists", [])
        if a.get("artist_id") is not None
    }
    return {
        "ok": not lost_endpoints,
        "path_endpoints": {
            "previous": len(previous_endpoints),
            "current": len(current_endpoints),
            "lost": [
                {"artist_id": artist_id, "name": names.get(artist_id)}
                for artist_id in lost_endpoints
            ],
        },
        # Reported, never enforced: derived pages may come and go.
        "contributor_index": {
            "previous": len(previous_ids),
            "current": len(current_ids),
            "kept": len(previous_ids & current_ids),
            "removed": len(lost_ids),
            "added": len(current_ids - previous_ids),
        },
    }
