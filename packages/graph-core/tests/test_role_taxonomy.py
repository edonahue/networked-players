from __future__ import annotations

import itertools

import duckdb

from networked_players_graph_core.eligibility import _ROLE_CATEGORY_BY_TOKEN
from networked_players_graph_core.graph import _NON_COLLABORATIVE_ROLE_TOKENS
from networked_players_graph_core.role_taxonomy import (
    _AUDIOVISUAL_TOKENS,
    _COMPOSITION_TOKENS,
    _PACKAGING_BUSINESS_TOKENS,
    _PERFORMANCE_SUBCATEGORY,
    _REWORK_TOKENS,
    CATEGORY_TRAVERSABLE,
    RoleCategory,
    classify_role,
    classify_role_sql,
    corpus_coverage_report,
    primary_role_category,
)

# Real difficult role strings already encountered in this project: overlaps
# eligibility.py's ROLE_PARITY_CASES plus production/engineering/composition/
# rework/business tokens named in graph.py's own docstring and ADR 0035/0027.
ROLE_PARITY_CASES = [
    None,
    "",
    "Producer",
    "Producer, Engineer",
    "Co-producer",
    "Written-By",
    "Written-By, Producer",
    "Vocals",
    "Lead Vocals",
    "Backing Vocals [Uncredited]",
    "Guitar",
    "Guitar [12-String]",
    "Bass Guitar",
    "Drums",
    "Synthesizer",
    "Mixed By",
    "Mastered By",
    "Recorded By",
    "Arranged By",
    "Programmed By",
    "Programmed By [Keyboard Programming By]",
    "Drum Programming",
    "Conductor",
    "Score [Strings], Conductor [Strings]",
    "Design",
    "Art Direction",
    "Executive-Producer",
    "Composed By",
    "Remix",
    "Piano, Producer",
    "A Genuinely Novel Role String That Nobody Has Seen",
]


def test_classify_role_matches_the_sql() -> None:
    connection = duckdb.connect()
    connection.execute("CREATE TABLE roles (role_text VARCHAR)")
    connection.executemany("INSERT INTO roles VALUES (?)", [[r] for r in ROLE_PARITY_CASES])
    sql = classify_role_sql("role_text")
    rows = connection.execute(f"SELECT role_text, {sql} FROM roles").fetchall()
    connection.close()

    mismatches = []
    for role_text, sql_categories in rows:
        python_categories = {c.value for c in classify_role(role_text)}
        sql_categories_set = set(sql_categories or [])
        if python_categories != sql_categories_set:
            mismatches.append((role_text, sql_categories_set, python_categories))
    assert not mismatches, f"SQL and Python disagree on: {mismatches}"


def test_none_and_empty_role_text_is_unknown() -> None:
    assert classify_role(None) == (RoleCategory.UNKNOWN,)
    assert classify_role("") == (RoleCategory.UNKNOWN,)


def test_a_genuinely_novel_role_string_is_unknown_not_guessed() -> None:
    assert classify_role("A Genuinely Novel Role String That Nobody Has Seen") == (
        RoleCategory.UNKNOWN,
    )


def test_studio_roles_classify_distinctly_from_performer_roles() -> None:
    assert classify_role("Producer") == (RoleCategory.PRODUCTION,)
    assert classify_role("Co-producer") == (RoleCategory.PRODUCTION,)
    assert classify_role("Mixed By") == (RoleCategory.ENGINEERING,)
    assert classify_role("Mastered By") == (RoleCategory.ENGINEERING,)
    assert classify_role("Recorded By") == (RoleCategory.ENGINEERING,)
    assert classify_role("Arranged By") == (RoleCategory.ARRANGEMENT,)
    assert classify_role("Producer, Engineer") == (
        RoleCategory.PRODUCTION,
        RoleCategory.ENGINEERING,
    )


def test_real_2026_08_04_coverage_additions_classify_correctly() -> None:
    """Tokens added from the real `classify-roles` run against the
    Jamiroquai topic corpus (Phase 3 Slice G follow-up) -- see
    role_taxonomy.py's own comment for the real counts."""
    assert classify_role("Programmed By") == (RoleCategory.ENGINEERING,)
    assert classify_role("Programmed By [Keyboard Programming By]") == (RoleCategory.ENGINEERING,)
    assert classify_role("Drum Programming") == (RoleCategory.ENGINEERING,)
    assert classify_role("Conductor") == (RoleCategory.ARRANGEMENT,)
    # Bracket-stripping applies per comma-separated component: "Score
    # [Strings]" strips to the still-unrecognized "Score" (UNKNOWN, left
    # deliberately unclassified -- see role_taxonomy.py's comment on why),
    # "Conductor [Strings]" strips to the now-recognized "Conductor".
    assert classify_role("Score [Strings], Conductor [Strings]") == (
        RoleCategory.UNKNOWN,
        RoleCategory.ARRANGEMENT,
    )
    # "Compiled By" would require extending graph.py's denylist, which this
    # module alone must not do -- stays genuinely UNKNOWN.
    assert classify_role("Compiled By") == (RoleCategory.UNKNOWN,)
    # "Featuring" was reclassified 2026-09-01 (ADR 0068 real-corpus audit):
    # it is now a recognized eligibility.py performer token (real
    # co-occurrence data -- "Vocals, Featuring", "Rap [Featuring]" -- showed
    # its real-world meaning is guest performance), so it now classifies as
    # the new RoleCategory.PERFORMANCE, not UNKNOWN.
    assert classify_role("Featuring") == (RoleCategory.PERFORMANCE,)
    # Real gap caught in review (round 2): the generic "Strings" token (a
    # collective ensemble credit, ADR 0068's own stated intent -- see its
    # Decision section) must classify as PERFORMANCE, the same as "Orchestra"
    # or bare "Performer", NOT as RoleCategory.STRINGS -- that specific
    # bucket is reserved for credits naming an actual stringed instrument
    # (Guitar, Violin, Banjo, ...), which generic "Strings" does not.
    assert classify_role("Strings") == (RoleCategory.PERFORMANCE,)


def test_performer_roles_map_into_coarser_taxonomy_buckets() -> None:
    assert classify_role("Guitar") == (RoleCategory.STRINGS,)
    assert classify_role("Bass Guitar") == (RoleCategory.STRINGS,)
    assert classify_role("Vocals") == (RoleCategory.VOCALS,)
    assert classify_role("Backing Vocals [Uncredited]") == (RoleCategory.VOCALS,)
    assert classify_role("Drums") == (RoleCategory.PERCUSSION_KEYS,)


def test_composition_and_rework_and_business_are_non_traversable() -> None:
    assert classify_role("Written-By") == (RoleCategory.COMPOSITION,)
    assert classify_role("Remix") == (RoleCategory.REWORK,)
    assert classify_role("Design") == (RoleCategory.PACKAGING_BUSINESS,)
    assert classify_role("Executive-Producer") == (RoleCategory.PACKAGING_BUSINESS,)
    assert CATEGORY_TRAVERSABLE[RoleCategory.COMPOSITION] is False
    assert CATEGORY_TRAVERSABLE[RoleCategory.REWORK] is False
    assert CATEGORY_TRAVERSABLE[RoleCategory.PACKAGING_BUSINESS] is False


def test_multi_component_role_keeps_every_distinct_category() -> None:
    assert classify_role("Piano, Producer") == (
        RoleCategory.PERCUSSION_KEYS,
        RoleCategory.PRODUCTION,
    )
    assert classify_role("Written-By, Producer") == (
        RoleCategory.COMPOSITION,
        RoleCategory.PRODUCTION,
    )


def test_primary_role_category_skips_unknown_when_a_real_category_exists() -> None:
    assert primary_role_category("Producer") == RoleCategory.PRODUCTION
    assert primary_role_category("Piano, Producer") == RoleCategory.PERCUSSION_KEYS


def test_primary_role_category_is_unknown_for_a_fully_unmatched_role() -> None:
    assert primary_role_category(None) == RoleCategory.UNKNOWN
    assert primary_role_category("Some Unmatched Text") == RoleCategory.UNKNOWN


def test_every_role_category_has_a_traversable_entry() -> None:
    assert set(CATEGORY_TRAVERSABLE) == set(RoleCategory)


def test_every_performance_display_category_is_mapped() -> None:
    """Every display category eligibility.py already produces for a
    performer-eligible role must land in this taxonomy's coarser buckets --
    no fine-grained category silently falls through to UNKNOWN."""
    assert set(_ROLE_CATEGORY_BY_TOKEN.values()) <= set(_PERFORMANCE_SUBCATEGORY)


def test_non_collaborative_tokens_are_fully_partitioned() -> None:
    """graph.py's denylist tokens must be triaged into exactly one of this
    taxonomy's four non-traversable categories -- no overlaps, no gaps. A
    future addition to graph.py's denylist that isn't triaged here should
    fail this test loudly rather than silently classifying as UNKNOWN."""
    sets = {
        "composition": _COMPOSITION_TOKENS,
        "rework": _REWORK_TOKENS,
        "packaging_business": _PACKAGING_BUSINESS_TOKENS,
        "audiovisual_production": _AUDIOVISUAL_TOKENS,
    }
    for left, right in itertools.combinations(sorted(sets), 2):
        assert sets[left].isdisjoint(sets[right]), f"{left} overlaps {right}"
    union = frozenset().union(*sets.values())
    assert union == _NON_COLLABORATIVE_ROLE_TOKENS


def test_corpus_coverage_report_over_a_small_synthetic_corpus() -> None:
    connection = duckdb.connect()
    connection.execute("CREATE TABLE credits (role_text VARCHAR)")
    connection.executemany(
        "INSERT INTO credits VALUES (?)",
        [
            ["Producer"],
            ["Guitar"],
            ["Some Unmatched Text"],
            [None],
        ],
    )
    report = corpus_coverage_report(connection, top_unknown=10)
    connection.close()

    assert report["total_credits"] == 4
    assert report["classified_pct"] == 50.0
    unknown_texts = {entry["role_text"] for entry in report["unknown_role_text_frequency"]}
    assert "Some Unmatched Text" in unknown_texts
    assert "" in unknown_texts  # None normalized to "" per the report's own contract
