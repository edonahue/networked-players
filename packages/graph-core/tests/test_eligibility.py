from __future__ import annotations

import duckdb

from networked_players_graph_core.eligibility import is_performer_role, is_performer_role_sql

# Deliberately overlaps graph.py's ROLE_PARITY_CASES so the two eligibility
# layers can be reasoned about side by side, plus cases specific to the
# allowlist's inverted default (NULL / unrecognized -> excluded).
ROLE_PARITY_CASES = [
    None,
    "",
    "Producer",
    "Producer, Engineer",
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
    "Programmed By",
    "Programmed By, Synthesizer",
    "Mixed By",
    "Mastered By",
    "Design",
    "Art Direction",
    "Executive-Producer",
    "Arranged By",
    "Composed By",
    "Remix",
    "Choir",
    "Piano, Producer",
    "Percussion [Additional]",
    "Vocals [Sample]",
]


def test_is_performer_role_matches_the_sql() -> None:
    connection = duckdb.connect()
    connection.execute("CREATE TABLE roles (role_text VARCHAR)")
    connection.executemany("INSERT INTO roles VALUES (?)", [[r] for r in ROLE_PARITY_CASES])
    sql = is_performer_role_sql("role_text")
    rows = connection.execute(f"SELECT role_text, {sql} FROM roles").fetchall()
    connection.close()

    mismatches = [
        (role, bool(sql_result), is_performer_role(role))
        for role, sql_result in rows
        if bool(sql_result) != is_performer_role(role)
    ]
    assert not mismatches, f"SQL and Python disagree on: {mismatches}"


def test_null_and_bare_billing_are_excluded_by_default() -> None:
    assert is_performer_role(None) is False
    assert is_performer_role("") is False


def test_explicit_instrument_and_vocal_roles_are_eligible() -> None:
    assert is_performer_role("Vocals") is True
    assert is_performer_role("Lead Vocals") is True
    assert is_performer_role("Guitar") is True
    assert is_performer_role("Bass Guitar") is True
    assert is_performer_role("Guitar [12-String]") is True
    assert is_performer_role("Backing Vocals [Uncredited]") is True


def test_production_and_business_roles_are_excluded() -> None:
    assert is_performer_role("Producer") is False
    assert is_performer_role("Mixed By") is False
    assert is_performer_role("Mastered By") is False
    assert is_performer_role("Design") is False
    assert is_performer_role("Executive-Producer") is False
    assert is_performer_role("Arranged By") is False
    assert is_performer_role("Composed By") is False
    assert is_performer_role("Remix") is False


def test_bare_programmer_excluded_but_qualifies_via_compound_instrument() -> None:
    assert is_performer_role("Programmed By") is False
    assert is_performer_role("Programmed By, Synthesizer") is True


def test_qualifies_via_any_eligible_component_even_with_ineligible_ones() -> None:
    assert is_performer_role("Piano, Producer") is True
    assert is_performer_role("Written-By, Producer") is False
