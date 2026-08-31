from __future__ import annotations

import itertools
from collections import Counter

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
    is_background_engineering_role,
    is_background_only_role_profile,
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


def test_is_background_engineering_role() -> None:
    """A secondary signal, never a reclassification -- Mastered By/Recorded
    By/Mixed By still classify as RoleCategory.ENGINEERING via classify_role
    (asserted above); this is the narrower "background, de-prioritize on
    core pages" predicate the owner asked for (2026-08-31), deliberately
    excluding the generic "Engineer" token and Programmed By/Drum
    Programming (electronic sequencing, a different concern)."""
    assert is_background_engineering_role("Mastered By") is True
    assert is_background_engineering_role("Mastered By [Vinyl]") is True
    assert is_background_engineering_role("Recorded By") is True
    assert is_background_engineering_role("Mixed By") is True
    assert is_background_engineering_role("Engineer") is False
    assert is_background_engineering_role("Producer") is False
    assert is_background_engineering_role("Programmed By") is False
    assert is_background_engineering_role("Drum Programming") is False
    # A mixed credit (e.g. someone billed as both producer and mastering
    # engineer on the same release) is not background-only -- real
    # creative involvement is present too.
    assert is_background_engineering_role("Producer, Mastered By") is False
    assert is_background_engineering_role("Mastered By, Mixed By") is True
    assert is_background_engineering_role(None) is False
    assert is_background_engineering_role("") is False


def test_is_background_engineering_role_bracket_qualifier_containing_a_comma() -> None:
    """Real gap caught in review: a real, committed credit -- "Recorded By
    [Le Mobile, Los Angeles]" -- has a comma INSIDE its bracket qualifier.
    A naive `role_text.split(",")` before bracket-stripping breaks this
    into "Recorded By [Le Mobile" and " Los Angeles]", neither of which has
    a balanced bracket to strip, so neither normalizes to a known token and
    the credit silently failed to classify as background-engineering (a
    false negative that let it escape Explorer dimming, route ranking, and
    contributor-pair filtering)."""
    assert is_background_engineering_role("Recorded By [Le Mobile, Los Angeles]") is True
    # Two independently-bracketed components must still split correctly.
    assert is_background_engineering_role("Guitar [Lead], Bass [Fretless]") is False
    assert (
        is_background_engineering_role(
            "Recorded By [Le Mobile, Los Angeles], Mixed By [Abbey Road, London]"
        )
        is True
    )


def test_is_background_engineering_role_allows_a_non_substantive_companion() -> None:
    """Real gap caught in review (round 9), reproduced against the exact
    cited real committed credit -- release 35780023, artist 520370 (Stephen
    Marsh): "Mastered By [Mastering], Lacquer Cut By [Lacquer Cutting]".
    "Lacquer Cut By" is a real, non-substantive packaging/business
    companion to the background "Mastered By [Mastering]" component, not a
    genuinely substantive one like "Producer" or "Engineer" -- it must not
    negate the background verdict for the whole credit, even though it
    isn't ITSELF one of the three narrow background tokens."""
    assert (
        is_background_engineering_role("Mastered By [Mastering], Lacquer Cut By [Lacquer Cutting]")
        is True
    )
    # A genuinely substantive companion (Producer/Engineer) still
    # disqualifies the whole credit -- this isn't a blanket "any
    # background component wins" rule.
    assert is_background_engineering_role("Mastered By, Engineer") is False
    assert is_background_engineering_role("Producer, Lacquer Cut By") is False
    # A packaging-only credit with no background component at all still
    # doesn't qualify -- nothing to background.
    assert is_background_engineering_role("Lacquer Cut By") is False
    # A substantive companion OUTSIDE production/engineering (composition,
    # arrangement) still disqualifies too -- already correctly handled
    # here via `_classify_component`'s fuller taxonomy (pinned as a
    # parity case: the TS port's round-9 fix initially missed this exact
    # gap, since that file tracks only PERFORMER/PRODUCTION_AND_ENGINEERING
    # token sets, not composition/arrangement -- round-10 finding).
    assert is_background_engineering_role("Mixed By, Written-By") is False
    assert is_background_engineering_role("Mastered By, Arranged By") is False


def test_is_background_only_role_profile() -> None:
    """The full-vocabulary companion to `is_background_engineering_role` --
    published as background-only-profiles-v1 (ADR 0048/0060 addendum),
    computed from a contributor's whole `role_texts` Counter, never the
    published, frequency-capped `role_text_examples` sample."""
    assert is_background_only_role_profile(Counter({"Mastered By": 3})) is True
    assert is_background_only_role_profile(Counter({"Mastered By": 2, "Mixed By": 1})) is True
    # A mastering engineer's real profile routinely mixes "Mastered By"
    # variants with a related-but-distinct packaging/business token like
    # "Lacquer Cut By" -- still background-only overall.
    assert (
        is_background_only_role_profile(
            Counter({"Mastered By": 5, "Lacquer Cut By": 2, "Mastered By [Vinyl]": 1})
        )
        is True
    )
    # A real substantive credit anywhere in the vocabulary disqualifies the
    # whole profile, regardless of how rare it is relative to the
    # background credits.
    assert is_background_only_role_profile(Counter({"Mastered By": 50, "Producer": 1})) is False
    assert is_background_only_role_profile(Counter({"Producer": 3})) is False
    # No engineering credit at all -- nothing to background.
    assert is_background_only_role_profile(Counter()) is False
    assert is_background_only_role_profile(Counter({"Lacquer Cut By": 3})) is False


def test_is_background_only_role_profile_real_committed_data_regressions() -> None:
    """Real committed contributors whose profiles previously broke a
    cruder version of this check -- see role_taxonomy.py's own history and
    the TS-side isBackgroundOnlyRoleProfile this superseded."""
    # Julio Iglesias (artist 67331): most frequent credit is "Mixed By",
    # but real Vocals credits exist too -- never background-only.
    assert is_background_only_role_profile(Counter({"Mixed By": 4, "Vocals": 3})) is False
    # Mike Fraser (artist 92830): role_categories collapses to
    # {"engineering"} for his whole profile, but "Recorded By, Engineer"
    # and "Engineer" are each real, non-background engineering work.
    assert (
        is_background_only_role_profile(
            Counter({"Mixed By": 5, "Recorded By, Engineer": 3, "Engineer": 2})
        )
        is False
    )
    # Stephen Marsh (artist 520370, round-9 finding): one credit combines a
    # background component with a non-substantive packaging/business
    # companion ("Lacquer Cut By") on the same release; his only other
    # observed role is plain "Mastered By" -- still background-only.
    assert (
        is_background_only_role_profile(
            Counter(
                {
                    "Mastered By [Mastering], Lacquer Cut By [Lacquer Cutting]": 2,
                    "Mastered By": 1,
                }
            )
        )
        is True
    )


def test_is_background_only_role_profile_recognizes_a_bracket_qualified_credit() -> None:
    """Real gap caught in review (round 5): a contributor whose ONLY
    engineering evidence is a real, committed credit with a comma inside
    its bracket qualifier -- "Recorded By [Le Mobile, Los Angeles]" --
    must still be recognized as background-engineering. `classify_role()`
    splits on a bare comma before bracket-stripping, so it mis-splits this
    into two unbalanced-bracket fragments and returns UNKNOWN for both,
    never seeing RoleCategory.ENGINEERING at all -- the bracket-aware
    `is_background_engineering_role()` must be consulted directly, not
    inferred through `classify_role()`."""
    assert (
        is_background_only_role_profile(Counter({"Recorded By [Le Mobile, Los Angeles]": 3}))
        is True
    )
    # Two independently-bracketed background credits, still correctly
    # recognized together.
    assert (
        is_background_only_role_profile(
            Counter(
                {
                    "Recorded By [Le Mobile, Los Angeles]": 2,
                    "Mixed By [Abbey Road, London]": 1,
                }
            )
        )
        is True
    )


def test_is_background_only_role_profile_recognizes_a_bracket_qualified_substantive() -> None:
    """Real gap caught in review (round 11), reproduced against the exact
    cited real committed credit -- release 822191, artist 263514 (Peter
    Mew): "Engineer [Multi-channel Master Eq, Balance, Preparation]". This
    is genuinely substantive generic-engineering work (not background-only),
    but its bracket qualifier contains TWO commas -- the fallback branch's
    `classify_role(role_text)` call used the same naive, non-bracket-aware
    split `is_background_engineering_role` was fixed for in round 5, so it
    mis-split this into unbalanced-bracket fragments that both classified
    as UNKNOWN, silently hiding the real ENGINEERING credit and letting a
    contributor whose ONLY other credit is "Mastered By" be wrongly judged
    background-only. Fixed by using the same bracket-aware, per-component
    classification throughout, rather than falling back to the whole-string,
    naive-split `classify_role`."""
    assert (
        is_background_only_role_profile(
            Counter(
                {
                    "Engineer [Multi-channel Master Eq, Balance, Preparation]": 1,
                    "Mastered By": 1,
                }
            )
        )
        is False
    )


def test_is_background_only_role_profile_sees_beyond_the_five_entry_display_cap() -> None:
    """Real gap caught in review (round 4): `role_text_examples` is capped
    to the five most frequent role strings. A contributor with 5+ frequent
    background-engineering credits and one rarer substantive credit could
    be misjudged background-only if inferred from that capped sample alone
    -- this function takes the full Counter instead, so a low-frequency
    "Producer" credit is never invisible just because five OTHER credits
    outrank it in frequency."""
    role_texts = Counter(
        {
            "Mastered By": 40,
            "Mastered By [Vinyl]": 30,
            "Mastered By [Cut]": 20,
            "Recorded By": 10,
            "Mixed By": 5,
            # A 6th, much rarer, genuinely substantive credit -- would be
            # truncated from a top-5-by-frequency display sample.
            "Producer": 1,
        }
    )
    assert is_background_only_role_profile(role_texts) is False


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
    # Genuinely frequent real strings deliberately left UNKNOWN (see
    # role_taxonomy.py's comment): "Featuring" is not an eligibility.py
    # performer token either, and "Compiled By" would require also
    # extending graph.py's denylist, which this module alone must not do.
    assert classify_role("Featuring") == (RoleCategory.UNKNOWN,)
    assert classify_role("Compiled By") == (RoleCategory.UNKNOWN,)


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
