"""Read `data/albums/expansion-policy-v1.json` and apply its automatic-lane
gates (graph-expansion Phase 2, plan section 5.2's hub-trap guard; corrected
supply stage section 21.3 slice X3).

Until this module existed the policy file was **documentation the code never
read**. `select-graph-rich-candidates` optimises purely for marginal edge
count, so in Round 1 four of its six picks sat outside the committed 5-30
roster band (rosters 34, 40, 42, 50) and had to be filtered out by hand before
the round could proceed. The band is the measured hub-trap guard -- greedy
top-N by raw new-performer count adds ~122 performers per album (plan section
2 finding 4) -- so leaving its enforcement to a manual step a future round can
forget is exactly the kind of gap this phase keeps finding.

Enforcing it is not a tax. Re-running Round 1's graph-value lane over a
band-filtered finalist list produced a *better* lane on every axis: 6 of 6
slots filled instead of 4, all inside the band instead of 2, and 36 new
performers instead of 34.

The roster and overlap figures come from `score_expansion_candidates`' output,
never recomputed here -- one measurement, one owner.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ExpansionPolicyError(ValueError):
    """Raised when a policy file cannot be applied as written."""


def load_automatic_lane_policy(path: str | Path) -> dict[str, Any]:
    """The `automatic_lanes` block of `expansion-policy-v1.json`.

    Fail-closed: a policy file missing the block, the band, or the overlap
    minimum raises rather than silently defaulting. A policy that does not
    actually constrain anything is worse than no policy, because it reads as
    enforcement in the round log while gating nothing.
    """
    payload = json.loads(Path(path).read_text())
    lanes = payload.get("automatic_lanes")
    if not isinstance(lanes, dict):
        raise ExpansionPolicyError("expansion policy has no automatic_lanes block")
    band = lanes.get("roster_band")
    if not isinstance(band, dict) or "min" not in band or "max" not in band:
        raise ExpansionPolicyError("automatic_lanes.roster_band must define min and max")
    if "overlap_existing_minimum" not in lanes:
        raise ExpansionPolicyError("automatic_lanes has no overlap_existing_minimum")
    return lanes


def automatic_lane_rejection(
    scored_row: dict[str, Any] | None, *, policy: dict[str, Any]
) -> str | None:
    """`None` when a scored candidate may enter an automatic lane; otherwise a
    reason string.

    A candidate with no scored row at all is rejected (`not_scored`), never
    admitted on the assumption it would have passed -- the band cannot be
    checked without `roster_size`, and admitting an unchecked candidate is the
    failure this module exists to prevent.
    """
    if scored_row is None:
        return "not_scored"
    if scored_row.get("eligibility") != "eligible":
        return str(scored_row.get("eligibility") or "ineligible")

    roster_size = scored_row.get("roster_size")
    if roster_size is None:
        return "roster_size_unknown"
    band = policy["roster_band"]
    if not (int(band["min"]) <= int(roster_size) <= int(band["max"])):
        return f"roster_outside_band: {roster_size} not in {band['min']}-{band['max']}"

    minimum_overlap = int(policy["overlap_existing_minimum"])
    overlap = scored_row.get("overlap_existing")
    if overlap is None or int(overlap) < minimum_overlap:
        return f"overlap_below_minimum: {overlap} < {minimum_overlap}"
    return None


def filter_to_automatic_lane(
    finalists: list[dict[str, Any]],
    scored_candidates: list[dict[str, Any]],
    *,
    policy: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Finalists that may enter an automatic lane, plus a reason histogram.

    Order is preserved, so a caller's own ranking survives. The histogram is
    returned rather than logged so the caller can report *why* a pool shrank --
    a lane that silently comes up short is the thing this phase keeps having
    to diagnose after the fact.
    """
    scored_by_master = {int(row["master_id"]): row for row in scored_candidates}
    kept: list[dict[str, Any]] = []
    rejections: dict[str, int] = {}
    for finalist in finalists:
        reason = automatic_lane_rejection(
            scored_by_master.get(int(finalist["master_id"])), policy=policy
        )
        if reason is None:
            kept.append(finalist)
            continue
        # Band misses are bucketed by kind, not by their individual numbers,
        # so the histogram stays readable over a pool of thousands.
        key = reason.split(":")[0]
        rejections[key] = rejections.get(key, 0) + 1
    return kept, rejections
