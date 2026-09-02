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

That exception used to be real: `eligibility_engineering.py` (the "Behind
the Glass" mode, ADR 0053) turned PRODUCTION/ENGINEERING membership
directly into gameplay eligibility, so a token edit here changed real
gameplay. Both that module and the mode were RETIRED with ADR 0068's
performer-gated cutover -- a graph in which no edge has producer/engineer
credits on both sides cannot satisfy that mode -- so this module is once
again purely presentational. Rhythm Section/Guitar Paths are
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
be imported by" prohibition -- itself since superseded by ADR 0068 for
`graph.py`/`challenge.py`/the cohort pipeline directly -- never applied to it
in the first place). This module remains presentation-only per ADR 0047
regardless: `graph.py`'s new performer gate (ADR 0068) imports
`eligibility.py` directly, never this module's `RoleCategory`/`classify_role`.
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
    # Added 2026-09-01 (ADR 0068 real-corpus audit): a real, measured-at-scale
    # performance credit that doesn't name a specific instrument or vocal
    # range -- "Performer" (999,112), "Musician" (220,705), "Orchestra"
    # (1,116,885), "Featuring" (3,221,801), "Soloist" (118,061), and similar.
    # Deliberately its own category rather than UNKNOWN (we know it IS a
    # documented performance, just not which kind) or a forced fit into
    # VOCALS/STRINGS/PERCUSSION_KEYS/BRASS_WOODWIND (which would fabricate an
    # instrument the credit itself doesn't name).
    PERFORMANCE = "performance"
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
    RoleCategory.PERFORMANCE: True,
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
    "performer": RoleCategory.PERFORMANCE,
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
# A secondary signal, never a reclassification: these three stay
# RoleCategory.ENGINEERING like every other token above. This is the
# specific, narrow subset of "pure post-production technical" work the
# owner asked to de-prioritize on core/default pages (2026-08-31): a
# mastering, recording, or mixing credit is real, but -- unlike Producer or
# a generic Engineer credit, which imply broader creative/session
# involvement -- it's also the credit type most likely to be an engineer's
# later, unrelated reissue/remaster work with no real period overlap with
# the other credited artist. Deliberately does NOT include "engineer"
# (too broad/ambiguous a token to single out), "programmed by", or
# "drum programming" (electronic-sequencing work, a different concern).
_BACKGROUND_ENGINEERING_TOKENS = frozenset(
    {
        "mastered by",
        "recorded by",
        "mixed by",
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
# `graph.py`'s denylist too. "Featuring" (2,375, formerly the single largest
# non-empty UNKNOWN string) is UNKNOWN no longer: ADR 0068 (2026-09-01) added
# it to `eligibility.py`'s `_PERFORMER_ROLE_TOKENS` after a real-corpus
# review concluded it reliably co-occurs with an explicit vocal/rap credit,
# so `classify_role("Featuring")` now returns `RoleCategory.PERFORMANCE` via
# `_PERFORMANCE_SUBCATEGORY`'s generic fallback, the same as "Performer" or
# "Musician". The film/video-production strings this note previously
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


#: Splits on a comma only when it's NOT inside a `[...]` qualifier -- a
#: plain `role_text.split(",")` (the convention `_classify_component`'s
#: caller `classify_role` uses elsewhere in this module) breaks on a real,
#: committed credit like "Recorded By [Le Mobile, Los Angeles]", whose
#: qualifier itself contains a comma: naively splitting first yields
#: "Recorded By [Le Mobile" and " Los Angeles]", neither of which has a
#: balanced bracket for the later `re.sub(r"\[.*\]", "", ...)` strip to
#: remove, so neither normalizes to a known token and the credit silently
#: fails to classify as background-engineering (a real false negative
#: caught in review, since this predicate -- unlike `classify_role` -- is
#: new code with no other established convention to match). Deliberately
#: scoped to this function only, not the shared `_classify_component`
#: path `classify_role` and every other caller of it still use, to avoid
#: widening this fix into `classify_role`'s much broader, already-
#: published blast radius (every contributor's `role_categories`) as part
#: of a background-engineering-specific change.
_ROLE_COMPONENT_SPLIT = re.compile(r",\s*(?![^\[]*\])")


def is_background_engineering_role(role_text: str | None) -> bool:
    """True when at least one comma-separated component of `role_text` is a
    background-engineering token (Mastered By / Recorded By / Mixed By) and
    every OTHER component is non-substantive (PACKAGING_BUSINESS/UNKNOWN via
    `_classify_component` -- a real, non-substantive companion credit like
    "Lacquer Cut By" alongside "Mastered By" on the same credit string must
    not negate the background verdict, even though "Lacquer Cut By" isn't
    ITSELF one of the three narrow background tokens; a round-9 review
    finding against real committed data, release 35780023 artist 520370:
    "Mastered By [Mastering], Lacquer Cut By [Lacquer Cutting]"). A
    genuinely substantive companion (Producer, Engineer, a performer role,
    ...) still disqualifies the whole credit -- this is not a blanket "any
    background component wins" rule, matching the existing pinned "Producer,
    Mastered By" -> False case. A secondary display/ranking signal, never a
    change to `classify_role`'s own ENGINEERING classification or to
    `graph.py`'s edge eligibility. `None`/empty and a role text with no
    background component at all (nothing to background) are both `False` --
    fail-closed, the same default `is_performer_role` uses."""
    if not role_text:
        return False
    saw_background = False
    for component in _ROLE_COMPONENT_SPLIT.split(role_text):
        if re.sub(r"\[.*\]", "", component).strip().lower() in _BACKGROUND_ENGINEERING_TOKENS:
            saw_background = True
            continue
        if _classify_component(component) not in (
            RoleCategory.PACKAGING_BUSINESS,
            RoleCategory.UNKNOWN,
        ):
            return False
    return saw_background


def is_background_only_role_profile(role_texts: Counter[str]) -> bool:
    """True when EVERY distinct role_text a contributor has ever been
    credited with -- the full observed vocabulary, never `role_text_examples`'
    frequency-capped top-`_MAX_ROLE_TEXT_EXAMPLES` display sample -- is either
    background-engineering or non-substantive (PACKAGING_BUSINESS, UNKNOWN,
    or ENGINEERING when the specific credit is itself background-only).

    Deliberately takes the full `Counter[str]` a builder already has on hand
    (`contributor_index.py`'s `role_texts[artist_id]`), not the published,
    capped `role_text_examples` sample: a contributor with 5+ distinct
    background-engineering credits and one rarer substantive credit (e.g. a
    single "Producer" hop) would have that credit silently truncated from
    the display sample, causing a false-positive "background-only" verdict
    if inferred from the sample alone -- a real gap caught in review, the
    same class of issue `_ROLE_COMPONENT_SPLIT` above already fixed once for
    a different reason. False for a profile with no engineering credit at
    all (nothing to background) or any credit classifying into a substantive
    category (vocals, production, composition, ...).

    Classifies every role_text bracket-aware, PER COMPONENT, the same way
    `is_background_engineering_role` does -- never by handing a whole
    role_text to `classify_role`, which splits on a bare comma before
    bracket-stripping. A real, committed credit -- "Engineer [Multi-channel
    Master Eq, Balance, Preparation]" (round 11) -- has TWO commas inside
    its bracket qualifier; `classify_role`'s naive split mis-splits it into
    unbalanced-bracket fragments that both classify as UNKNOWN, silently
    hiding the real, substantive ENGINEERING credit and letting a
    contributor whose only other credit is background be wrongly judged
    background-only. An earlier version of this function called
    `is_background_engineering_role(role_text)` first and fell back to
    whole-string `classify_role(role_text)` only when that returned False
    -- exactly the path this bracket-comma credit took, since it isn't
    purely background either. A single bracket-aware per-component loop
    avoids ever reintroducing that class of gap by construction."""
    saw_engineering = False
    for role_text in role_texts:
        for component in _ROLE_COMPONENT_SPLIT.split(role_text):
            normalized = re.sub(r"\[.*\]", "", component).strip().lower()
            if normalized in _BACKGROUND_ENGINEERING_TOKENS:
                saw_engineering = True
                continue
            if _classify_component(component) not in (
                RoleCategory.PACKAGING_BUSINESS,
                RoleCategory.UNKNOWN,
            ):
                return False
    return saw_engineering


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
