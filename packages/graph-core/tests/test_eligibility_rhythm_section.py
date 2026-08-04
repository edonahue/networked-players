from __future__ import annotations

from networked_players_graph_core.eligibility_rhythm_section import (
    is_rhythm_section_role,
)


def test_recognizes_real_drums_and_bass_strings() -> None:
    for role in (
        "Drums",
        "Bass",
        "Bass Guitar",
        "Double Bass",
        "Upright Bass",
        "Bass [Fretless]",
    ):
        assert is_rhythm_section_role(role) is True


def test_excludes_percussion_a_separate_display_category() -> None:
    assert is_rhythm_section_role("Percussion") is False


def test_excludes_unrelated_roles() -> None:
    for role in ("Vocals", "Guitar", "Producer"):
        assert is_rhythm_section_role(role) is False


def test_matches_a_qualifying_component_among_several() -> None:
    assert is_rhythm_section_role("Vocals, Drums") is True


def test_is_fail_closed_for_none_and_empty() -> None:
    assert is_rhythm_section_role(None) is False
    assert is_rhythm_section_role("") is False
