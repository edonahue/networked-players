from __future__ import annotations

from typing import Any

import pytest

from networked_players_graph_core.performer_credit import (
    agreement_report,
    canonical_performing_credit,
    classify_performing_credit,
    is_performing_credit,
    prototype_performing_credit,
    role_components,
)


def _credit(role_text: str | None, scope: str = "track_credit") -> dict[str, Any]:
    return {"artist_id": 1, "name": "Synthetic", "role_text": role_text, "credit_scope": scope}


PERFORMING_ROLES = [
    "Bass",
    "Backing Vocals",
    "Electric Piano [Fender Rhodes]",
    "Tenor Saxophone, Clarinet",
    "Percussion",
    "Drums, Flute",
    "Guitar, Vocals, Producer",
    "Organ [Hammond]",
    "Rap",
    "Singer",
]

NON_PERFORMING_ROLES = [
    "Producer",
    "Mastered By",
    "Engineer [Assistant]",
    "Written-By",
    "Design",
    "Photography By",
    "Lacquer Cut By",
    "Arranged By [Horns]",
    "Mixed By",
    "Producer, Engineer",
    "Other [Guitar Treatments]",
    "Programmed By [Synthesizer]",
    "Licensed To",
    "Licensing",
    "Organized By",
    "Calligraphy",
    "Graphics",
]


@pytest.mark.parametrize("role_text", PERFORMING_ROLES)
@pytest.mark.parametrize("scope", ["track_credit", "release_credit"])
def test_required_performing_roles(role_text: str, scope: str) -> None:
    assert is_performing_credit(_credit(role_text, scope))


@pytest.mark.parametrize("role_text", NON_PERFORMING_ROLES)
@pytest.mark.parametrize("scope", ["track_credit", "release_credit"])
def test_required_non_performing_roles(role_text: str, scope: str) -> None:
    assert not is_performing_credit(_credit(role_text, scope))


@pytest.mark.parametrize("scope", ["release_artist", "track_artist"])
def test_billing_scope_with_null_role_is_performing(scope: str) -> None:
    verdict = classify_performing_credit(_credit(None, scope))
    assert verdict.performing
    assert verdict.basis == "billing"


def test_release_credit_with_null_role_is_not_performing() -> None:
    verdict = classify_performing_credit(_credit(None, "release_credit"))
    assert not verdict.performing
    assert verdict.basis == "no_role"
    assert not is_performing_credit(_credit("", "release_credit"))


def test_allowlist_wins_before_regex() -> None:
    verdict = classify_performing_credit(_credit("Guitar, Vocals, Producer"))
    assert verdict.basis == "allowlist"
    assert verdict.matched_component == "guitar"


def test_regex_fallback_only_for_unrecognized_components() -> None:
    singer = classify_performing_credit(_credit("Singer"))
    assert singer.basis == "regex_fallback"
    assert singer.matched_component == "singer"
    # Real unmatched-by-allowlist strings from the published catalog.
    for role in ("Harmony Vocals", "Pedal Steel Guitar", "Contrabass", "Handclaps"):
        assert classify_performing_credit(_credit(role)).basis == "regex_fallback", role


@pytest.mark.parametrize(
    "role_text",
    [
        "Conductor",
        "Orchestrated By",
        "Programming",
        "Drum Programming",
        "Drum Programming [Linn Programming]",
        "Drum Machine [Roland]",
        "Sampler",
        "Sampler [Additional Sampling], Sound Designer [Sound Design]",
        "Cover",
        "Leader",
        "Arranged By",
    ],
)
def test_adr_0068_deliberate_exclusions_are_not_rescued_by_regex(role_text: str) -> None:
    assert not is_performing_credit(_credit(role_text))


@pytest.mark.parametrize(
    "role_text",
    [
        "Performer [Sample]",
        'Performer ["Walk On By" Samples], Written-By ["Walk On By" Samples]',
        "Performer [Excerpts]",
        "Samples",
    ],
)
def test_quotation_roles_are_never_performing_even_as_billing(role_text: str) -> None:
    assert classify_performing_credit(_credit(role_text)).basis == "ineligible_role"
    assert not is_performing_credit(_credit(role_text, "track_artist"))
    # The unmodified prototype counts sampled performers; this is a deliberate fix.
    if role_text.startswith("Performer"):
        assert prototype_performing_credit(_credit(role_text))


def test_bracket_aware_split() -> None:
    assert role_components("Bass [Fretless], Producer") == ["bass", "producer"]
    assert role_components("Electric Piano [Fender Rhodes, Wurlitzer]") == ["electric piano"]
    assert role_components("Arranged By [Rhythm, Synthesizer, Vocals]") == ["arranged by"]


def test_bracket_comma_cases_where_canonical_splits_wrongly() -> None:
    missed = _credit("Synthesizer [Mini-moog, Arp]")
    assert not canonical_performing_credit(missed)
    assert is_performing_credit(missed)

    false_positive = _credit("Arranged By [Rhythm, Synthesizer, Vocals]")
    assert canonical_performing_credit(false_positive)
    assert not is_performing_credit(false_positive)


SUPERSET_CASES = [
    None,
    "",
    "Producer",
    "Bass",
    "Vocals, Written-By",
    "Featuring",
    "Musician [Additional]",
    "Concertmaster",
    "Orchestra",
    "Written-By",
    "Performer [Sample]",
    "Mixed By, Guitar [12-String]",
    "Timpani",
]


@pytest.mark.parametrize("role_text", SUPERSET_CASES)
@pytest.mark.parametrize("scope", ["track_credit", "release_credit", "release_artist"])
def test_superset_of_canonical_rule_without_bracket_commas(
    role_text: str | None, scope: str
) -> None:
    credit = _credit(role_text, scope)
    if canonical_performing_credit(credit):
        assert is_performing_credit(credit)


def test_agreement_report_counts_and_disagreements() -> None:
    albums = [
        {
            "album_id": "master-1",
            "credits": [
                _credit(None, "release_artist"),
                _credit("Bass"),
                _credit("Bass"),
                _credit("Harmony Vocals"),
                _credit("Drum Programming"),
                _credit("Featuring"),
                _credit("Producer"),
            ],
        }
    ]
    report = agreement_report(albums)
    assert report["totals"] == {
        "credits": 7,
        "canonical": 4,  # artist, bass x2, featuring
        "prototype": 5,  # artist, bass x2, harmony vocals, drum programming
        "combined": 5,  # artist, bass x2, harmony vocals, featuring
        "canonical_and_prototype": 3,
    }
    assert report["distinct_disagreements"] == 3
    rows = {row["role_text"]: row for row in report["disagreements"]}
    assert rows["Harmony Vocals"]["combined"] is True
    assert rows["Drum Programming"]["combined"] is False
    assert rows["Featuring"]["prototype"] is False
