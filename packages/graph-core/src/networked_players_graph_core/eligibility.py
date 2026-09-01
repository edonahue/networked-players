"""Fail-closed instrument/vocal performer-role allowlist.

`is_performer_role`/`is_performer_role_sql` answer one question: "does this
specific credit row's role text show that a person sang or played an
instrument (or otherwise directly performed)". Fail-closed in the OPPOSITE
direction from `graph.py`'s `credit_edges` denylist (`_NON_COLLABORATIVE_ROLE_TOKENS`
/ `_edge_ineligible_role_sql`): an unrecognized or `NULL` role_text here means
EXCLUDED, not included. A bare release-artist billing has no role text at
all and does not by itself prove someone sang or played -- only an explicit,
recognized instrument/vocal role text does.

**ADR 0068 supersedes ADR 0039's "must never be imported by `graph.py`,
`challenge.py`, or the cohort pipeline" restriction.** That restriction
existed to keep the flagship game's narrower question from silently
narrowing the album/cohort surfaces' broader "did these two people plausibly
share a recording session" question. The owner's own product decision
(2026-09-01, ADR 0068) is that the public graph should now ask the SAME
narrower question this module already answered for game rounds. ADR 0068's
own follow-on implementation PR will have `graph.py`'s `credit_edges_sql` and
`pathfinding_graph.py`'s `edge_eligible_membership_artist_ids` import this
module directly (applied only to `track_credit`/`release_credit`-scope rows;
`track_artist`/`release_artist`-scope billing will remain implicitly
performer-qualifying at those call sites without needing this predicate at
all -- see ADR 0068). **As of this module's current state, `graph.py` and
`pathfinding_graph.py` do NOT yet import it** -- this PR only lifts ADR
0039's restriction and expands the token set; the graph-construction cutover
is deliberately deferred to keep this PR reviewable independently (ADR
0068's Consequences section states this explicitly). This module's own file
location, token set, and NULL-excluded behavior are otherwise unchanged by
the ADR 0068 decision; it is not a new, second definition, just one whose
authorized callers are about to widen. `role_taxonomy.py` remains
presentation-only per ADR 0047 and does not import from here for gating
purposes.
"""

from __future__ import annotations

import re

# Explicit instrument/vocal role tokens, lowercase, matched after the same
# bracket-stripping normalization `graph.py` uses for its denylist (a
# bracketed qualifier such as "Guitar [12-String]" must still match "guitar").
# Starting narrow is deliberate: expand this set only by adding tokens after
# reviewing real unmatched role strings (see the CLI's --dump-unmatched-roles
# diagnostic), never by relaxing the default-excluded posture.
#
# ADR 0068 audit (2026-09-01): real exact-string counts against the full
# public one-hop corpus (local/processed/discogs-v3-full, 220M credit rows)
# for every token added below, run before this module became the graph's
# canonical performer predicate. Kept token-by-token, not blanket, per this
# module's own stated revisit discipline. Explicitly considered and EXCLUDED
# (kept fail-closed) after the same review, with reasoning:
# - "Conductor" (1,119,397) / "Orchestrated By" (114,331) -- directing or
#   arranging a performance is not itself performing; role_taxonomy.py
#   already buckets both under ARRANGEMENT, not a performance category.
# - "Programming" (123) / the much larger "Programmed By" (already excluded)
#   -- a production/engineering process, not a real-time performance act.
# - "Sampler" (11,871) -- ambiguous between "played the sampler as an
#   instrument" and "sampled other people's recordings" (a rework/production
#   technique); real corpus text alone can't disambiguate, so it stays
#   excluded rather than guessed.
# - "Cover" (253,766, 98% release-scope) -- overwhelmingly a truncated
#   packaging credit (cover art/design), not a performance.
# - "Leader" (76,602) -- too generic across contexts (band-leader vs.
#   directorial) to safely assume performance.
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
        # Voice, range-qualified (ADR 0068 audit: soprano 229,273 / tenor
        # 194,549 / alto 53,625 / baritone 88,876 / bass vocals 107,351 --
        # unambiguous singing credits the original token list simply lacked).
        "soprano vocals",
        "tenor vocals",
        "alto vocals",
        "baritone vocals",
        "bass vocals",
        # Voice, other real explicit performance credits (ADR 0068 audit):
        # "human beatbox" (3,718) and "whistling" (4,672) are themselves the
        # performance; "featuring" (3,221,801 -- the single largest addition
        # in this audit) is Discogs' standard guest-performer billing --
        # real co-occurrence data shows it used interchangeably with "Rap"/
        # "Vocals" (e.g. "Vocals, Featuring" 7,318 rows; "Rap [Featuring]"
        # 51,438 rows), confirming its real-world meaning is guest
        # performance, not mere name-checking.
        "human beatbox",
        "whistling",
        "featuring",
        # Ensemble / generic self-declared performance (ADR 0068 audit):
        # "performer" (999,112), "musician" (220,705), and "instruments"
        # (47,705) are vague about WHICH instrument/voice but are themselves
        # explicit, self-declared performance claims in the source credit --
        # not an inference from outside the credit. "Orchestra" (1,116,885)
        # and generic "Strings" (309,116) are real collective-performance
        # credits (the ensemble itself performed), distinct from "Conductor"
        # (excluded above) or the specific instrument tokens already listed.
        # "Soloist" (118,061, 85% track-scoped) explicitly means a featured
        # solo performance.
        "performer",
        "musician",
        "instruments",
        "orchestra",
        "strings",
        "soloist",
        # Turntablism (ADR 0068 audit: turntables 12,800 / scratches 97,466)
        # -- playing a turntable as an instrument is a real, physical,
        # skill-based musical performance, not a production process.
        "turntables",
        "scratches",
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
        # Fretted / plucked / bowed strings, additional real instruments
        # (ADR 0068 audit, each individually confirmed real and unambiguous
        # against the corpus): "concertmaster" (32,339, the orchestra's lead
        # violinist -- a performing role, not directorial), "zither" (5,255),
        # "dulcimer" (4,996), "bouzouki" (17,043), "kora" (2,911),
        # "autoharp" (4,872), "dobro" (24,596).
        "concertmaster",
        "zither",
        "dulcimer",
        "bouzouki",
        "kora",
        "autoharp",
        "dobro",
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
        # Percussion / keys, additional real instruments (ADR 0068 audit):
        # "tambourine" (41,907), "cowbell" (5,395), "steel drums" (6,424) --
        # percussion; "theremin" (4,628), "moog" (11), "mellotron" (12,573),
        # "clavinet" (17,483), "rhodes" (43), "wurlitzer" (30), "vocoder"
        # (4,220), "talk box" (3) -- electronic/keyboard instruments, each
        # played live as part of a recorded performance.
        "tambourine",
        "cowbell",
        "steel drums",
        "theremin",
        "moog",
        "mellotron",
        "clavinet",
        "rhodes",
        "wurlitzer",
        "vocoder",
        "talk box",
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
        # Woodwind / breath-performed, additional real instruments (ADR 0068
        # audit): "recorder" (22,951) is a real woodwind instrument;
        # "didgeridoo" (5,588) is a real wind instrument, the closest
        # existing category to it; "whistle" (8,208), "melodica" (5,965),
        # and "kazoo" (2,330) are each a real, played instrument or breath
        # performance, not an inference from context.
        "recorder",
        "didgeridoo",
        "whistle",
        "melodica",
        "kazoo",
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
# presentational text, never branched on). Every token in
# `_PERFORMER_ROLE_TOKENS` has an entry here (enforced by
# `test_every_performer_token_has_exactly_one_role_category`); a genuinely
# generic/ensemble token added in the ADR 0068 audit ("performer", "musician",
# "instruments", "orchestra", "featuring", "soloist", "turntables",
# "scratches", "whistle", "vocoder", "talk box") is explicitly mapped to the
# same generic `"performer"` label `performer_role_category`'s own fallback
# already uses for a non-eligible role -- there is no more specific real
# category to give it without guessing at an instrument the credit itself
# doesn't name.
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
    "soprano vocals": "vocals",
    "tenor vocals": "vocals",
    "alto vocals": "vocals",
    "baritone vocals": "vocals",
    "bass vocals": "vocals",
    "human beatbox": "vocals",
    "whistling": "vocals",
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
    "strings": "strings",
    "concertmaster": "violin",
    "zither": "strings",
    "dulcimer": "strings",
    "bouzouki": "strings",
    "kora": "strings",
    "autoharp": "strings",
    "dobro": "guitar",
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
    "tambourine": "percussion",
    "cowbell": "percussion",
    "steel drums": "percussion",
    "theremin": "keys",
    "moog": "keys",
    "mellotron": "keys",
    "clavinet": "keys",
    "rhodes": "keys",
    "wurlitzer": "keys",
    "melodica": "keys",
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
    "recorder": "woodwind",
    "didgeridoo": "woodwind",
    "kazoo": "woodwind",
    # Generic / ensemble / other (ADR 0068 audit) -- no more specific real
    # category exists for these without guessing at an instrument the credit
    # itself doesn't name.
    "performer": "performer",
    "musician": "performer",
    "instruments": "performer",
    "orchestra": "performer",
    "featuring": "performer",
    "soloist": "performer",
    "turntables": "performer",
    "scratches": "performer",
    "whistle": "performer",
    "vocoder": "performer",
    "talk box": "performer",
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
