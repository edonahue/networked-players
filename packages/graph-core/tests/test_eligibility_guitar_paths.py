from __future__ import annotations

from networked_players_graph_core.eligibility_guitar_paths import is_guitar_role


def test_recognizes_real_guitar_variants() -> None:
    for role in (
        "Guitar",
        "Acoustic Guitar",
        "Electric Guitar",
        "Lead Guitar",
        "Rhythm Guitar",
        "Slide Guitar",
        "Steel Guitar",
        "Pedal Steel",
        "Guitar [12-String]",
    ):
        assert is_guitar_role(role) is True


def test_excludes_bass_and_unrelated_roles() -> None:
    for role in ("Bass", "Vocals", "Drums"):
        assert is_guitar_role(role) is False


def test_matches_a_qualifying_component_among_several() -> None:
    assert is_guitar_role("Vocals, Guitar") is True


def test_is_fail_closed_for_none_and_empty() -> None:
    assert is_guitar_role(None) is False
    assert is_guitar_role("") is False
