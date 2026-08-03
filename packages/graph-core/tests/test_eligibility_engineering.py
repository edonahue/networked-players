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


def test_matches_a_qualifying_component_among_several() -> None:
    assert is_engineering_or_production_role("Vocals, Producer") is True


def test_is_fail_closed_for_none_and_empty() -> None:
    assert is_engineering_or_production_role(None) is False
    assert is_engineering_or_production_role("") is False


def test_is_fail_closed_for_unrecognized_text() -> None:
    assert is_engineering_or_production_role("Some Future Unknown Credit") is False
