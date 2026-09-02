"""Fail-closed guitar eligibility for the "Guitar Paths" role-aware
experience (Phase 2 follow-up slice, ADR 0053 addendum).

Layered the same way `eligibility_rhythm_section.py`
layer their own scoped questions: a standalone module answering "is this
specific credit a guitar contribution" -- never imported by `graph.py`/
`challenge.py`/the cohort pipeline. Wraps `eligibility.py`'s fine-grained
`_ROLE_CATEGORY_BY_TOKEN` display-category tokens (not `role_taxonomy.
classify_role`) for the same reason `eligibility_rhythm_section.py` does --
`role_taxonomy.py`'s coarse STRINGS bucket bundles guitar together with
bass/banjo/violin/harp, too broad for an instrument-specific mode.

Real measurement (`role_mode_candidates.py`, ADR 0053) found this mode
cleared ADR 0043's launch-floor precedent (>=50 one-hop / >=20 two-hop)
against the real 140-album catalog: 109 one-hop / 196 two-hop candidate
pairs.
"""

from __future__ import annotations

from .eligibility import _ROLE_CATEGORY_BY_TOKEN

_GUITAR_CATEGORY = "guitar"


def is_guitar_role(role_text: str | None) -> bool:
    """True when at least one comma-separated component of `role_text` is a
    guitar credit (any variant -- "Acoustic Guitar", "Slide Guitar", etc).
    Fail-closed: `None`/unrecognized text is excluded, the same default
    direction every other scoped eligibility module in this package uses."""
    if not role_text:
        return False
    for component in role_text.split(","):
        stripped = component.strip().lower().split("[")[0].strip()
        if _ROLE_CATEGORY_BY_TOKEN.get(stripped) == _GUITAR_CATEGORY:
            return True
    return False
