"""Real Connection Guesser round generation.

Emits `apps/web`'s `GameUniverse`/`GameRounds` contract
(`apps/web/src/game/types.ts`, `data/contracts/game-universe-v1.md`,
`data/contracts/game-rounds-v1.md`) directly, from the real credit graph.

This is a genuinely different question from `rounds.py`/`rounds_generator.py`'s
**path** semantic (album A -> artist X -> album B via a third shared release,
consumed by the separate Record Routes mode): here, a one-hop round's answer
is a performer explicitly credited on **both displayed albums directly** --
"name someone who played on both of these records" -- and a two-hop round
hides a middle album bridging two performers who each connect one endpoint to
it. `rounds.py`'s evidence-building and format/family-exclusion gates are not
reused here because the underlying discovery is structurally different (album
pairs and their shared performer sets, not artist-pair BFS paths); the
`eligibility.py` performer allowlist and the family-exclusion callable are the
two pieces of policy actually shared between both generators.

Album inputs are the canonical catalog's ID-resolved album shape
(`id`, `main_release_id`, `artist_id`, `artist`, `title`, `year`, optionally
`cover_image`) -- the same `--albums` artifact `build-challenge-from-dump`
consumes (`apps/web/public/data/catalog/albums.v1.json`,
`assemble_album_catalog`'s output). That artifact is the single source of
truth for which albums exist; this module never narrows or re-derives it
(see ADR 0038, ADR 0042, ADR 0043).
"""

from __future__ import annotations

import hashlib
import random
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .eligibility import is_performer_role, performer_role_category
from .graph import CreditGraph

GAME_SCHEMA_VERSION = 1

_MAX_DISTRACTORS = 4
_MIN_DISTRACTORS = 2
_MAX_MIDDLE_CHOICES = 4
_MAX_BRIDGE_ATTEMPTS = 8

_FORBIDDEN_SUBSTRINGS = ("/home/", "data/private", "local/", "DISCOGS_TOKEN", ".ssh")
_FORBIDDEN_PHRASES = ("worked with", "collaborated with", "influenced")


@dataclass(frozen=True, slots=True)
class _AlbumPerformers:
    album: dict[str, Any]
    # artist_id -> first eligible credit row {name, anv, role_text}, in the
    # graph's own deterministic row order (CreditGraph.credit_rows_for_releases
    # is `ORDER BY ALL`).
    performers: dict[int, dict[str, Any]]


def _index_album_performers(
    graph: CreditGraph, albums: list[dict[str, Any]]
) -> dict[str, _AlbumPerformers]:
    release_ids = [int(a["main_release_id"]) for a in albums]
    grouped = graph.credit_rows_for_releases(release_ids)
    by_release: dict[int, dict[str, Any]] = {int(a["main_release_id"]): a for a in albums}
    result: dict[str, _AlbumPerformers] = {}
    for release_id, rows in grouped.items():
        album = by_release[release_id]
        performers: dict[int, dict[str, Any]] = {}
        for row in rows:
            if not is_performer_role(row["role_text"]):
                continue
            artist_id = row["artist_id"]
            if artist_id in performers:
                continue
            performers[artist_id] = row
        result[album["id"]] = _AlbumPerformers(album=album, performers=performers)
    return result


def _shared_performers(
    a: _AlbumPerformers, b: _AlbumPerformers
) -> dict[int, tuple[dict[str, Any], dict[str, Any]]]:
    return {
        artist_id: (row, b.performers[artist_id])
        for artist_id, row in a.performers.items()
        if artist_id in b.performers
    }


def _contributor_ref(artist_id: int, row: dict[str, Any]) -> dict[str, Any]:
    """A `ContributorRef` -- `name` is always the canonical PAN-resolved
    artist name (`row["name"]`), never the release-specific ANV. Conflating
    the two would make the same real person's chip label vary round to round
    depending on which release's ANV happened to be picked; the ANV/as-
    credited spelling belongs only in `EvidenceRow.credited_as`
    (`_evidence_rows`, below)."""
    return {
        "id": int(artist_id),
        "name": row["name"],
        "role_category": performer_role_category(row["role_text"]),
    }


def _album_ref(album: dict[str, Any]) -> dict[str, Any]:
    cover = album.get("cover_image")
    art = {"kind": "hotlink", "uri150": cover["uri150"], "uri": cover["uri"]} if cover else None
    return {
        "id": album["id"],
        "title": album["title"],
        "year": album["year"],
        "act": album["artist"],
        "label": None,
        "art": art,
    }


def _initials(name: str) -> str:
    parts = [p for p in re.split(r"\s+", name.strip()) if p]
    return " ".join(f"{p[0].upper()}." for p in parts if p[0].isalpha())


def _year_text(album: dict[str, Any]) -> str:
    return str(album["year"]) if album["year"] is not None else "?"


def _evidence_rows(
    artist_id: int,
    album_a: dict[str, Any],
    row_a: dict[str, Any],
    album_c: dict[str, Any],
    row_c: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = []
    for album, row in ((album_a, row_a), (album_c, row_c)):
        rows.append(
            {
                "release_ref": album["id"],
                "release_title": album["title"],
                "contributor_id": int(artist_id),
                "credited_as": row["anv"] or row["name"],
                "role_text": row["role_text"],
                "credit_scope": row["credit_scope"],
            }
        )
    return rows


def _pick_distractors(
    endpoint_performers: list[dict[int, dict[str, Any]]],
    exclude_ids: set[int],
) -> list[dict[str, Any]]:
    """Contributor rows credited on at least one endpoint but not a shared
    answer -- proven not to satisfy the connection, not merely plausible."""
    seen: dict[int, dict[str, Any]] = {}
    for performers in endpoint_performers:
        for artist_id, row in performers.items():
            if artist_id in exclude_ids or artist_id in seen:
                continue
            seen[artist_id] = row
    return [
        {"artist_id": artist_id, "row": row}
        for artist_id, row in sorted(seen.items())[:_MAX_DISTRACTORS]
    ]


def _one_hop_difficulty(answer_count: int) -> str:
    if answer_count >= 3:
        return "easy"
    if answer_count == 2:
        return "medium"
    return "hard"


def _role_clause(count: int, category: str) -> str:
    """Honest role-clue phrasing: a bare category claim is only exclusive
    when there is exactly one valid answer for that step -- otherwise it
    would misleadingly suggest the OTHER valid answers share this role too."""
    return f"{category} work" if count == 1 else f"{category} work (among other valid answers)"


def _initials_clause(count: int, name: str) -> str:
    """Honest initials-clue phrasing, mirroring `_role_clause`: naming one
    answer's initials must not read as if that answer were the only one."""
    initials = _initials(name)
    return initials if count == 1 else f"{initials} (one of several valid answers)"


def _stable_id(*parts: str) -> str:
    """Deterministic, content-derived round id: a sha256 digest of the
    round's own canonical semantic fields, joined with an unambiguous
    delimiter. Depends only on WHAT the round is, never on where it lands in
    the selected pool -- reordering or regenerating the pool around it never
    changes an unchanged round's id (see ADR 0043)."""
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()[:10]
    return f"conn-{digest}"


def _seeded_shuffle(items: list[dict[str, Any]], seed_text: str) -> None:
    """In-place shuffle seeded by a round's own stable id -- deterministic
    across regenerations, never insertion order or wall-clock randomness."""
    seed_int = int.from_bytes(hashlib.sha256(seed_text.encode()).digest()[:8], "big")
    random.Random(seed_int).shuffle(items)


@dataclass(slots=True)
class _RoundCandidate:
    kind: str
    album_a_id: str
    album_c_id: str
    round_json: dict[str, Any]
    endpoint_ids: tuple[str, str]
    bridge_ids: frozenset[int] = field(default_factory=frozenset)


def _build_one_hop_round(
    idx: dict[str, _AlbumPerformers],
    album_a_id: str,
    album_c_id: str,
    shared: dict[int, tuple[dict[str, Any], dict[str, Any]]],
) -> _RoundCandidate | None:
    perf_a, perf_c = idx[album_a_id], idx[album_c_id]
    album_a, album_c = perf_a.album, perf_c.album
    answer_ids = sorted(shared)
    distractor_rows = _pick_distractors([perf_a.performers, perf_c.performers], set(answer_ids))
    if len(distractor_rows) < _MIN_DISTRACTORS:
        return None
    primary_id = answer_ids[0]
    row_a_primary, _row_c_primary = shared[primary_id]
    primary_name = row_a_primary["anv"] or row_a_primary["name"]
    evidence = [
        row
        for artist_id in answer_ids
        for row in _evidence_rows(
            artist_id, album_a, shared[artist_id][0], album_c, shared[artist_id][1]
        )
    ]
    distractors = [_contributor_ref(d["artist_id"], d["row"]) for d in distractor_rows]
    round_id = _stable_id(
        "1h", *sorted((album_a_id, album_c_id)), ",".join(str(a) for a in answer_ids)
    )
    primary_category = performer_role_category(row_a_primary["role_text"])
    round_json = {
        "id": round_id,
        "pool": "real-records",
        "kind": "one_hop",
        "difficulty": _one_hop_difficulty(len(answer_ids)),
        "endpoints": [_album_ref(album_a), _album_ref(album_c)],
        "answer_set": [_contributor_ref(aid, shared[aid][0]) for aid in answer_ids],
        "distractors": distractors,
        "clues": [
            {
                "kind": "years",
                "text": f"The records are from {_year_text(album_a)} and {_year_text(album_c)}.",
            },
            {
                "kind": "role",
                "text": (
                    f"The connecting credit is {_role_clause(len(answer_ids), primary_category)}."
                ),
            },
            {
                "kind": "initials",
                "text": f"Their initials are {_initials_clause(len(answer_ids), primary_name)}",
            },
            {
                "kind": "credit_excerpt",
                "text": f'Liner note, {album_a["title"]}: "{row_a_primary["role_text"]} — ▮▮▮▮▮▮"',
            },
            {
                "kind": "eliminate",
                "text": "Two names struck from the tray.",
                "eliminate_ids": [d["id"] for d in distractors[:2]],
            },
        ],
        "evidence": evidence,
        "provenance_note": (
            "Real records: derived from the Discogs monthly data dump (CC0), "
            "gated to an explicit, displayable instrument or vocal credit on "
            "both records. Cover art, when present, is hotlinked from Discogs "
            "and remains presentational, not evidence."
        ),
    }
    return _RoundCandidate(
        kind="one_hop",
        album_a_id=album_a_id,
        album_c_id=album_c_id,
        round_json=round_json,
        endpoint_ids=(album_a_id, album_c_id),
    )


def _build_two_hop_round(
    idx: dict[str, _AlbumPerformers],
    album_a_id: str,
    album_c_id: str,
    middle_id: str,
    bridge_a: dict[int, tuple[dict[str, Any], dict[str, Any]]],
    bridge_c: dict[int, tuple[dict[str, Any], dict[str, Any]]],
    middle_choices: list[str],
) -> _RoundCandidate | None:
    perf_a, perf_m, perf_c = idx[album_a_id], idx[middle_id], idx[album_c_id]
    album_a, album_m, album_c = perf_a.album, perf_m.album, perf_c.album
    # Every performer who bridges each side is a valid answer for that step --
    # not just the lowest artist_id. `min()` picks a "primary" only for clue
    # text (initials/credit excerpt need one concrete example); it must never
    # gate which ids are published as answers or excluded from distractors,
    # or a real alternate bridge performer would wrongly end up as a "proven
    # wrong" distractor chip (see ADR 0043).
    bridge_a_ids = sorted(bridge_a)
    bridge_c_ids = sorted(bridge_c)
    primary_a_id = bridge_a_ids[0]
    primary_c_id = bridge_c_ids[0]
    row_a1, _row_a2 = bridge_a[primary_a_id]
    row_c1, _row_c2 = bridge_c[primary_c_id]
    distractor_rows = _pick_distractors(
        [perf_a.performers, perf_m.performers, perf_c.performers],
        set(bridge_a_ids) | set(bridge_c_ids),
    )
    if len(distractor_rows) < _MIN_DISTRACTORS:
        return None
    name_a = row_a1["name"]
    name_c = row_c1["name"]
    evidence = [
        row
        for aid in bridge_a_ids
        for row in _evidence_rows(aid, album_a, bridge_a[aid][0], album_m, bridge_a[aid][1])
    ] + [
        row
        for aid in bridge_c_ids
        for row in _evidence_rows(aid, album_m, bridge_c[aid][0], album_c, bridge_c[aid][1])
    ]
    distractors = [_contributor_ref(d["artist_id"], d["row"]) for d in distractor_rows]
    round_id = _stable_id(
        "2h",
        album_a_id,
        album_c_id,
        middle_id,
        ",".join(str(i) for i in bridge_a_ids),
        ",".join(str(i) for i in bridge_c_ids),
    )
    middle_ref = _album_ref(album_m)
    choices = [middle_ref] + [
        _album_ref(idx[cid].album) for cid in middle_choices if cid != middle_id
    ]
    choices = choices[:_MAX_MIDDLE_CHOICES]
    _seeded_shuffle(choices, round_id)
    category_a = performer_role_category(row_a1["role_text"])
    category_c = performer_role_category(row_c1["role_text"])
    round_json = {
        "id": round_id,
        "pool": "real-records",
        "kind": "two_hop",
        "difficulty": "hard",
        "endpoints": [_album_ref(album_a), _album_ref(album_c)],
        "middle": {"album": middle_ref, "choices": choices},
        "answer_set": [],
        "bridge_answer_sets": [
            [_contributor_ref(aid, bridge_a[aid][0]) for aid in bridge_a_ids],
            [_contributor_ref(aid, bridge_c[aid][0]) for aid in bridge_c_ids],
        ],
        "distractors": distractors,
        "clues": [
            {
                "kind": "years",
                "text": f"The hidden middle record is from {_year_text(album_m)}.",
            },
            {
                "kind": "role",
                "text": (
                    f"One bridge is {_role_clause(len(bridge_a_ids), category_a)}; "
                    f"the other is {_role_clause(len(bridge_c_ids), category_c)}."
                ),
            },
            {
                "kind": "initials",
                "text": (
                    f"Bridge initials: {_initials_clause(len(bridge_a_ids), name_a)} and "
                    f"{_initials_clause(len(bridge_c_ids), name_c)}"
                ),
            },
            {
                "kind": "credit_excerpt",
                "text": f'Liner note, {album_a["title"]}: "{row_a1["role_text"]} — ▮▮▮▮▮▮"',
            },
            {
                "kind": "eliminate",
                "text": "Two names struck from the tray.",
                "eliminate_ids": [d["id"] for d in distractors[:2]],
            },
        ],
        "evidence": evidence,
        "provenance_note": (
            "Real records: derived from the Discogs monthly data dump (CC0), "
            "gated to an explicit, displayable instrument or vocal credit at "
            "each bridge. The hidden middle record is the only album in this "
            "launch's catalog that bridges both sides. Cover art, when "
            "present, is hotlinked from Discogs and remains presentational."
        ),
    }
    return _RoundCandidate(
        kind="two_hop",
        album_a_id=album_a_id,
        album_c_id=album_c_id,
        round_json=round_json,
        endpoint_ids=(album_a_id, album_c_id),
        bridge_ids=frozenset(bridge_a_ids) | frozenset(bridge_c_ids),
    )


def _score(
    candidate: _RoundCandidate, endpoint_uses: dict[str, int], bridge_uses: dict[int, int]
) -> float:
    kind_weight = 1.0 if candidate.kind == "one_hop" else 0.6
    a, c = candidate.endpoint_ids
    endpoint_penalty = 1.0 / (1 + endpoint_uses.get(a, 0) + endpoint_uses.get(c, 0))
    bridge_penalty = 1.0
    if candidate.bridge_ids:
        # Penalize by the MOST-used individual bridge performer, not a
        # compound pair key -- a performer who bridges many different album
        # pairs must still be capped across all of them, not just repeats of
        # the exact same pairing (see ADR 0043).
        max_use = max(bridge_uses.get(bid, 0) for bid in candidate.bridge_ids)
        bridge_penalty = 1.0 / (1 + max_use)
    return kind_weight * endpoint_penalty * bridge_penalty


def _select_diversified(
    candidates: list[_RoundCandidate], *, target: int, max_endpoint_uses: int, max_bridge_uses: int
) -> list[_RoundCandidate]:
    remaining = sorted(candidates, key=lambda c: (c.album_a_id, c.album_c_id))
    endpoint_uses: dict[str, int] = {}
    bridge_uses: dict[int, int] = {}
    selected: list[_RoundCandidate] = []
    while remaining and len(selected) < target:
        best = max(
            remaining,
            key=lambda c: (_score(c, endpoint_uses, bridge_uses), c.album_a_id, c.album_c_id),
        )
        remaining.remove(best)
        a, c = best.endpoint_ids
        if (
            endpoint_uses.get(a, 0) >= max_endpoint_uses
            or endpoint_uses.get(c, 0) >= max_endpoint_uses
        ):
            continue
        if best.bridge_ids and any(
            bridge_uses.get(bid, 0) >= max_bridge_uses for bid in best.bridge_ids
        ):
            continue
        for bid in best.bridge_ids:
            bridge_uses[bid] = bridge_uses.get(bid, 0) + 1
        endpoint_uses[a] = endpoint_uses.get(a, 0) + 1
        endpoint_uses[c] = endpoint_uses.get(c, 0) + 1
        selected.append(best)
    return selected


def generate_connection_round_pool(
    graph: CreditGraph,
    albums: list[dict[str, Any]],
    *,
    one_hop_target: int,
    two_hop_target: int,
    is_family_excluded: Callable[[int, int], bool] | None = None,
    max_endpoint_share: float = 0.15,
    max_bridge_share: float = 0.2,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, _AlbumPerformers]]:
    """Discover, score, and select a diversified real Connection Guesser pool.

    `albums` are the canonical catalog's ID-resolved dicts (real, already
    studio-gated -- see `apps/web/public/data/catalog/albums.v1.json`). Never
    pads past what real candidates support -- the diagnostics dict reports
    achieved counts, not requested targets. The third return value is the
    complete per-album eligible-performer index used for discovery; pass it
    to `build_connection_universe_and_rounds` so the published universe's
    `credits` are the same complete data the rounds were discovered from, not
    a narrower evidence-only subset (Finding 7, ADR 0043).
    """
    idx = _index_album_performers(graph, albums)
    album_ids = sorted(idx)

    one_hop_pairs: dict[tuple[str, str], dict[int, tuple[dict[str, Any], dict[str, Any]]]] = {}
    one_hop_candidates: list[_RoundCandidate] = []
    for i, a in enumerate(album_ids):
        for c in album_ids[i + 1 :]:
            if is_family_excluded is not None and is_family_excluded(
                int(idx[a].album["artist_id"]), int(idx[c].album["artist_id"])
            ):
                continue
            shared = _shared_performers(idx[a], idx[c])
            if not shared:
                continue
            one_hop_pairs[(a, c)] = shared
            candidate = _build_one_hop_round(idx, a, c, shared)
            if candidate is not None:
                one_hop_candidates.append(candidate)

    two_hop_candidates: list[_RoundCandidate] = []
    for i, a in enumerate(album_ids):
        for c in album_ids[i + 1 :]:
            if (a, c) in one_hop_pairs:
                continue
            if is_family_excluded is not None and is_family_excluded(
                int(idx[a].album["artist_id"]), int(idx[c].album["artist_id"])
            ):
                continue
            middles = []
            for m in album_ids:
                if m in (a, c):
                    continue
                key_am = (a, m) if a < m else (m, a)
                key_mc = (m, c) if m < c else (c, m)
                if key_am in one_hop_pairs and key_mc in one_hop_pairs:
                    middles.append(m)
                if len(middles) > 1:
                    break
            if len(middles) != 1:
                continue
            middle_id = middles[0]
            key_am = (a, middle_id) if a < middle_id else (middle_id, a)
            key_mc = (middle_id, c) if middle_id < c else (c, middle_id)
            middle_choice_pool = [m for m in album_ids if m not in (a, c, middle_id)][
                : _MAX_MIDDLE_CHOICES - 1
            ]
            candidate = _build_two_hop_round(
                idx,
                a,
                c,
                middle_id,
                one_hop_pairs[key_am],
                one_hop_pairs[key_mc],
                middle_choice_pool,
            )
            if candidate is not None:
                two_hop_candidates.append(candidate)

    max_endpoint_uses = max(1, int(len(albums) * max_endpoint_share))
    max_bridge_uses = max(1, int(len(albums) * max_bridge_share))
    selected_one_hop = _select_diversified(
        one_hop_candidates,
        target=one_hop_target,
        max_endpoint_uses=max_endpoint_uses,
        max_bridge_uses=max_bridge_uses,
    )
    selected_two_hop = _select_diversified(
        two_hop_candidates,
        target=two_hop_target,
        max_endpoint_uses=max_endpoint_uses,
        max_bridge_uses=max_bridge_uses,
    )

    # Round ids are content-derived at construction time (see `_stable_id`),
    # not assigned here by position -- selection order must never affect an
    # unchanged round's id. Guard the invariant this function relies on:
    # `_select_diversified` never selects the same candidate twice, but two
    # *different* candidates producing the same id would mean a real hash
    # collision or a semantic-field bug, either worth failing loudly on.
    rounds_json = [candidate.round_json for candidate in selected_one_hop + selected_two_hop]
    seen_ids = {r["id"] for r in rounds_json}
    if len(seen_ids) != len(rounds_json):
        raise ConnectionRoundsValidationError("duplicate stable round id within one generation run")

    diagnostics = {
        "one_hop_candidates_found": len(one_hop_candidates),
        "two_hop_candidates_found": len(two_hop_candidates),
        "one_hop_selected": len(selected_one_hop),
        "two_hop_selected": len(selected_two_hop),
        "one_hop_target": one_hop_target,
        "two_hop_target": two_hop_target,
        "max_endpoint_uses": max_endpoint_uses,
        "max_bridge_uses": max_bridge_uses,
    }
    return rounds_json, diagnostics, idx


def build_connection_universe_and_rounds(
    albums: list[dict[str, Any]],
    rounds_json: list[dict[str, Any]],
    performer_index: dict[str, _AlbumPerformers],
    *,
    snapshot_date: str,
    generated_by: str,
    catalog_version: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Assemble the final `GameUniverse`/`GameRounds` artifact pair. Only
    albums actually referenced by a round (endpoint or middle/choice) are
    included -- an album that matched the catalog but never became part of a
    round is not part of the game universe, mirroring `rounds.py`'s posture.

    `credits`/`contributors` are built from `performer_index` (the SAME
    complete per-album eligible-performer index the generator discovered
    rounds from, see `generate_connection_round_pool`) for every used album
    -- not narrowed to whichever credits happen to be cited as evidence for
    an already-selected round. A round's answer/bridge sets are a claim about
    this complete index (every qualifying performer, not a sample of one);
    publishing anything less would make that claim unverifiable by an
    independent consumer (see Finding 7, ADR 0043) -- exactly the trap the
    prior "subset check" against `challenge.v2.json` fell into.
    """
    used_album_ids: set[str] = set()
    for round_json in rounds_json:
        for endpoint in round_json["endpoints"]:
            used_album_ids.add(endpoint["id"])
        middle = round_json.get("middle")
        if middle:
            used_album_ids.add(middle["album"]["id"])
            for choice in middle["choices"]:
                used_album_ids.add(choice["id"])

    album_by_id = {a["id"]: a for a in albums}
    universe_albums = [
        {
            "id": a["id"],
            "title": a["title"],
            "act": a["artist"],
            "act_id": int(a["artist_id"]),
            "year": a["year"],
            "label": None,
            "art": (
                {
                    "kind": "hotlink",
                    "uri150": a["cover_image"]["uri150"],
                    "uri": a["cover_image"]["uri"],
                }
                if a.get("cover_image")
                else None
            ),
        }
        for a in sorted(album_by_id.values(), key=lambda x: x["id"])
        if a["id"] in used_album_ids
    ]

    contributors: dict[int, dict[str, Any]] = {}
    releases: dict[str, dict[str, Any]] = {}
    credits: list[dict[str, Any]] = []
    for album_id in sorted(used_album_ids):
        perf = performer_index.get(album_id)
        if perf is None:
            continue
        album = album_by_id[album_id]
        releases[album_id] = {
            "id": album_id,
            "album_id": album_id,
            "title": album["title"],
            "year": album["year"],
            "catalog_stamp": f"DISCOGS-{album['main_release_id']}",
        }
        for artist_id, row in perf.performers.items():
            # `row["name"]` is the canonical PAN-resolved name -- never the
            # ANV -- so a contributor's universe-wide display name is stable
            # regardless of which release happened to populate it first.
            contributors.setdefault(
                artist_id,
                {
                    "id": artist_id,
                    "name": row["name"],
                    "role_category": performer_role_category(row["role_text"]),
                },
            )
            credits.append(
                {
                    "release_id": album_id,
                    "contributor_id": artist_id,
                    "role_text": row["role_text"],
                    "role_category": performer_role_category(row["role_text"]),
                    "credit_scope": row["credit_scope"],
                }
            )

    pool_version = (
        f"connection-v1-{snapshot_date}-"
        + hashlib.sha256("|".join(sorted(r["id"] for r in rounds_json)).encode()).hexdigest()[:12]
    )
    provenance = {
        "source": "Discogs monthly data dump (CC0), one-hop working set",
        "license": "Derived from the Discogs monthly CC0 data dumps. See docs/DATA_AND_RIGHTS.md.",
        "snapshot_date": snapshot_date,
        "generated_by": generated_by,
        "catalog_version": catalog_version,
        "pool_version": pool_version,
        "note": (
            "Real records, not synthetic. A round's answer is a performer with "
            "an explicit, displayable instrument or vocal credit on both "
            "displayed albums directly (or, for a two-hop round, on the hidden "
            "middle album). The private collection seed used to build the "
            "working set this catalog is drawn from is never published. "
            "catalog_version identifies the canonical "
            "apps/web/public/data/catalog/albums.v1.json this pool's album set "
            "was resolved from; pool_version is a content hash of this "
            "specific round set (regenerating identical rounds from an "
            "identical catalog reproduces the same pool_version)."
        ),
    }

    universe = {
        "schema_version": GAME_SCHEMA_VERSION,
        "provenance": provenance,
        "albums": universe_albums,
        "contributors": sorted(contributors.values(), key=lambda c: c["id"]),
        "releases": sorted(releases.values(), key=lambda r: r["id"]),
        "credits": sorted(credits, key=lambda c: (c["release_id"], c["contributor_id"])),
    }
    rounds = {
        "schema_version": GAME_SCHEMA_VERSION,
        "provenance": provenance,
        "rounds": rounds_json,
    }
    return universe, rounds


class ConnectionRoundsValidationError(RuntimeError):
    """Raised when a real GameUniverse/GameRounds artifact pair violates its contract."""


_ROUND_ID_PATTERN = re.compile(r"^conn-[0-9a-f]{10}$")

_UNIVERSE_TOP_LEVEL_KEYS = frozenset(
    {"schema_version", "provenance", "albums", "contributors", "releases", "credits"}
)
_ROUNDS_TOP_LEVEL_KEYS = frozenset({"schema_version", "provenance", "rounds"})
_PROVENANCE_REQUIRED_FIELDS = (
    "source",
    "license",
    "snapshot_date",
    "generated_by",
    "note",
    "catalog_version",
    "pool_version",
)


def _find_seed_keys(obj: Any, path: str = "") -> list[str]:
    """Recursively collect dotted paths to any dict key literally named
    ``seed`` -- must agree with the dependency-free mirror in
    `networked_players_contracts.connection_rounds` (see that module's
    docstring for why this pool needs its own mirror, distinct from
    `networked_players_contracts.rounds`'s Record Routes contract)."""
    found: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            child = f"{path}.{key}" if path else str(key)
            if key == "seed":
                found.append(child)
            found.extend(_find_seed_keys(value, child))
    elif isinstance(obj, list):
        for index, item in enumerate(obj):
            found.extend(_find_seed_keys(item, f"{path}[{index}]"))
    return found


def validate_connection_rounds_artifact(universe: dict[str, Any], rounds: dict[str, Any]) -> None:
    """Generation-time validation for the Connection Guesser's real
    `GameUniverse`/`GameRounds` pair. An independent dependency-free mirror
    lives at `networked_players_contracts.connection_rounds` for Pi-fleet use
    -- if the two disagree, treat it as a bug in whichever is stricter by
    mistake. Distinct from `networked_players_contracts.rounds`, which
    validates the unrelated Record Routes path-shaped contract; both pairs
    have historically been published at the same file names
    (`universe.v1.json`/`rounds.v1.json`) in different directories, so do not
    assume "rounds.v1" alone identifies which contract applies (Finding 8/11,
    ADR 0043).
    """
    failures: list[str] = []

    if set(universe.keys()) != _UNIVERSE_TOP_LEVEL_KEYS:
        failures.append(f"universe has unexpected top-level keys: {sorted(universe.keys())}")
    if universe.get("schema_version") != GAME_SCHEMA_VERSION:
        failures.append(f"universe schema_version must be {GAME_SCHEMA_VERSION}")
    if set(rounds.keys()) != _ROUNDS_TOP_LEVEL_KEYS:
        failures.append(f"rounds has unexpected top-level keys: {sorted(rounds.keys())}")
    if rounds.get("schema_version") != GAME_SCHEMA_VERSION:
        failures.append(f"rounds schema_version must be {GAME_SCHEMA_VERSION}")
    if universe.get("provenance") != rounds.get("provenance"):
        failures.append("universe and rounds provenance must match exactly")

    album_ids = {a["id"] for a in universe.get("albums", [])}
    contributor_ids = {c["id"] for c in universe.get("contributors", [])}

    for album in universe.get("albums", []):
        if album.get("id") not in album_ids:
            failures.append(f"album {album.get('id')} missing from its own index (impossible)")

    round_ids: set[str] = set()
    for round_json in rounds.get("rounds", []):
        round_id = round_json.get("id")
        if round_id in round_ids:
            failures.append(f"duplicate round id {round_id}")
        round_ids.add(round_id)
        if not isinstance(round_id, str) or not _ROUND_ID_PATTERN.match(round_id):
            failures.append(f"round id {round_id!r} is not a stable content-derived id")
        if round_json.get("pool") != "real-records":
            failures.append(
                f"round {round_id} pool must be 'real-records', got {round_json.get('pool')!r}"
            )
        answer_set = round_json.get("answer_set", [])
        kind = round_json.get("kind")
        if kind == "one_hop" and not answer_set:
            failures.append(f"round {round_id} has an empty answer set")
        answer_ids = {a["id"] for a in answer_set}
        bridges = round_json.get("bridge_answer_sets") or []
        bridge_answer_ids: set[int] = {a["id"] for group in bridges for a in group}
        all_valid_ids = answer_ids | bridge_answer_ids
        for distractor in round_json.get("distractors", []):
            if distractor["id"] in all_valid_ids:
                failures.append(f"round {round_id} distractor {distractor['id']} is an answer")
        evidence = round_json.get("evidence", [])
        if not evidence:
            failures.append(f"round {round_id} has no evidence rows")
        for answer in answer_set:
            if not any(row["contributor_id"] == answer["id"] for row in evidence):
                failures.append(f"round {round_id} answer {answer['id']} lacks evidence")
        for group in bridges:
            for bridge_answer in group:
                if not any(row["contributor_id"] == bridge_answer["id"] for row in evidence):
                    failures.append(
                        f"round {round_id} bridge answer {bridge_answer['id']} lacks evidence"
                    )
        for clue in round_json.get("clues", []):
            if clue.get("kind") == "eliminate":
                for eliminated_id in clue.get("eliminate_ids", []):
                    if eliminated_id in all_valid_ids:
                        failures.append(
                            f"round {round_id} eliminate clue targets valid answer {eliminated_id}"
                        )
        for endpoint in round_json.get("endpoints", []):
            if endpoint["id"] not in album_ids:
                failures.append(f"round {round_id} endpoint {endpoint['id']} not in universe")
        if kind == "two_hop":
            middle = round_json.get("middle")
            if not middle or not bridges:
                failures.append(f"two-hop round {round_id} missing middle/bridge_answer_sets")
            elif not any(c["id"] == middle["album"]["id"] for c in middle["choices"]):
                failures.append(f"round {round_id} middle answer missing from its own choices")
            if not bridges or not bridges[0] or not bridges[1]:
                failures.append(f"round {round_id} must have at least one bridge answer per side")
            bridge_a_ids = {a["id"] for a in bridges[0]} if bridges else set()
            bridge_c_ids = {a["id"] for a in bridges[1]} if bridges else set()
            for distractor in round_json.get("distractors", []):
                if distractor["id"] in bridge_a_ids or distractor["id"] in bridge_c_ids:
                    failures.append(
                        f"round {round_id} distractor {distractor['id']} is a bridge answer"
                    )

    for artifact, name in ((universe, "universe"), (rounds, "rounds")):
        for seed_path in _find_seed_keys(artifact):
            failures.append(f"{name} must not have a 'seed' key ({seed_path})")
        serialized = str(artifact)
        for forbidden in _FORBIDDEN_SUBSTRINGS:
            if forbidden in serialized:
                failures.append(f"{name} contains forbidden substring: {forbidden!r}")
        lowered = serialized.lower()
        for phrase in _FORBIDDEN_PHRASES:
            if phrase in lowered:
                failures.append(f"{name} contains forbidden phrase: {phrase!r}")

    for field_name in _PROVENANCE_REQUIRED_FIELDS:
        if not universe.get("provenance", {}).get(field_name):
            failures.append(f"universe.provenance.{field_name} is required")

    source = universe.get("provenance", {}).get("source", "").lower()
    generated_by = universe.get("provenance", {}).get("generated_by", "").lower()
    if "discogs" not in source:
        failures.append("universe provenance.source does not identify a real Discogs source")
    if "synthetic" in generated_by or "ci placeholder" in generated_by:
        # The challenge.v2.json trap: a generator name that quietly marks the
        # artifact as a synthetic/CI fixture while everything else looks real.
        failures.append("universe provenance.generated_by marks this as a synthetic fixture")

    for credit in universe.get("credits", []):
        if credit.get("contributor_id") not in contributor_ids:
            failures.append(f"credit references unknown contributor {credit.get('contributor_id')}")
        if credit.get("release_id") not in {r["id"] for r in universe.get("releases", [])}:
            failures.append(f"credit references unknown release {credit.get('release_id')}")

    if failures:
        raise ConnectionRoundsValidationError("; ".join(failures))
