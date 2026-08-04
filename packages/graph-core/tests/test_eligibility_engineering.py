from __future__ import annotations

from networked_players_graph_core.eligibility_engineering import (
    is_engineering_or_production_role,
)


def test_recognizes_real_production_and_engineering_strings() -> None:
    for role in (
        "Producer",
        "Co-Producer",
        "Engineer",
        "Mixed By",
        "Mastered By",
        "Recorded By",
    ):
        assert is_engineering_or_production_role(role) is True


def test_excludes_performer_and_non_collaborative_roles() -> None:
    for role in ("Vocals", "Guitar", "Written-By", "Design"):
        assert is_engineering_or_production_role(role) is False


def test_real_2026_08_04_engineering_additions_qualify() -> None:
    """ "Programmed By"/"Drum Programming" were added to role_taxonomy.py's
    ENGINEERING tokens from a real Jamiroquai-corpus coverage run -- since
    eligibility_engineering.py is a thin wrapper over classify_role, this
    silently changed real Behind-the-Glass eligibility. Locks in that real,
    current behavior (previously untested) -- see role_taxonomy.py's module
    docstring for why this isn't merely a display-layer change."""
    for role in ("Programmed By", "Drum Programming"):
        assert is_engineering_or_production_role(role) is True


def test_conductor_does_not_qualify() -> None:
    """ "Conductor" was added to role_taxonomy.py's ARRANGEMENT tokens in the
    same real coverage run -- ARRANGEMENT is not in
    eligibility_engineering.py's PRODUCTION/ENGINEERING set, so this one
    stays excluded, unlike "Programmed By"/"Drum Programming" above."""
    assert is_engineering_or_production_role("Conductor") is False


def test_matches_a_qualifying_component_among_several() -> None:
    assert is_engineering_or_production_role("Vocals, Producer") is True


def test_is_fail_closed_for_none_and_empty() -> None:
    assert is_engineering_or_production_role(None) is False
    assert is_engineering_or_production_role("") is False


def test_is_fail_closed_for_unrecognized_text() -> None:
    assert is_engineering_or_production_role("Some Future Unknown Credit") is False
