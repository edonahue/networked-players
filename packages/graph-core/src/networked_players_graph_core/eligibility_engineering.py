"""Fail-closed engineering/production eligibility for the "Behind the Glass"
role-aware experience (Phase 2 Slice H, ADR 0053).

Layered the same way ADR 0039 layered `eligibility.py`'s performer allowlist:
a standalone, scoped module answering one narrow question -- "is this
specific credit a producer/engineer/mixer/mastering-engineer contribution"
-- never imported by `graph.py`/`challenge.py`/the cohort pipeline. Unlike
`eligibility.py`, this is a thin wrapper over `role_taxonomy.classify_role`
rather than its own hand-maintained token set -- `role_taxonomy.py` is
already the shared source of truth for PRODUCTION/ENGINEERING token
membership (ADR 0047), so this module adds no new tokens of its own.

Real measurement (`role_mode_candidates.py`, ADR 0053) found this the
best-supported role-aware candidate against the real 140-album catalog: 202
one-hop / 429 two-hop candidate pairs, with 137 of 140 albums carrying at
least one eligible credit -- comfortably above ADR 0043's launch-floor
precedent (>=50 one-hop / >=20 two-hop).
"""

from __future__ import annotations

from .role_taxonomy import RoleCategory, classify_role

_ENGINEERING_PRODUCTION_CATEGORIES = frozenset({RoleCategory.PRODUCTION, RoleCategory.ENGINEERING})


def is_engineering_or_production_role(role_text: str | None) -> bool:
    """True when at least one comma-separated component of `role_text`
    classifies as PRODUCTION or ENGINEERING (`role_taxonomy.classify_role`).
    Fail-closed: `None`/unrecognized text is excluded, the same default
    direction `eligibility.py`'s performer allowlist uses and for the same
    reason -- an unrecognized role should never silently qualify a "Behind
    the Glass" connection."""
    return any(
        category in _ENGINEERING_PRODUCTION_CATEGORIES for category in classify_role(role_text)
    )
