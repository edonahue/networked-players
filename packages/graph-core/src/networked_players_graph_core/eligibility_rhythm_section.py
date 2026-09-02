"""Fail-closed drums/bass eligibility for the "Rhythm Section" role-aware
experience (Phase 2 follow-up slice, ADR 0053 addendum).

Layered the same way the retired `eligibility_engineering.py` layered
Behind the Glass (ADR 0053, retired by ADR 0068):
a standalone, scoped module answering one narrow question -- "is this
specific credit a drums or bass contribution" -- never imported by
`graph.py`/`challenge.py`/the cohort pipeline. Unlike
`eligibility_engineering.py`, this wraps `eligibility.py`'s fine-grained
`_ROLE_CATEGORY_BY_TOKEN` display-category tokens rather than
`role_taxonomy.classify_role` -- `role_taxonomy.py`'s coarse
PERCUSSION_KEYS bucket bundles drums together with keys/organ/percussion,
too broad for an instrument-specific mode. This is the same distinction
`role_mode_candidates.py` already draws between its two candidate-mode
predicate shapes.

Real measurement (`role_mode_candidates.py`, ADR 0053) found this mode
cleared ADR 0043's launch-floor precedent (>=50 one-hop / >=20 two-hop)
against the real 140-album catalog: 170 one-hop / 455 two-hop candidate
pairs.
"""

from __future__ import annotations

from .eligibility import _ROLE_CATEGORY_BY_TOKEN

# eligibility.py's own display-category values for drums/bass tokens.
# "percussion" is a separate display category and deliberately excluded --
# matching role_mode_candidates.py's _RHYTHM_SECTION_TOKENS.
_RHYTHM_SECTION_CATEGORIES = frozenset({"drums", "bass"})


def is_rhythm_section_role(role_text: str | None) -> bool:
    """True when at least one comma-separated component of `role_text` is a
    drums or bass credit (any variant -- "Bass Guitar", "Double Bass",
    etc). Fail-closed: `None`/unrecognized text is excluded, the same
    default direction every other scoped eligibility module in this
    package uses."""
    if not role_text:
        return False
    for component in role_text.split(","):
        stripped = component.strip().lower().split("[")[0].strip()
        if _ROLE_CATEGORY_BY_TOKEN.get(stripped) in _RHYTHM_SECTION_CATEGORIES:
            return True
    return False
