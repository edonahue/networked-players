"""One per-credit answer to "is this a performing credit?" (ADR 0075).

`is_performing_credit(credit)` takes one `album_credit_membership` credit dict
(`role_text`, `credit_scope`, ...) and returns a bool; `classify_performing_credit`
returns the same verdict plus the `basis` that decided it, for audits.

It is built ON the existing ADR 0068 rule, never beside it:

1. `graph.edge_ineligible_role` is the entry gate -- quotation roles
   (`Performer [Sample]`) and all-denylisted role text (`Written-By`, `Design`)
   are never performing, whatever the scope.
2. Billing scope (`release_artist`/`track_artist`) is performing, including a
   bare `NULL` role -- the same rule `pathfinding_graph.
   edge_eligible_membership_artist_ids` applies.
3. A `track_credit`/`release_credit` component whose bracket-stripped text is
   an `eligibility._PERFORMER_ROLE_TOKENS` token is performing.
4. Only a component the project's token sets do NOT recognize at all (neither
   a performer token, nor any `role_taxonomy` category, nor one of ADR 0068's
   deliberately excluded strings) falls through to a regex heuristic ported
   from the duet-lab "Crate Constellation" prototype. A component NP already
   classifies as production/engineering/arrangement/... is never rescued by
   the regex.

So this predicate is (almost) a SUPERSET of the graph's canonical per-credit
rule: everything `credit_edges_sql`/`edge_eligible_membership_artist_ids`
counts as performing is performing here, and the regex can only add
unrecognized instrument/vocal strings ("Singer", "Harmony Vocals", "Pedal Steel
Guitar"). The one exception is a canonical false positive caused by splitting
inside brackets (`Arranged By [Rhythm, Synthesizer, Vocals]` -> the fragment
` Synthesizer` matches; see below), which this module correctly rejects. It is
NOT consumed by `graph.py`, `pathfinding_graph.py`, or any published-artifact
builder: the graph's ADR 0068 gate stays the fail-closed token allowlist. A
regex hit here is a candidate for that allowlist (review it with
`classify-roles`), not a silent widening of the public graph.

Two parsing differences from `eligibility.is_performer_role`, both deliberate:

- Commas inside brackets do not split (`Electric Piano [Fender Rhodes,
  Wurlitzer]` is one component). `is_performer_role` splits on every comma, so
  its first fragment `electric piano [fender rhodes` keeps an unclosed bracket
  and fails to match the `electric piano` token (a missed performance), while
  `Arranged By [Rhythm, Synthesizer, Vocals]` yields a bare `synthesizer`
  fragment (a false performance).
- Brackets are stripped non-greedily per bracket pair.

Judgment calls (recorded in ADR 0075): `Arranged By`, `Conductor`,
`Orchestrated By`, `Programmed By`/`Programming`/`Drum Programming`,
`Sampler`, `Cover`, and `Leader` are not performing even when the same person
may also have played -- the credit text does not say they did; a separate
instrument credit on the same release is what counts.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from .eligibility import _PERFORMER_ROLE_TOKENS, is_performer_role
from .graph import edge_ineligible_role
from .role_taxonomy import _TOKEN_CATEGORY, RoleCategory

BILLING_SCOPES = frozenset({"release_artist", "track_artist"})

Basis = Literal[
    "billing",  # release_artist/track_artist scope
    "allowlist",  # an eligibility.py performer token
    "regex_fallback",  # an unrecognized component matched the heuristic
    "ineligible_role",  # graph.edge_ineligible_role (denylist or quotation)
    "no_role",  # credit-scope row with NULL/empty role text
    "not_performing",  # every component known-non-performing or unmatched
]

# ADR 0068's audit explicitly considered and EXCLUDED these from the performer
# allowlist (see eligibility.py's `_PERFORMER_ROLE_TOKENS` comment). They are
# UNKNOWN to role_taxonomy, so without this set the regex fallback would
# quietly overturn a measured decision ("sampler" matches the instrument regex).
_DELIBERATELY_EXCLUDED = frozenset(
    {
        "conductor",
        "orchestrated by",
        "programming",
        "programmed by",
        "drum programming",
        "sampler",
        "cover",
        "leader",
        "arranged by",
    }
)

# Ported from the duet-lab prototype. Matched against a bracket-stripped
# component the token sets above did not recognize. Additions beyond the
# prototype are marked; `sampler` and `drum machine` are removed from the
# prototype's PERFORMING list (sampler: ADR 0068 exclusion; drum machine:
# the same programming-vs-performing call as "Programmed By").
_NON_PERFORMING_PATTERN = re.compile(
    r"produc|engineer|mix|master|lacquer|cut by|remaster|design|photo|art direction|artwork|"
    r"layout|liner|notes|written|composed|lyrics|songwriter|music by|words by|arranged|"
    r"orchestrated|conductor|copyist|management|a&r|executive|coordinator|legal|booking|"
    r"publish|copyright|phonographic|manufactured|distributed|recorded by|edited|programm|"
    r"technician|tech\b|assistant|supervised|compiled|transferred|illustration|painting|"
    r"cover|sleeve|translated|other\b|directed|film|video|crew|contractor|label|"
    # additions: business/packaging strings seen as UNKNOWN in the catalog
    r"licens|organi[sz]ed|calligraph|graphic|concept|promotion|commissioned|"
    r"score|sampl|drum machine",
    re.IGNORECASE,
)
_PERFORMING_PATTERN = re.compile(
    r"vocal|voice|\bsing|choir|chorus|guitar|bass|drum|percussion|piano|keyboard|\borgan\b|synth|"
    r"moog|mellotron|clavinet|rhodes|harpsichord|saxophone|sax\b|trumpet|trombone|horn|flute|"
    r"clarinet|oboe|bassoon|harmonica|violin|viola|cello|fiddle|strings|banjo|mandolin|ukulele|"
    r"sitar|harp\b|pedal steel|dobro|lap steel|tabla|conga|bongo|tambourine|timbales|vibraphone|"
    r"marimba|glockenspiel|xylophone|accordion|whistl|scratch|turntables|\brap\b|didgeridoo|"
    r"steel drums|cowbell|handclaps|performer|soloist|instruments|electronics|theremin|"
    r"bouzouki|tuba|flugelhorn|cornet|celesta|autoharp|kalimba|backing band",
    re.IGNORECASE,
)

_COMPONENT_SPLIT = re.compile(r",\s*(?![^\[]*\])")
_BRACKETED = re.compile(r"\[[^\]]*\]")


@dataclass(frozen=True)
class PerformerVerdict:
    performing: bool
    basis: Basis
    # The normalized component that decided a performing verdict, if any.
    matched_component: str | None = None


def role_components(role_text: str) -> list[str]:
    """Bracket-aware split + bracket strip + lowercase: `"Bass [Fretless],
    Producer"` -> `["bass", "producer"]`. Commas inside `[...]` do not split."""
    parts = []
    for part in _COMPONENT_SPLIT.split(role_text):
        base = _BRACKETED.sub("", part).strip().lower()
        if base:
            parts.append(base)
    return parts


def regex_component_is_performing(component: str) -> bool:
    """The prototype's per-component heuristic, on a normalized component."""
    return bool(_PERFORMING_PATTERN.search(component)) and not _NON_PERFORMING_PATTERN.search(
        component
    )


def _known_to_np(component: str) -> bool:
    category = _TOKEN_CATEGORY.get(component, RoleCategory.UNKNOWN)
    return category is not RoleCategory.UNKNOWN or component in _DELIBERATELY_EXCLUDED


def classify_performing_credit(credit: Mapping[str, Any]) -> PerformerVerdict:
    """See module docstring for the ordered rule."""
    raw_role = credit.get("role_text")
    role_text = raw_role if isinstance(raw_role, str) else None
    scope = str(credit.get("credit_scope") or "")

    if edge_ineligible_role(role_text):
        return PerformerVerdict(False, "ineligible_role")
    if scope in BILLING_SCOPES:
        return PerformerVerdict(True, "billing")
    if not role_text or not role_text.strip():
        return PerformerVerdict(False, "no_role")

    components = role_components(role_text)
    for component in components:
        if component in _PERFORMER_ROLE_TOKENS:
            return PerformerVerdict(True, "allowlist", component)
    for component in components:
        if not _known_to_np(component) and regex_component_is_performing(component):
            return PerformerVerdict(True, "regex_fallback", component)
    return PerformerVerdict(False, "not_performing")


def is_performing_credit(credit: Mapping[str, Any]) -> bool:
    """True when this one credit row documents a performance. See module
    docstring; a strict superset of the graph's ADR 0068 per-credit rule."""
    return classify_performing_credit(credit).performing


def canonical_performing_credit(credit: Mapping[str, Any]) -> bool:
    """The graph's existing ADR 0068 per-credit rule, verbatim from
    `pathfinding_graph.edge_eligible_membership_artist_ids` -- exposed only so
    the agreement report can compare against it."""
    raw_role = credit.get("role_text")
    role_text = raw_role if isinstance(raw_role, str) else None
    scope = str(credit.get("credit_scope") or "")
    return not edge_ineligible_role(role_text) and (
        scope in BILLING_SCOPES or is_performer_role(role_text)
    )


def prototype_performing_credit(credit: Mapping[str, Any]) -> bool:
    """The duet-lab prototype's rule, unmodified, for the agreement report:
    billing scope is always performing; otherwise any component matching its
    original PERFORMING and not NON_PERFORMING regex."""
    if credit.get("credit_scope") in BILLING_SCOPES:
        return True
    role_text = credit.get("role_text") or ""
    if not role_text:
        return False
    return any(
        _PROTOTYPE_PERFORMING.search(base) and not _PROTOTYPE_NON_PERFORMING.search(base)
        for base in (
            re.sub(r"\[.*?\]", "", part).strip() for part in _COMPONENT_SPLIT.split(role_text)
        )
    )


_PROTOTYPE_NON_PERFORMING = re.compile(
    r"produc|engineer|mix|master|lacquer|cut by|remaster|design|photo|art direction|artwork|"
    r"layout|liner|notes|written|composed|lyrics|songwriter|music by|words by|arranged|"
    r"orchestrated|conductor|copyist|management|a&r|executive|coordinator|legal|booking|"
    r"publish|copyright|phonographic|manufactured|distributed|recorded by|edited|programmed|"
    r"technician|tech\b|assistant|supervised|compiled|transferred|illustration|painting|"
    r"cover|sleeve|translated|other\b|directed|film|video|crew|contractor|label",
    re.IGNORECASE,
)
_PROTOTYPE_PERFORMING = re.compile(
    _PERFORMING_PATTERN.pattern + r"|drum machine|sampler", re.IGNORECASE
)


def agreement_report(
    memberships: Iterable[Mapping[str, Any]], *, sample_limit: int = 40
) -> dict[str, Any]:
    """Count performing credits under the canonical (ADR 0068), prototype and
    combined rules over `album_credit_membership` albums, and list distinct
    `(role_text, credit_scope)` pairs where canonical and prototype disagree,
    most frequent first."""
    totals: Counter[str] = Counter()
    disagreements: Counter[tuple[str | None, str, bool, bool, bool]] = Counter()
    for album in memberships:
        for credit in album.get("credits", []):
            totals["credits"] += 1
            canonical = canonical_performing_credit(credit)
            prototype = prototype_performing_credit(credit)
            combined = is_performing_credit(credit)
            totals["canonical"] += canonical
            totals["prototype"] += prototype
            totals["combined"] += combined
            totals["canonical_and_prototype"] += canonical and prototype
            if canonical != prototype:
                key = (
                    credit.get("role_text"),
                    str(credit.get("credit_scope") or ""),
                    canonical,
                    prototype,
                    combined,
                )
                disagreements[key] += 1
    return {
        "totals": dict(totals),
        "distinct_disagreements": len(disagreements),
        "disagreement_rows": sum(disagreements.values()),
        "disagreements": [
            {
                "role_text": role_text,
                "credit_scope": scope,
                "canonical": canonical,
                "prototype": prototype,
                "combined": combined,
                "count": count,
            }
            for (role_text, scope, canonical, prototype, combined), count in (
                disagreements.most_common(sample_limit)
            )
        ],
    }
