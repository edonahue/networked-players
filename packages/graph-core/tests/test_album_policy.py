"""Unit + Python/SQL parity tests for the master-level studio-album gate."""

from __future__ import annotations

import duckdb
import pytest

from networked_players_graph_core.album_policy import (
    master_non_studio_reason,
    master_non_studio_sql,
)

# (genres, styles, expected_non_studio)
CASES = [
    (["Stage & Screen"], ["Soundtrack", "Musical"], True),  # West Side Story
    (["Rock", "Pop"], ["Pop Rock", "Vocal"], False),  # Hot August Night (a live album,
    (["Rock"], ["Folk Rock", "Country Rock", "Blues Rock"], False),  # ...no genre signal)
    (["Rock"], ["Prog Rock", "Psychedelic Rock"], False),  # Dark Side (studio)
    (["Stage & Screen"], [], True),  # genre alone is enough
    ([], ["Score"], True),  # style alone is enough
    ([], ["Musical"], True),
    (["STAGE & SCREEN"], [], True),  # case-insensitive
    ([], ["  soundtrack  "], True),  # whitespace-tolerant
    ([], [], False),
    (None, None, False),  # nulls read as empty, not non-studio
    (["Electronic"], ["Techno"], False),
]


@pytest.mark.parametrize("genres, styles, expected", CASES)
def test_master_non_studio_reason(genres, styles, expected) -> None:
    assert (master_non_studio_reason(genres, styles) is not None) is expected


def test_reason_names_the_signal() -> None:
    reason = master_non_studio_reason(["Stage & Screen"], ["Soundtrack"])
    assert reason is not None
    assert "soundtrack" in reason and "stage & screen" in reason


@pytest.mark.parametrize("genres, styles, expected", CASES)
def test_sql_matches_python(genres, styles, expected) -> None:
    con = duckdb.connect()
    sql = master_non_studio_sql("genres", "styles")
    row = con.execute(
        f"SELECT {sql} FROM (SELECT ?::VARCHAR[] AS genres, ?::VARCHAR[] AS styles)",
        [genres, styles],
    ).fetchone()
    assert row is not None
    assert bool(row[0]) is expected
    # And the SQL agrees with the Python reference on every case.
    assert bool(row[0]) is (master_non_studio_reason(genres, styles) is not None)
