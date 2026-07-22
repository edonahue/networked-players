"""Candidate discovery, scoring, and diversified selection for the game-rounds pool.

Builds on `rounds.py`'s per-round evidence construction (`build_round_hop`,
`build_round_from_path`) -- this module is the "many candidate pairs" layer.
It discovers one-hop and two-hop candidates across a bounded album universe
via `CreditGraph.neighbors_batch` (one batched query, not O(n^2) separate
`find_path` BFS calls), scores them deterministically, and greedily selects
a diversified pool under repetition caps. Fully deterministic given a fixed
graph snapshot, album list, exclusion artifact, and format policy -- no
randomness, no live re-scoring after publication.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .challenge import MatchedAlbum
from .graph import CreditGraph, EvidencePath, Hop
from .rounds import build_round_from_path

# A bridge candidate's own neighbor-set can be very large for a hub artist;
# trying only the first few (by artist_id, for determinism) is enough to find
# one that clears the performer-eligibility and format gates without turning
# a hub-heavy pair into an unbounded search.
_MAX_BRIDGE_ATTEMPTS = 8
_MAX_DISTRACTORS = 3


@dataclass(frozen=True, slots=True)
class _Candidate:
    path: EvidencePath
    round_json: dict[str, Any]


def _candidate_release_ids(
    albums_by_artist: dict[int, MatchedAlbum],
    neighbors: dict[int, dict[int, tuple[int, ...]]],
) -> set[int]:
    """Every release_id `_one_hop_candidates`/`_two_hop_candidates` might need
    evidence rows for, computed purely from the already-fetched `neighbors`
    batch (no DB access, matches their pair-selection loops but doesn't stop
    at the first working bridge). Lets the caller prefetch all of it in one
    query instead of one per candidate hop -- see
    `CreditGraph.credit_rows_for_release_batch`."""
    backbone_ids = sorted(albums_by_artist)
    release_ids: set[int] = set()
    for artist_a_id in backbone_ids:
        for artist_b_id, releases in neighbors[artist_a_id].items():
            if artist_b_id in albums_by_artist and artist_b_id != artist_a_id:
                release_ids.add(releases[0])
    for i, artist_a_id in enumerate(backbone_ids):
        for artist_c_id in backbone_ids[i + 1 :]:
            bridge_ids = sorted(set(neighbors[artist_a_id]) & set(neighbors[artist_c_id]))
            for bridge_id in bridge_ids[:_MAX_BRIDGE_ATTEMPTS]:
                if bridge_id in (artist_a_id, artist_c_id):
                    continue
                release_ids.add(neighbors[artist_a_id][bridge_id][0])
                release_ids.add(neighbors[artist_c_id][bridge_id][0])
    return release_ids


def _one_hop_candidates(
    graph: CreditGraph,
    albums_by_artist: dict[int, MatchedAlbum],
    neighbors: dict[int, dict[int, tuple[int, ...]]],
    *,
    is_family_excluded: Callable[[int, int], bool] | None,
    credit_rows_by_release: Mapping[int, list[dict[str, Any]]] | None = None,
) -> tuple[list[_Candidate], set[tuple[int, int]]]:
    backbone_ids = set(albums_by_artist)
    seen_pairs: set[tuple[int, int]] = set()
    candidates: list[_Candidate] = []
    for artist_a_id in sorted(backbone_ids):
        for artist_b_id, _releases in sorted(neighbors[artist_a_id].items()):
            if artist_b_id not in backbone_ids or artist_b_id == artist_a_id:
                continue
            pair = (min(artist_a_id, artist_b_id), max(artist_a_id, artist_b_id))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            if is_family_excluded is not None and is_family_excluded(*pair):
                continue
            path = EvidencePath(
                from_artist_id=pair[0],
                to_artist_id=pair[1],
                hops=(
                    Hop(
                        release_id=neighbors[pair[0]][pair[1]][0],
                        artist_a_id=pair[0],
                        artist_b_id=pair[1],
                    ),
                ),
            )
            round_json = build_round_from_path(
                graph,
                path,
                round_id="pending",
                from_album_id=albums_by_artist[pair[0]].album_id,
                to_album_id=albums_by_artist[pair[1]].album_id,
                credit_rows_by_release=credit_rows_by_release,
            )
            if round_json is not None:
                candidates.append(_Candidate(path=path, round_json=round_json))
    return candidates, seen_pairs


def _two_hop_candidates(
    graph: CreditGraph,
    albums_by_artist: dict[int, MatchedAlbum],
    neighbors: dict[int, dict[int, tuple[int, ...]]],
    one_hop_pairs: set[tuple[int, int]],
    *,
    is_family_excluded: Callable[[int, int], bool] | None,
    allowed_release_ids: frozenset[int] | None,
    credit_rows_by_release: Mapping[int, list[dict[str, Any]]] | None = None,
) -> list[_Candidate]:
    backbone_ids = sorted(albums_by_artist)
    candidates: list[_Candidate] = []
    for i, artist_a_id in enumerate(backbone_ids):
        for artist_c_id in backbone_ids[i + 1 :]:
            pair = (artist_a_id, artist_c_id)
            if pair in one_hop_pairs:
                continue
            if is_family_excluded is not None and is_family_excluded(*pair):
                continue
            bridge_ids = sorted(set(neighbors[artist_a_id]) & set(neighbors[artist_c_id]))
            for bridge_id in bridge_ids[:_MAX_BRIDGE_ATTEMPTS]:
                if bridge_id in (artist_a_id, artist_c_id):
                    continue
                release_a = neighbors[artist_a_id][bridge_id][0]
                release_c = neighbors[artist_c_id][bridge_id][0]
                if allowed_release_ids is not None and (
                    release_a not in allowed_release_ids or release_c not in allowed_release_ids
                ):
                    continue
                path = EvidencePath(
                    from_artist_id=artist_a_id,
                    to_artist_id=artist_c_id,
                    hops=(
                        Hop(release_id=release_a, artist_a_id=artist_a_id, artist_b_id=bridge_id),
                        Hop(release_id=release_c, artist_a_id=bridge_id, artist_b_id=artist_c_id),
                    ),
                )
                round_json = build_round_from_path(
                    graph,
                    path,
                    round_id="pending",
                    from_album_id=albums_by_artist[artist_a_id].album_id,
                    to_album_id=albums_by_artist[artist_c_id].album_id,
                    credit_rows_by_release=credit_rows_by_release,
                )
                if round_json is not None:
                    # First working bridge only, in deterministic (sorted)
                    # order -- the "unique, deliberately unambiguous middle"
                    # requirement, resolved by a fixed tie-break rather than
                    # rejecting every pair with more than one possible bridge.
                    candidates.append(_Candidate(path=path, round_json=round_json))
                    break
    return candidates


def _score(
    candidate: _Candidate, endpoint_uses: dict[int, int], bridge_uses: dict[int, int]
) -> float:
    strength_flags = {flag for hop in candidate.round_json["hops"] for flag in hop["quality_flags"]}
    evidence_quality = 1.0 if "co_billed_release_artists" in strength_flags else 0.7
    path_intelligibility = 1.0 if candidate.round_json["kind"] == "one_hop" else 0.6
    from_id = candidate.path.from_artist_id
    to_id = candidate.path.to_artist_id
    endpoint_penalty = 1.0 / (1 + endpoint_uses.get(from_id, 0) + endpoint_uses.get(to_id, 0))
    bridge_penalty = 1.0
    if len(candidate.path.hops) == 2:
        bridge_id = candidate.path.hops[0].artist_b_id
        bridge_penalty = 1.0 / (1 + bridge_uses.get(bridge_id, 0))
    return evidence_quality * path_intelligibility * endpoint_penalty * bridge_penalty


def _select_diversified(
    candidates: list[_Candidate],
    *,
    target: int,
    max_endpoint_uses: int,
    max_bridge_uses: int,
) -> list[_Candidate]:
    """Greedy, deterministic: re-score after every acceptance (repetition
    penalties depend on what's already selected), stable tie-break by
    (from_artist_id, to_artist_id) so ordering never depends on input order."""
    remaining = sorted(candidates, key=lambda c: (c.path.from_artist_id, c.path.to_artist_id))
    endpoint_uses: dict[int, int] = {}
    bridge_uses: dict[int, int] = {}
    selected: list[_Candidate] = []

    while remaining and len(selected) < target:
        best = max(
            remaining,
            key=lambda c: (
                _score(c, endpoint_uses, bridge_uses),
                -c.path.from_artist_id,
                -c.path.to_artist_id,
            ),
        )
        remaining.remove(best)
        from_id, to_id = best.path.from_artist_id, best.path.to_artist_id
        if endpoint_uses.get(from_id, 0) >= max_endpoint_uses:
            continue
        if endpoint_uses.get(to_id, 0) >= max_endpoint_uses:
            continue
        if len(best.path.hops) == 2:
            bridge_id = best.path.hops[0].artist_b_id
            if bridge_uses.get(bridge_id, 0) >= max_bridge_uses:
                continue
            bridge_uses[bridge_id] = bridge_uses.get(bridge_id, 0) + 1
        endpoint_uses[from_id] = endpoint_uses.get(from_id, 0) + 1
        endpoint_uses[to_id] = endpoint_uses.get(to_id, 0) + 1
        selected.append(best)
    return selected


def _distractors(
    album: MatchedAlbum,
    other_album: MatchedAlbum,
    all_albums: list[MatchedAlbum],
    connected_pairs: set[tuple[int, int]],
) -> list[dict[str, str]]:
    distractors: list[dict[str, str]] = []
    for candidate_album in sorted(all_albums, key=lambda a: a.album_id):
        if len(distractors) >= _MAX_DISTRACTORS:
            break
        if candidate_album.artist_id in (album.artist_id, other_album.artist_id):
            continue
        pair = (
            min(album.artist_id, candidate_album.artist_id),
            max(album.artist_id, candidate_album.artist_id),
        )
        if pair in connected_pairs:
            continue
        distractors.append({"album_id": candidate_album.album_id, "reason": "no_known_path"})
    return distractors


def generate_round_pool(
    graph: CreditGraph,
    matched_albums: list[MatchedAlbum],
    *,
    one_hop_target: int,
    two_hop_target: int,
    is_family_excluded: Callable[[int, int], bool] | None = None,
    allowed_release_ids: frozenset[int] | None = None,
    max_endpoint_share: float = 0.15,
    max_bridge_share: float = 0.2,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Discover, score, and select a diversified real-evidence round pool.

    `allowed_release_ids`, when given, additionally gates every two-hop
    round's bridge evidence (both hop releases) by the studio-album-v1
    policy -- the "hidden middle record" requirement -- on top of the
    endpoint albums already being format-gated by `match_albums`. One-hop
    evidence is not separately format-gated: it is proof of a shared credit
    between two already-gated albums, not a middle record shown as its own
    thing.

    Never pads past what real candidates support -- returns the real
    achieved counts in the diagnostics dict, not the requested targets.
    """
    albums_by_artist = {m.artist_id: m for m in matched_albums}
    neighbors = graph.neighbors_batch(list(albums_by_artist))
    credit_rows_by_release = graph.credit_rows_for_release_batch(
        sorted(_candidate_release_ids(albums_by_artist, neighbors))
    )

    one_hop_candidates, one_hop_pairs = _one_hop_candidates(
        graph,
        albums_by_artist,
        neighbors,
        is_family_excluded=is_family_excluded,
        credit_rows_by_release=credit_rows_by_release,
    )
    two_hop_candidates = _two_hop_candidates(
        graph,
        albums_by_artist,
        neighbors,
        one_hop_pairs,
        is_family_excluded=is_family_excluded,
        allowed_release_ids=allowed_release_ids,
        credit_rows_by_release=credit_rows_by_release,
    )

    max_endpoint_uses = max(1, int(len(matched_albums) * max_endpoint_share))
    max_bridge_uses = max(1, int(len(matched_albums) * max_bridge_share))

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

    connected_pairs = one_hop_pairs | {
        (
            min(c.path.from_artist_id, c.path.to_artist_id),
            max(c.path.from_artist_id, c.path.to_artist_id),
        )
        for c in two_hop_candidates
    }

    rounds_json: list[dict[str, Any]] = []
    for index, candidate in enumerate(selected_one_hop + selected_two_hop, start=1):
        round_json = dict(candidate.round_json)
        round_json["id"] = f"round-{index:06d}"
        from_album = albums_by_artist[candidate.path.from_artist_id]
        to_album = albums_by_artist[candidate.path.to_artist_id]
        round_json["distractors"] = _distractors(
            from_album, to_album, matched_albums, connected_pairs
        )
        rounds_json.append(round_json)

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
    return rounds_json, diagnostics
