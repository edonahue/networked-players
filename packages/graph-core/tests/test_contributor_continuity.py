"""Tests for the contributor-continuity check (graph-expansion plan section 22.4).

The gate is deliberately asymmetric: losing a documented path ENDPOINT fails,
losing an interior contributor does not. That asymmetry is the owner's 2026-09-05
decision that contributor pages are derived rather than permanent."""

from __future__ import annotations

from networked_players_graph_core.contributor_continuity import contributor_continuity_report


def _challenge(pairs, artists=None):
    return {
        "paths": [{"from_artist_id": a, "to_artist_id": b} for a, b in pairs],
        "artists": [{"artist_id": i, "name": n} for i, n in (artists or {}).items()],
    }


def _index(ids):
    return {"contributors": [{"artist_id": i} for i in ids]}


def test_keeping_every_endpoint_passes_even_when_interior_contributors_churn() -> None:
    """The real Round 1 outcome: 76 interior contributors dropped while all 173
    published path endpoints survived. Derived pages may come and go."""
    report = contributor_continuity_report(
        previous_challenge=_challenge([(1, 2), (3, 4)]),
        current_challenge=_challenge([(1, 2), (3, 4), (5, 6)]),
        previous_index=_index([1, 2, 3, 4, 900, 901]),
        current_index=_index([1, 2, 3, 4, 5, 6, 902]),
    )
    assert report["ok"] is True
    assert report["path_endpoints"]["lost"] == []
    # The churn is still reported, not silently swallowed.
    assert report["contributor_index"] == {
        "previous": 6,
        "current": 7,
        "kept": 4,
        "removed": 2,
        "added": 3,
    }


def test_losing_a_documented_path_endpoint_fails() -> None:
    """A connection the site previously asserted has stopped being asserted --
    the one thing --carry-forward-challenge exists to prevent."""
    report = contributor_continuity_report(
        previous_challenge=_challenge([(1, 2), (3, 4)], artists={3: "Bill Frisell"}),
        current_challenge=_challenge([(1, 2)]),
        previous_index=_index([1, 2, 3, 4]),
        current_index=_index([1, 2]),
    )
    assert report["ok"] is False
    lost = report["path_endpoints"]["lost"]
    assert [entry["artist_id"] for entry in lost] == [3, 4]
    assert lost[0]["name"] == "Bill Frisell"


def test_it_would_have_caught_this_rounds_regression() -> None:
    """Round 1's first cascade built Record Routes with the default
    --two-hop-target 100 instead of the published 200, and 94 routes-only
    contributors vanished. That specific loss is index churn, so it is reported
    rather than failed -- but a reviewer reading `removed: 94` in the round log
    would have seen it immediately instead of a round later."""
    report = contributor_continuity_report(
        previous_challenge=_challenge([(1, 2)]),
        current_challenge=_challenge([(1, 2)]),
        previous_index=_index(range(100)),
        current_index=_index(range(6, 100)),
    )
    assert report["ok"] is True
    assert report["contributor_index"]["removed"] == 6


def test_an_index_that_lost_everyone_still_reports_precisely() -> None:
    report = contributor_continuity_report(
        previous_challenge=_challenge([]),
        current_challenge=_challenge([]),
        previous_index=_index([1, 2, 3]),
        current_index=_index([]),
    )
    assert report["ok"] is True  # no endpoints were ever documented
    assert report["contributor_index"]["removed"] == 3
    assert report["contributor_index"]["current"] == 0
