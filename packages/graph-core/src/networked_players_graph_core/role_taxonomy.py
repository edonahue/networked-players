"""A bounded, reviewable classification of Discogs role text by *kind* of
contribution -- vocals, strings, engineering, composition, and so on.

This is a THIRD, orthogonal layer, independent of the other two role-related
modules in this package:

- `graph.py`'s `_NON_COLLABORATIVE_ROLE_TOKENS` / `edge_ineligible_role` is a
  DENYLIST answering "does this role justify a collaboration edge at all" --
  broad, permissive by default (an unrecognized role stays edge-eligible).
- `eligibility.py`'s `_PERFORMER_ROLE_TOKENS` / `is_performer_role` is a
  narrower ALLOWLIST answering "did this specific person sing or play an
  instrument" -- fail-closed (an unrecognized role is excluded), used only by
  game-round candidate generation.

This module answers a different question: "what KIND of contribution is
this" -- for display and filtering (contributor pages, the network explorer,
role-aware game modes). Every `RoleCategory` carries a `traversable` flag in
`CATEGORY_TRAVERSABLE`, but that flag is a READ of `graph.py`'s existing
denylist behavior re-expressed for display -- it must never become a new
gate. Classifying a role here does not change whether it creates a
`credit_edges` row or whether it counts as a performer credit for the
flagship game; it only labels it.

Real, live exception to "it only labels it": `eligibility_engineering.py`
(the "Behind the Glass" role-aware game mode, ADR 0053) is a thin wrapper
over `classify_role` that turns PRODUCTION/ENGINEERING category membership
directly into gameplay eligibility -- and `apps/web/src/game/roleTaxonomy.ts`
independently hand-mirrors that same token set for the live client-side
pathfinding UI. **Adding or removing a PRODUCTION/ENGINEERING/ARRANGEMENT
token here changes real Behind-the-Glass eligibility and must be mirrored
in both `eligibility_engineering.py`'s own tests and `roleTaxonomy.ts`
(kept in sync by inspection, checked by `apps/web/tests/
game-roletaxonomy.spec.ts`'s pinned-value parity cases) -- it is not a
display-only change for that one mode.** Rhythm Section/Guitar Paths are
unaffected -- they use `eligibility.py`'s separate, finer-grained token map
instead of this module.

`UNKNOWN` is an explicit, first-class category. A role that doesn't match any
known token is UNKNOWN, never silently folded into an adjacent category --
`docs/discogs-data/one-hop-hub-artists.md` observed 3,115 distinct role-text
variants from just 20 artists, so this taxonomy will always be incomplete,
and pretending otherwise would be worse than saying so plainly.

Extend the token sets only after reviewing real unmatched role strings via
the `classify-roles` CLI diagnostic (`corpus_coverage_report`) -- never by
guessing, and never by relaxing UNKNOWN as the honest default for anything
unrecognized.

This module may import from both `graph.py` and `eligibility.py` (it is a new
consumer, not `graph.py`/`challenge.py`/cohort code, so ADR 0039's "must never
be imported by" prohibition does not apply to it).
"""

from __future__ import annotations

import re
from collections import Counter
from enum import StrEnum
from pathlib import Path

import duckdb

from .eligibility import _PERFORMER_ROLE_TOKENS, _ROLE_CATEGORY_BY_TOKEN


class RoleCategory(StrEnum):
    """A bounded, reviewable vocabulary of contribution kinds. Extend only
    after reviewing real unmatched role strings (see module docstring)."""

    VOCALS = "vocals"
    STRINGS = "strings"
    PERCUSSION_KEYS = "percussion_keys"
    BRASS_WOODWIND = "brass_woodwind"
    PRODUCTION = "production"
    ENGINEERING = "engineering"
    ARRANGEMENT = "arrangement"
    COMPOSITION = "composition"
    REWORK = "rework"
    PACKAGING_BUSINESS = "packaging_business"
    AUDIOVISUAL_PRODUCTION = "audiovisual_production"
    UNKNOWN = "unknown"


# Whether a role in this category is, by itself, treated as edge-eligible by
# `graph.py`'s `credit_edges_sql` today. This documents existing behavior; it
# is never consulted by `graph.py` or `eligibility.py` and must not become a
# new traversal gate (see module docstring).
CATEGORY_TRAVERSABLE: dict[RoleCategory, bool] = {
    RoleCategory.VOCALS: True,
    RoleCategory.STRINGS: True,
    RoleCategory.PERCUSSION_KEYS: True,
    RoleCategory.BRASS_WOODWIND: True,
    RoleCategory.PRODUCTION: True,
    RoleCategory.ENGINEERING: True,
    RoleCategory.ARRANGEMENT: True,
    RoleCategory.COMPOSITION: False,
    RoleCategory.REWORK: False,
    RoleCategory.PACKAGING_BUSINESS: False,
    RoleCategory.AUDIOVISUAL_PRODUCTION: False,
    # graph.py's denylist is permissive-by-default: an unrecognized role
    # component is NOT excluded from credit_edges. UNKNOWN documents that
    # existing default, it does not grant it.
    RoleCategory.UNKNOWN: True,
}

# One source of truth for "what does `guitar` mean" at the taxonomy's coarser
# grain: remaps eligibility.py's fine-grained display categories (already
# real, tested, and used for the game's performer chips) into this module's
# RoleCategory buckets. Every value in `_ROLE_CATEGORY_BY_TOKEN` must appear
# here -- enforced by `test_every_performance_display_category_is_mapped`.
_PERFORMANCE_SUBCATEGORY: dict[str, RoleCategory] = {
    "vocals": RoleCategory.VOCALS,
    "backing_vocals": RoleCategory.VOCALS,
    "guitar": RoleCategory.STRINGS,
    "bass": RoleCategory.STRINGS,
    "strings": RoleCategory.STRINGS,
    "violin": RoleCategory.STRINGS,
    "harp": RoleCategory.STRINGS,
    "drums": RoleCategory.PERCUSSION_KEYS,
    "percussion": RoleCategory.PERCUSSION_KEYS,
    "keys": RoleCategory.PERCUSSION_KEYS,
    "organ": RoleCategory.PERCUSSION_KEYS,
    "brass": RoleCategory.BRASS_WOODWIND,
    "trumpet": RoleCategory.BRASS_WOODWIND,
    "sax": RoleCategory.BRASS_WOODWIND,
    "woodwind": RoleCategory.BRASS_WOODWIND,
    "flute": RoleCategory.BRASS_WOODWIND,
}

# Studio/production/arrangement tokens: real strings already named in
# graph.py's own docstring ("Producer, Engineer", "Mixed By", "Mastered By",
# "Recorded By", "Arranged By" all appear there as edge-eligible-but-
# uncategorized) and in eligibility.py's ROLE_PARITY_CASES test fixtures.
# "Co-producer" is a real observed string (test_graph.py, cohort_connectivity
# .py, onehop.py, ADR 0035). "Programmed By"/"Drum Programming"/"Conductor"
# were added 2026-08-04 from the real `classify-roles` coverage report run
# against the Jamiroquai topic corpus (Phase 3 Slice G follow-up):
# "Programmed By" alone was the single largest non-empty UNKNOWN role string
# (304 occurrences), with "Programmed By [Keyboard Programming By]" and
# similar bracket-suffixed variants adding more (bracket-stripping already
# collapses those into the same base token); "Drum Programming" (14) is the
# same kind of electronic-sequencing work under a different literal string.
# "Conductor" (part of "Score [Strings], Conductor [Strings]", 94
# occurrences, plus standalone) is musical-direction work closely related to
# "Arranged By". Deliberately narrow to start -- expand only via
# `classify-roles`' unknown-role diagnostic, per the module docstring.
_PRODUCTION_TOKENS = frozenset(
    {
        "producer",
        "co-producer",
        "produced by",
    }
)
_ENGINEERING_TOKENS = frozenset(
    {
        "engineer",
        "mixed by",
        "mastered by",
        "recorded by",
        "programmed by",
        "drum programming",
    }
)
_ARRANGEMENT_TOKENS = frozenset(
    {
        "arranged by",
        "conductor",
    }
)

# graph.py's `_NON_COLLABORATIVE_ROLE_TOKENS` is reused verbatim, partitioned
# into this module's three non-traversable categories. `test_non_collaborative_
# tokens_are_fully_partitioned` asserts these three sets are disjoint and their
# union equals `_NON_COLLABORATIVE_ROLE_TOKENS` exactly, so a future addition
# to graph.py's denylist that isn't triaged here fails loudly rather than
# silently becoming UNKNOWN.
_COMPOSITION_TOKENS = frozenset(
    {
        "written-by",
        "written by",
        "composed by",
        "music by",
        "lyrics by",
        "words by",
        "songwriter",
        "song by",
        "libretto by",
    }
)
_REWORK_TOKENS = frozenset(
    {
        "remix",
        "remixed by",
        "re-edit",
        "re-edited by",
        "edit",
        "edited by",
        "dj mix",
        "mashup",
    }
)
_PACKAGING_BUSINESS_TOKENS = frozenset(
    {
        "design",
        "design concept",
        "art direction",
        "artwork",
        "artwork by",
        "layout",
        "illustration",
        "photography by",
        "photography",
        "liner notes",
        "sleeve notes",
        "a&r",
        "management",
        "translation",
        "lacquer cut by",
        "executive-producer",
        "executive producer",
        "coordinator",
        "supervised by",
        "authoring",
        "other",
    }
)
# Film/video-production credits. Added 2026-08-27 (Phase 7 preflight) together
# with the matching `graph.py` denylist entries -- see the note below, which
# anticipated exactly this set and deferred it. These are not packaging and
# not business: a cinematographer or film editor made a *film*. Calling that
# "packaging & business" on a contributor page would be wrong, so this is its
# own category rather than a stretch of an existing one. Non-traversable, like
# every other category sourced from `_NON_COLLABORATIVE_ROLE_TOKENS`.
_AUDIOVISUAL_TOKENS = frozenset(
    {
        "film director",
        "film producer",
        "film editor",
        "cinematographer",
        "camera operator",
        "director of photography",
        "film technician",
        "video director",
        "video editor",
        "lighting director",
        "creative director",
        "choreography",
        "choreographer",
    }
)

# Real, frequent role strings from the same 2026-08-04 `classify-roles` run
# that were deliberately NOT added, and why: `_COMPOSITION_TOKENS`/
# `_REWORK_TOKENS`/`_PACKAGING_BUSINESS_TOKENS` must exactly partition
# `graph.py`'s `_NON_COLLABORATIVE_ROLE_TOKENS` denylist
# (`test_non_collaborative_tokens_are_fully_partitioned`) -- adding a token
# to any of the three without also adding it to that denylist would break
# the invariant, and adding it to the denylist changes the flagship game's
# actual credit-edge traversal, a materially bigger and differently-risked
# change than a display-only classification tweak. So "Compiled By" (205),
# "Concept By" (17), "Graphic Design" (17), "Product Manager" (15),
# "Promotion" (~31 combined), "Commissioned By" (85), and "Score" (part of
# the 94-count "Score [Strings], Conductor [Strings]") all stay UNKNOWN,
# correctly, until a future change deliberately re-measures and touches
# `graph.py`'s denylist too. "Featuring" (2,375, the single largest
# non-empty UNKNOWN string) stays UNKNOWN for a different reason: it is not
# an `eligibility.py` performer token either (deliberately fail-closed
# there -- it names a billing relationship, not an instrument/vocal type),
# and this module's `_PERFORMANCE_SUBCATEGORY` only remaps categories
# `eligibility.py` already recognizes, never invents new performance
# tokens independently. The film/video-production strings this note previously
# deferred (Film Director, Director Of Photography, Film Producer, Film
# Editor, Video Editor) ARE now classified: 2026-08-27's Phase 7 preflight
# measured them on the real published graph, added them to `graph.py`'s
# denylist, and gave them the honest home this note called for --
# `RoleCategory.AUDIOVISUAL_PRODUCTION` (see `_AUDIOVISUAL_TOKENS` above).
# "Presenter" and "Interviewee" stay UNKNOWN: they are broadcast/spoken-word
# billing, not audiovisual *production*, and no measurement justified them.

# Token -> category, built once at import time. Order matters only in that a
# token must not appear in two of these source dicts (tested explicitly).
_TOKEN_CATEGORY: dict[str, RoleCategory] = {}
for _token in _PERFORMER_ROLE_TOKENS:
    _sub = _ROLE_CATEGORY_BY_TOKEN.get(_token)
    if _sub is not None and _sub in _PERFORMANCE_SUBCATEGORY:
        _TOKEN_CATEGORY[_token] = _PERFORMANCE_SUBCATEGORY[_sub]
for _token in _PRODUCTION_TOKENS:
    _TOKEN_CATEGORY[_token] = RoleCategory.PRODUCTION
for _token in _ENGINEERING_TOKENS:
    _TOKEN_CATEGORY[_token] = RoleCategory.ENGINEERING
for _token in _ARRANGEMENT_TOKENS:
    _TOKEN_CATEGORY[_token] = RoleCategory.ARRANGEMENT
for _token in _COMPOSITION_TOKENS:
    _TOKEN_CATEGORY[_token] = RoleCategory.COMPOSITION
for _token in _REWORK_TOKENS:
    _TOKEN_CATEGORY[_token] = RoleCategory.REWORK
for _token in _PACKAGING_BUSINESS_TOKENS:
    _TOKEN_CATEGORY[_token] = RoleCategory.PACKAGING_BUSINESS
for _token in _AUDIOVISUAL_TOKENS:
    _TOKEN_CATEGORY[_token] = RoleCategory.AUDIOVISUAL_PRODUCTION
del _token, _sub


def _classify_component(component: str) -> RoleCategory:
    stripped = re.sub(r"\[.*\]", "", component).strip().lower()
    return _TOKEN_CATEGORY.get(stripped, RoleCategory.UNKNOWN)


def classify_role(role_text: str | None) -> tuple[RoleCategory, ...]:
    """The distinct categories present across `role_text`'s comma-separated
    components, in first-seen order. `None`/empty and any unmatched component
    classify as `UNKNOWN` -- never dropped, never guessed into an adjacent
    category. Kept in step with the SQL by
    `test_classify_role_matches_the_sql`."""
    if not role_text:
        return (RoleCategory.UNKNOWN,)
    seen: list[RoleCategory] = []
    for component in role_text.split(","):
        category = _classify_component(component)
        if category not in seen:
            seen.append(category)
    return tuple(seen)


def primary_role_category(role_text: str | None) -> RoleCategory:
    """The first non-UNKNOWN category present, for a single display chip --
    or UNKNOWN if every component is unrecognized. Presentational only."""
    for category in classify_role(role_text):
        if category is not RoleCategory.UNKNOWN:
            return category
    return RoleCategory.UNKNOWN


def classify_role_sql(role_column: str) -> str:
    """SQL: an array of distinct category strings present in `role_column`,
    mirroring `classify_role`. Empty/NULL -> `['unknown']`. DuckDB mirror of
    the same `_TOKEN_CATEGORY` mapping, kept in step by
    `test_classify_role_matches_the_sql`."""
    case_lines = []
    for token in sorted(_TOKEN_CATEGORY):
        category = _TOKEN_CATEGORY[token]
        escaped = token.replace("'", "''")
        case_lines.append(f"WHEN normalized = '{escaped}' THEN '{category.value}'")
    case_sql = "\n                        ".join(case_lines)
    unknown = RoleCategory.UNKNOWN.value
    return f"""(
        CASE
            WHEN {role_column} IS NULL OR trim({role_column}) = ''
                THEN ['{unknown}']
            ELSE list_distinct(
                list_transform(
                    list_transform(
                        str_split({role_column}, ','),
                        x -> lower(trim(regexp_replace(x, '\\[.*\\]', '')))
                    ),
                    normalized -> CASE
                        {case_sql}
                        ELSE '{unknown}'
                    END
                )
            )
        END
    )"""


def corpus_coverage_report(
    connection: duckdb.DuckDBPyConnection,
    *,
    credits_relation: str = "credits",
    top_unknown: int = 50,
) -> dict[str, object]:
    """Local-only diagnostic over a one-hop or full corpus: what fraction of
    `role_text` values classify as something other than pure UNKNOWN, and the
    most frequent unmatched role strings. Never published -- this queries the
    private corpus and is a coverage report, not a build gate. Output belongs
    under `local/analysis/role-taxonomy/`, never `apps/web/public/`."""
    total = connection.execute(f"SELECT count(*) FROM {credits_relation}").fetchone()
    total_credits = int(total[0]) if total else 0

    rows = connection.execute(
        f"""
        SELECT role_text, {classify_role_sql("role_text")} AS categories
        FROM {credits_relation}
        """
    ).fetchall()

    classified = 0
    unknown_counter: Counter[str] = Counter()
    for role_text, categories in rows:
        cats = set(categories or [RoleCategory.UNKNOWN.value])
        if cats != {RoleCategory.UNKNOWN.value}:
            classified += 1
        else:
            unknown_counter[role_text if role_text is not None else ""] += 1

    classified_pct = (classified / total_credits * 100.0) if total_credits else 0.0
    return {
        "total_credits": total_credits,
        "classified_pct": round(classified_pct, 2),
        "unknown_role_text_frequency": [
            {"role_text": text, "count": count}
            for text, count in unknown_counter.most_common(top_unknown)
        ],
    }


def corpus_coverage_report_from_dataset(
    dataset_root: Path, *, top_unknown: int = 50
) -> dict[str, object]:
    """Open a normalized snapshot's `credits` table read-only (same
    `table=credits/*.parquet` glob every other CLI diagnostic uses -- see
    `discogs/validation.py::validate_dataset`) and run
    `corpus_coverage_report` over it. A thin CLI-facing wrapper; the
    reportable logic lives in `corpus_coverage_report` so it can be unit
    tested without a real dataset on disk."""
    credits_glob = str(Path(dataset_root) / "table=credits" / "*.parquet")
    connection = duckdb.connect(database=":memory:")
    try:
        connection.read_parquet(credits_glob).create_view("credits")
        return corpus_coverage_report(connection, top_unknown=top_unknown)
    finally:
        connection.close()
