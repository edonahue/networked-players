"""Measures real one-hop/two-hop candidate counts per role-aware game mode
(Phase 2 Slice H) BEFORE committing to building any of them -- the
"measured, not designed-then-hoped" discipline ADR 0039/0043 already
established for the flagship game's own launch.

Reuses `connection_rounds.py`'s exact album-performer-intersection
discovery shape (index each album's eligible credited artists on its main
release, then intersect two albums' eligible sets) -- the only change is
which role-text predicate counts as "eligible" for a given candidate mode.
Does not build full game rounds (ids, distractors, quality gates); this is
a measurement pass only, and its output is local-only
(`local/analysis/role-mode-candidates/`), never published -- these are
diagnostic counts over the real catalog, the same sensitivity class as the
round-generation diagnostics `build-connection-rounds` already treats as
local.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from itertools import combinations
from typing import Any

from .eligibility import _ROLE_CATEGORY_BY_TOKEN
from .graph import CreditGraph
from .role_taxonomy import RoleCategory, classify_role

# Fine-grained tokens (eligibility.py's own display-category map) for the
# two candidate modes that need finer granularity than role_taxonomy.py's
# coarse buckets provide (STRINGS bundles guitar with bass/banjo/violin;
# PERCUSSION_KEYS bundles drums with keys/organ) -- "Rhythm Section" and
# "Guitar Paths" are about specific instruments, not a whole taxonomy tier.
_RHYTHM_SECTION_TOKENS = frozenset({"drums", "bass"})
_GUITAR_TOKENS = frozenset({"guitar"})


def _fine_grained_role_predicate(tokens: frozenset[str]) -> Callable[[str | None], bool]:
    def predicate(role_text: str | None) -> bool:
        if not role_text:
            return False
        for component in role_text.split(","):
            stripped = component.strip().lower()
            # Strip a bracketed qualifier the same way eligibility.py does
            # ("Guitar [12-String]" must still match "guitar").
            stripped = stripped.split("[")[0].strip()
            if _ROLE_CATEGORY_BY_TOKEN.get(stripped) in tokens:
                return True
        return False

    return predicate


def _taxonomy_category_predicate(
    categories: frozenset[RoleCategory],
) -> Callable[[str | None], bool]:
    def predicate(role_text: str | None) -> bool:
        return any(category in categories for category in classify_role(role_text))

    return predicate


@dataclass(frozen=True)
class CandidateMode:
    name: str
    description: str
    is_eligible: Callable[[str | None], bool]


CANDIDATE_MODES: tuple[CandidateMode, ...] = (
    CandidateMode(
        name="behind_the_glass",
        description="Shared producer/engineering credit (role_taxonomy PRODUCTION/ENGINEERING)",
        is_eligible=_taxonomy_category_predicate(
            frozenset({RoleCategory.PRODUCTION, RoleCategory.ENGINEERING})
        ),
    ),
    CandidateMode(
        name="rhythm_section",
        description="Shared drums or bass credit",
        is_eligible=_fine_grained_role_predicate(_RHYTHM_SECTION_TOKENS),
    ),
    CandidateMode(
        name="guitar_paths",
        description="Shared guitar credit",
        is_eligible=_fine_grained_role_predicate(_GUITAR_TOKENS),
    ),
)


def _index_album_eligible_artists(
    graph: CreditGraph,
    albums: list[dict[str, Any]],
    is_eligible: Callable[[str | None], bool],
) -> dict[str, set[int]]:
    release_ids = [int(a["main_release_id"]) for a in albums]
    grouped = graph.credit_rows_for_releases(release_ids)
    by_release: dict[int, dict[str, Any]] = {int(a["main_release_id"]): a for a in albums}
    result: dict[str, set[int]] = {}
    for release_id, rows in grouped.items():
        album = by_release[release_id]
        result[album["id"]] = {row["artist_id"] for row in rows if is_eligible(row["role_text"])}
    return result


def measure_candidates(
    graph: CreditGraph, albums: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """One-hop candidate count per mode: album pairs sharing at least one
    eligible artist under that mode's predicate. Two-hop candidate count:
    album pairs with no direct one-hop link but connected via one bridging
    album that one-hop-links to each. Real, measured against whichever
    dataset `graph` is open on -- callers decide the real catalog scope."""
    report: dict[str, dict[str, Any]] = {}
    for mode in CANDIDATE_MODES:
        eligible_by_album = _index_album_eligible_artists(graph, albums, mode.is_eligible)
        album_ids = list(eligible_by_album)

        one_hop_pairs: set[tuple[str, str]] = set()
        for a, b in combinations(album_ids, 2):
            if eligible_by_album[a] & eligible_by_album[b]:
                one_hop_pairs.add((a, b))

        one_hop_endpoint_ids: set[str] = set()
        for a, b in one_hop_pairs:
            one_hop_endpoint_ids.add(a)
            one_hop_endpoint_ids.add(b)

        two_hop_pairs = 0
        for a, b in combinations(album_ids, 2):
            if (a, b) in one_hop_pairs:
                continue
            for bridge in album_ids:
                if bridge in (a, b):
                    continue
                if (
                    eligible_by_album[a] & eligible_by_album[bridge]
                    and eligible_by_album[bridge] & eligible_by_album[b]
                ):
                    two_hop_pairs += 1
                    break

        report[mode.name] = {
            "description": mode.description,
            "albums_with_at_least_one_eligible_credit": sum(
                1 for ids in eligible_by_album.values() if ids
            ),
            "one_hop_candidate_pairs": len(one_hop_pairs),
            "one_hop_endpoint_album_count": len(one_hop_endpoint_ids),
            "two_hop_candidate_pairs": two_hop_pairs,
        }
    return report
