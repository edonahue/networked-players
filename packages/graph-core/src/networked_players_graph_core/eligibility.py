"""Fail-closed instrument/vocal performer-role allowlist for game rounds.

This is layered *on top of* `credit_edges` (`graph.py`'s
`_NON_COLLABORATIVE_ROLE_TOKENS` / `_edge_ineligible_role_sql`), not a
replacement for it. `credit_edges` is a denylist tuned to answer "did these
two people plausibly share a recording session" -- correct for the album
challenge and cohort surfaces, where a bare `Producer` or `Mixed By` credit
should keep counting as a real edge (ADR 0035).

The flagship game asks a narrower, different question: "did this specific
person sing or play an instrument on this specific credit". That rule is
deliberately fail-closed in the opposite direction from `credit_edges`: an
unrecognized or `NULL` role_text here means EXCLUDED, not included. A bare
release-artist billing does not by itself prove someone sang or played --
only an explicit, recognized instrument/vocal role text does.

This module must never be imported by `graph.py`, `challenge.py`, or the
cohort pipeline -- only by game-round candidate generation. Narrowing what
counts as a "playable identity" for the game must not silently narrow the
cohort's or album challenge's broader graph exploration.
"""

from __future__ import annotations

import re

# Explicit instrument/vocal role tokens, lowercase, matched after the same
# bracket-stripping normalization `graph.py` uses for its denylist (a
# bracketed qualifier such as "Guitar [12-String]" must still match "guitar").
# Starting narrow is deliberate: expand this set only by adding tokens after
# reviewing real unmatched role strings (see the CLI's --dump-unmatched-roles
# diagnostic), never by relaxing the default-excluded posture.
_PERFORMER_ROLE_TOKENS = frozenset(
    {
        # Voice
        "vocals",
        "lead vocals",
        "co-lead vocals",
        "backing vocals",
        "background vocals",
        "additional vocals",
        "choir",
        "chorus",
        "voice",
        "rap",
        "spoken word",
        # Fretted / plucked / bowed strings
        "guitar",
        "acoustic guitar",
        "electric guitar",
        "lead guitar",
        "rhythm guitar",
        "slide guitar",
        "steel guitar",
        "pedal steel",
        "bass",
        "bass guitar",
        "double bass",
        "upright bass",
        "banjo",
        "mandolin",
        "ukulele",
        "sitar",
        "violin",
        "viola",
        "cello",
        "fiddle",
        "harp",
        # Percussion / keys
        "drums",
        "percussion",
        "congas",
        "bongos",
        "timpani",
        "tabla",
        "piano",
        "electric piano",
        "organ",
        "hammond organ",
        "keyboards",
        "synthesizer",
        "synth",
        "accordion",
        "harpsichord",
        "celesta",
        "vibraphone",
        "marimba",
        "xylophone",
        # Brass
        "trumpet",
        "trombone",
        "tuba",
        "french horn",
        "cornet",
        "flugelhorn",
        # Woodwind
        "saxophone",
        "alto saxophone",
        "tenor saxophone",
        "baritone saxophone",
        "soprano saxophone",
        "clarinet",
        "flute",
        "piccolo",
        "oboe",
        "bassoon",
        "bagpipes",
        "harmonica",
    }
)


def is_performer_role(role_text: str | None) -> bool:
    """Python mirror of `is_performer_role_sql`: True only when at least one
    comma-separated component of `role_text` is a recognized instrument/vocal
    token. `None` (a bare release-artist credit with no role text at all) is
    always False -- unlike `graph.edge_ineligible_role`, billing is not proof
    of performance.

    Kept in step with the SQL by `test_is_performer_role_matches_the_sql`.
    """
    if role_text is None:
        return False
    for component in role_text.split(","):
        stripped = re.sub(r"\[.*\]", "", component).strip().lower()
        if stripped in _PERFORMER_ROLE_TOKENS:
            return True
    return False


# Display-only categorization of the same token set above, for the game's
# contributor chips (a short, human label like "guitar" or "vocals" -- purely
# presentational text, never branched on). Grouped exactly like
# `_PERFORMER_ROLE_TOKENS`'s comments; a token not listed here falls back to
# `"performer"`, which should never actually happen since every token in
# `_PERFORMER_ROLE_TOKENS` has an entry.
_ROLE_CATEGORY_BY_TOKEN: dict[str, str] = {
    # Voice
    "vocals": "vocals",
    "lead vocals": "vocals",
    "co-lead vocals": "vocals",
    "backing vocals": "backing_vocals",
    "background vocals": "backing_vocals",
    "additional vocals": "backing_vocals",
    "choir": "vocals",
    "chorus": "vocals",
    "voice": "vocals",
    "rap": "vocals",
    "spoken word": "vocals",
    # Fretted / plucked / bowed strings
    "guitar": "guitar",
    "acoustic guitar": "guitar",
    "electric guitar": "guitar",
    "lead guitar": "guitar",
    "rhythm guitar": "guitar",
    "slide guitar": "guitar",
    "steel guitar": "guitar",
    "pedal steel": "guitar",
    "bass": "bass",
    "bass guitar": "bass",
    "double bass": "bass",
    "upright bass": "bass",
    "banjo": "strings",
    "mandolin": "strings",
    "ukulele": "strings",
    "sitar": "strings",
    "violin": "violin",
    "viola": "strings",
    "cello": "strings",
    "fiddle": "violin",
    "harp": "harp",
    # Percussion / keys
    "drums": "drums",
    "percussion": "percussion",
    "congas": "percussion",
    "bongos": "percussion",
    "timpani": "percussion",
    "tabla": "percussion",
    "piano": "keys",
    "electric piano": "keys",
    "organ": "organ",
    "hammond organ": "organ",
    "keyboards": "keys",
    "synthesizer": "keys",
    "synth": "keys",
    "accordion": "keys",
    "harpsichord": "keys",
    "celesta": "keys",
    "vibraphone": "percussion",
    "marimba": "percussion",
    "xylophone": "percussion",
    # Brass
    "trumpet": "trumpet",
    "trombone": "brass",
    "tuba": "brass",
    "french horn": "brass",
    "cornet": "brass",
    "flugelhorn": "brass",
    # Woodwind
    "saxophone": "sax",
    "alto saxophone": "sax",
    "tenor saxophone": "sax",
    "baritone saxophone": "sax",
    "soprano saxophone": "sax",
    "clarinet": "woodwind",
    "flute": "flute",
    "piccolo": "woodwind",
    "oboe": "woodwind",
    "bassoon": "woodwind",
    "bagpipes": "woodwind",
    "harmonica": "woodwind",
}


def first_performer_component(role_text: str | None) -> str | None:
    """The first comma-separated component of `role_text` that is a recognized
    performer token, normalized (bracket-stripped, trimmed, lowercased) but not
    re-cased -- or None if `role_text` is not performer-eligible. Feeds
    `performer_role_category`."""
    if role_text is None:
        return None
    for component in role_text.split(","):
        stripped = re.sub(r"\[.*\]", "", component).strip().lower()
        if stripped in _PERFORMER_ROLE_TOKENS:
            return stripped
    return None


def performer_role_category(role_text: str | None) -> str:
    """Short display category (e.g. "guitar", "vocals") for a performer-eligible
    `role_text`. Presentational only -- see `_ROLE_CATEGORY_BY_TOKEN`. Falls back
    to `"performer"` for a non-eligible or unrecognized role_text; callers should
    only invoke this after confirming `is_performer_role(role_text)`."""
    token = first_performer_component(role_text)
    if token is None:
        return "performer"
    return _ROLE_CATEGORY_BY_TOKEN.get(token, "performer")


def is_performer_role_sql(role_column: str) -> str:
    """SQL boolean: true when at least one comma-separated component of
    `role_column` is a recognized instrument/vocal token. False for NULL.
    """
    tokens = ", ".join(f"'{token}'" for token in sorted(_PERFORMER_ROLE_TOKENS))
    return f"""(
        {role_column} IS NOT NULL
        AND list_bool_or(
            list_transform(
                str_split({role_column}, ','),
                x -> lower(trim(regexp_replace(x, '\\[.*\\]', ''))) IN ({tokens})
            )
        )
    )"""
