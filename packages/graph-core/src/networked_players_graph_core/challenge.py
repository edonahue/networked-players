"""Build a challenge.v2 artifact: an album-centered, evidence-preserving
static challenge derived from a real one-hop credit graph.

Albums are matched against a snapshot by exact (case-insensitive) title and
release-artist name; releases are demoted to evidence beneath the hops that
justify each connection, per docs/DATA_AND_RIGHTS.md's "derived does not
mean rights-free" -- the artifact carries only what's needed to understand
and verify the experience, plus full provenance.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from networked_players_contracts.challenge import challenge_failures

from . import __version__
from .album_policy import master_non_studio_reason
from .graph import CreditGraph, EvidencePath, FrontierTooLargeError

CHALLENGE_SCHEMA_VERSION = 2


class ChallengeValidationError(RuntimeError):
    """Raised when a challenge.v2 artifact violates its contract."""


@dataclass(slots=True)
class MatchedAlbum:
    artist_query: str
    title_query: str
    master_id: int | None
    main_release_id: int
    title: str
    artist_id: int
    artist_name: str
    year: int | None
    cover_image: dict[str, Any] | None = None

    @property
    def album_id(self) -> str:
        return f"master-{self.master_id}" if self.master_id else f"release-{self.main_release_id}"

    def to_resolved_dict(self) -> dict[str, Any]:
        """The ID-precise wire shape for an already-resolved album -- see
        `resolved_album_from_dict`. Carries `artist_id`/`main_release_id`
        directly so a downstream consumer never needs to re-resolve this
        album by matching on artist/title strings again, which for a common
        display name (or, worse, a placeholder identity like "Various") is a
        real collision risk `find_release_by_title_artist` can't rule out on
        text alone."""
        return {
            "id": self.album_id,
            "artist_id": self.artist_id,
            "artist": self.artist_name,
            "master_id": self.master_id,
            "main_release_id": self.main_release_id,
            "title": self.title,
            "year": self.year,
        }


def resolved_album_from_dict(d: dict[str, Any]) -> MatchedAlbum:
    """Reconstruct a `MatchedAlbum` from `to_resolved_dict`'s shape without
    any graph query -- the whole point being that a candidate or previously
    -matched album, once resolved to a real artist_id/release_id, never needs
    to be re-matched by name again."""
    return MatchedAlbum(
        artist_query=d["artist"],
        title_query=d["title"],
        master_id=d["master_id"],
        main_release_id=d["main_release_id"],
        title=d["title"],
        artist_id=d["artist_id"],
        artist_name=d["artist"],
        year=d["year"],
    )


def _year_from_released(released: str | None) -> int | None:
    if released and len(released) >= 4 and released[:4].isdigit():
        return int(released[:4])
    return None


def release_eligibility_reason(
    graph: CreditGraph,
    *,
    release_id: int,
    master_id: int | None,
    allowed_release_ids: frozenset[int] | None,
    master_exclusions: frozenset[int] | None,
) -> str | None:
    """`None` when a release passes the real studio-album-v1 policy;
    otherwise a short, human-readable reason it doesn't.

    Shared by `match_albums` (text-resolved editorial/candidate albums) and
    `analysis.py::assemble_album_catalog`'s pre-resolved path (albums that
    already carry a real identity -- e.g. `data/albums/editorial-seed-v1.json`
    -- and so skip `find_release_by_title_artist` entirely) so both apply
    the IDENTICAL policy, never two copies of the same rule.
    """
    if allowed_release_ids is not None and release_id not in allowed_release_ids:
        return "release not in the release-format allow-list"
    master = graph.master(master_id) if master_id is not None else None
    # Fail-closed master-level exclusion: soundtracks/stage recordings the
    # release-format gate can't see (via Discogs genre/style), plus the
    # curated human-reviewed deny-list for non-studio masters that carry no
    # structured signal at all.
    if master is not None:
        non_studio_reason = master_non_studio_reason(master["genres"], master["styles"])
        if non_studio_reason:
            return f"non-studio master: {non_studio_reason}"
    if master_exclusions and master_id in master_exclusions:
        return "curated studio-album-master-exclusions-v1 entry"
    return None


def match_albums(
    graph: CreditGraph,
    albums: list[dict[str, str]],
    *,
    allowed_release_ids: frozenset[int] | None = None,
    master_exclusions: frozenset[int] | None = None,
) -> tuple[list[MatchedAlbum], list[dict[str, str]]]:
    """Match each ``{"artist", "title"}`` query against the graph's releases.

    ``allowed_release_ids``, when given (the ``allowed_release_ids`` of a
    ``release-format-scoring-index``, see ``discogs/release_format_policy.py``),
    fail-closed gates every match -- editorial or graph-candidate alike -- by
    the same studio-album-v1 policy used for round/candidate generation. A
    query whose matched release isn't in the allow-list is treated exactly
    like an unmatched query: reported in ``missed``, never silently included.
    This is deliberately applied here, not only in the candidate-ranking SQL,
    so any caller of ``match_albums``/``build_challenge_v2`` gets the same
    guarantee even with a hand-written album list that wasn't pre-filtered.

    Returns (matched, missed) -- ``missed`` entries are the original query dicts.
    """
    matched: list[MatchedAlbum] = []
    missed: list[dict[str, str]] = []
    seen_artist_ids: set[int] = set()

    for album in albums:
        artist_query = album["artist"]
        title_query = album["title"]
        found = graph.find_release_by_title_artist(title_query, artist_query)
        if found is None or found["artist_id"] in seen_artist_ids:
            missed.append(album)
            continue
        if (
            release_eligibility_reason(
                graph,
                release_id=found["release_id"],
                master_id=found["master_id"],
                allowed_release_ids=allowed_release_ids,
                master_exclusions=master_exclusions,
            )
            is not None
        ):
            missed.append(album)
            continue
        seen_artist_ids.add(found["artist_id"])

        master = graph.master(found["master_id"]) if found["master_id"] is not None else None
        year = _year_from_released(found["released"])
        resolved_title = found["title"]
        if master is not None:
            resolved_title = master["title"] or resolved_title
            year = int(master["year"]) if master["year"] else year

        matched.append(
            MatchedAlbum(
                artist_query=artist_query,
                title_query=title_query,
                master_id=found["master_id"],
                main_release_id=found["release_id"],
                title=resolved_title,
                artist_id=found["artist_id"],
                artist_name=found["name"],
                year=year,
            )
        )
    return matched, missed


def _candidate_album_pairs(
    ordered: list[MatchedAlbum],
    *,
    is_family_excluded: Callable[[int, int], bool] | None = None,
) -> list[tuple[MatchedAlbum, MatchedAlbum]]:
    """Every distinct-artist-pair candidate, in the same `i, i+1:` order the
    original sequential loop used -- shared by both the sequential and
    concurrent paths so output ordering/determinism never depends on
    `max_workers`.

    `is_family_excluded`, when given, drops a pair before any path search is
    attempted (e.g. a band's own album paired with a member's solo album) --
    see `networked_players_catalog.discogs.artist_family`. Excluded pairs
    never reach `find_path`, so no evidence toward them can ever surface,
    trivial or not.
    """
    used_pairs: set[tuple[int, int]] = set()
    candidates: list[tuple[MatchedAlbum, MatchedAlbum]] = []
    for i, from_album in enumerate(ordered):
        for to_album in ordered[i + 1 :]:
            if from_album.artist_id == to_album.artist_id:
                # Real bug found after Phase 7 introduced multi-album-per-
                # artist pre-resolved lanes (ADR 0065): `ordered` can now
                # contain two DIFFERENT albums by the SAME artist (e.g. two
                # Jamiroquai albums, or a Bucket A pick alongside an
                # already-published album by the same artist). Without this
                # skip, `pair = (id, id)` slips past the used_pairs dedup
                # (it was never seen before) and reaches `find_path`, which
                # raises `GraphError("from_artist_id and to_artist_id must
                # differ")` -- there is no meaningful "how is this artist
                # connected to themselves" question to ask. This was always
                # possible in principle; every catalog before Phase 7
                # deduped to one album per artist everywhere, so it was
                # never actually exercised until now.
                continue
            pair = (
                min(from_album.artist_id, to_album.artist_id),
                max(from_album.artist_id, to_album.artist_id),
            )
            if pair in used_pairs:
                continue
            if is_family_excluded is not None and is_family_excluded(*pair):
                continue
            used_pairs.add(pair)
            candidates.append((from_album, to_album))
    return candidates


def _bounded_find_path(
    graph: CreditGraph,
    from_artist_id: int,
    to_artist_id: int,
    *,
    max_hops: int,
    max_frontier_expansion: int | None,
) -> tuple[EvidencePath | None, bool]:
    """`find_path`, but a `FrontierTooLargeError` (search inconclusive, not a
    confirmed no-path -- see `graph.py`) is caught and reported as `(None,
    capped=True)` rather than propagating. At real-catalog scale (tens of
    thousands of candidate pairs, most of which are NOT connected), an
    unbounded BFS through a high-degree hub artist is the actual cost driver;
    a cap turns "run for a very long time" into "report this pair as
    inconclusive," which is honest -- not a confirmed no-path -- and bounded.
    """
    try:
        return (
            graph.find_path(
                from_artist_id,
                to_artist_id,
                max_hops=max_hops,
                max_frontier_expansion=max_frontier_expansion,
            ),
            False,
        )
    except FrontierTooLargeError:
        return None, True


# How many pairs each worker gets per concurrent batch. Bigger batches
# amortize thread/cursor overhead but waste more work past an early stop;
# the wasted tail is bounded by `max_workers * _PATH_BATCH_PER_WORKER`.
_PATH_BATCH_PER_WORKER = 4


def _iter_path_results(
    graph: CreditGraph,
    candidate_pairs: list[tuple[MatchedAlbum, MatchedAlbum]],
    *,
    max_hops: int,
    max_workers: int,
    max_frontier_expansion: int | None,
) -> Iterator[tuple[MatchedAlbum, MatchedAlbum, EvidencePath | None, bool]]:
    """Yield `(from_album, to_album, path, capped)` in `candidate_pairs`
    order, computing lazily so the caller can stop early.

    Why this is lazy, and why that matters enormously: the caller stops as
    soon as it has `max_paths` paths. The previous implementation
    precomputed EVERY candidate pair up front whenever `max_workers > 1`,
    which silently discarded that early stop -- measured on the real Phase 7
    179-album catalog, that is ~14,878 pairs at tens of seconds each
    (a multi-day job) to fill an artifact that only ever keeps a few hundred
    paths. Passing `max_workers > 1` therefore made the build dramatically
    SLOWER than the sequential default, which is the opposite of what a
    concurrency knob should do.

    `max_workers == 1` is a plain lazy loop. `max_workers > 1` computes in
    ORDER-PRESERVING BATCHES: each batch is spread across one dedicated
    `graph.cursor()` per worker (never shared between threads), results are
    re-sorted back into the original pair order before yielding, and the
    next batch is only started when the caller asks for it. So the work
    wasted past an early stop is bounded by a single batch, not the entire
    remaining candidate list, and the yielded sequence is byte-identical to
    the sequential path's regardless of `max_workers`.
    """
    if max_workers <= 1:
        for from_album, to_album in candidate_pairs:
            path, capped = _bounded_find_path(
                graph,
                from_album.artist_id,
                to_album.artist_id,
                max_hops=max_hops,
                max_frontier_expansion=max_frontier_expansion,
            )
            yield from_album, to_album, path, capped
        return

    worker_graphs = [graph.cursor() for _ in range(max_workers)]
    batch_size = max_workers * _PATH_BATCH_PER_WORKER

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for start in range(0, len(candidate_pairs), batch_size):
            batch = candidate_pairs[start : start + batch_size]
            # One chunk per worker, so a given cursor is only ever touched by
            # a single thread at a time (DuckDB cursors are not thread-safe).
            chunks: list[list[tuple[int, MatchedAlbum, MatchedAlbum]]] = [
                [] for _ in range(max_workers)
            ]
            for offset, (from_album, to_album) in enumerate(batch):
                chunks[offset % max_workers].append((offset, from_album, to_album))

            def _run_chunk(
                worker_index: int,
                chunks: list[list[tuple[int, MatchedAlbum, MatchedAlbum]]] = chunks,
            ) -> list[tuple[int, MatchedAlbum, MatchedAlbum, EvidencePath | None, bool]]:
                worker_graph = worker_graphs[worker_index]
                out = []
                for offset, from_album, to_album in chunks[worker_index]:
                    path, capped = _bounded_find_path(
                        worker_graph,
                        from_album.artist_id,
                        to_album.artist_id,
                        max_hops=max_hops,
                        max_frontier_expansion=max_frontier_expansion,
                    )
                    out.append((offset, from_album, to_album, path, capped))
                return out

            merged: list[tuple[int, MatchedAlbum, MatchedAlbum, EvidencePath | None, bool]] = []
            for chunk_out in pool.map(_run_chunk, range(max_workers)):
                merged.extend(chunk_out)
            merged.sort(key=lambda row: row[0])
            for _offset, from_album, to_album, path, capped in merged:
                yield from_album, to_album, path, capped


def build_challenge_v2(
    graph: CreditGraph,
    albums: list[dict[str, str]],
    *,
    snapshot_date: str,
    generated_by: str,
    max_paths: int = 12,
    max_hops: int = 4,
    max_workers: int = 1,
    is_family_excluded: Callable[[int, int], bool] | None = None,
    allowed_release_ids: frozenset[int] | None = None,
    master_exclusions: frozenset[int] | None = None,
    max_frontier_expansion: int | None = 300,
    catalog_version: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Match `{artist, title}` name/title queries against the graph, then
    build the artifact. For albums already resolved to a real artist_id
    (e.g. from `assemble_album_catalog`'s hybrid-catalog output), prefer
    `build_challenge_v2_from_matched` -- re-matching an already-known
    artist_id by name string is a real collision risk (a common display
    name, or worse a placeholder identity, can resolve to the wrong artist),
    not just redundant work."""
    matched, missed = match_albums(
        graph,
        albums,
        allowed_release_ids=allowed_release_ids,
        master_exclusions=master_exclusions,
    )
    return build_challenge_v2_from_matched(
        graph,
        matched,
        missed,
        snapshot_date=snapshot_date,
        generated_by=generated_by,
        max_paths=max_paths,
        max_hops=max_hops,
        max_workers=max_workers,
        is_family_excluded=is_family_excluded,
        max_frontier_expansion=max_frontier_expansion,
        catalog_version=catalog_version,
    )


def build_challenge_v2_from_matched(
    graph: CreditGraph,
    matched: list[MatchedAlbum],
    missed: list[dict[str, str]],
    *,
    snapshot_date: str,
    generated_by: str,
    max_paths: int = 12,
    max_hops: int = 4,
    max_workers: int = 1,
    is_family_excluded: Callable[[int, int], bool] | None = None,
    max_frontier_expansion: int | None = 300,
    catalog_version: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the artifact from an already-resolved album list -- no further
    name-based matching happens here. `missed` is carried through only for
    the report; pass `()` if there is nothing to report as missed.

    `max_frontier_expansion` (default 300, same as the cohort scorer's own
    default) bounds each `find_path` search -- at real-catalog scale (tens of
    thousands of candidate pairs, most NOT connected), an unbounded BFS
    through a high-degree hub artist is the real cost driver, not edge
    construction. A pair whose search hits the cap is reported inconclusive
    (`paths_capped` in the report), never as a confirmed no-path."""
    distinct_artist_matches = {m.artist_id: m for m in matched}
    if len(distinct_artist_matches) < 2:
        raise ValueError(
            f"only {len(distinct_artist_matches)} album(s) matched with distinct artists "
            "(need at least 2); widen the album list or check the snapshot"
        )

    ordered = sorted(matched, key=lambda m: m.album_id)
    candidate_pairs = _candidate_album_pairs(ordered, is_family_excluded=is_family_excluded)
    capped_count = 0
    attempted = 0
    paths_json: list[dict[str, Any]] = []
    used_release_ids: set[int] = set()
    used_artist_ids: set[int] = set()

    # Lazy in BOTH modes (see `_iter_path_results`): the `max_paths` break
    # below is what bounds the real cost, so path results must never be
    # precomputed for the whole candidate list ahead of it.
    #
    # The cap is checked AFTER appending, never at the top of the loop: a
    # top-of-loop guard only runs once the `for` has already pulled the next
    # item from the iterator, and pulling is what triggers the work -- one
    # extra bounded BFS in sequential mode (tens of seconds on the real
    # catalog), or an entire extra batch in concurrent mode when the
    # satisfying result happened to be the last of its batch. Breaking the
    # instant the final path lands means the iterator is never advanced past
    # the point the caller stopped caring about.
    path_results = _iter_path_results(
        graph,
        candidate_pairs,
        max_hops=max_hops,
        max_workers=max_workers,
        max_frontier_expansion=max_frontier_expansion,
    )
    if max_paths <= 0:
        # Nothing to fill: never advance the iterator at all (a top-of-loop
        # guard would still have computed one result before noticing).
        path_results = iter(())

    for from_album, to_album, path, capped in path_results:
        attempted += 1
        capped_count += int(capped)
        if path is None:
            continue

        hop_ids = {a for h in path.hops for a in (h.artist_a_id, h.artist_b_id)}
        used_artist_ids.update(hop_ids)
        for hop in path.hops:
            used_release_ids.add(hop.release_id)

        paths_json.append(
            {
                "id": f"path-{len(paths_json) + 1:02d}",
                "label": f"{from_album.title} → {to_album.title}",
                "description": (
                    "A single documented co-credit."
                    if len(path.hops) == 1
                    else f"{len(path.hops)} documented hops."
                ),
                "from_album_id": from_album.album_id,
                "to_album_id": to_album.album_id,
                "from_artist_id": from_album.artist_id,
                "to_artist_id": to_album.artist_id,
                "hops": [
                    {
                        "release_id": h.release_id,
                        "artist_a_id": h.artist_a_id,
                        "artist_b_id": h.artist_b_id,
                    }
                    for h in path.hops
                ],
            }
        )
        if len(paths_json) >= max_paths:
            break

    if not paths_json:
        raise ValueError("no evidence paths found between any matched albums")

    releases_json = []
    for release_id in sorted(used_release_ids):
        release = graph.release(release_id)
        if release is None:
            continue
        hop_artist_ids = {
            a
            for p in paths_json
            for h in p["hops"]
            if h["release_id"] == release_id
            for a in (h["artist_a_id"], h["artist_b_id"])
        }
        release_json = dict(release)
        release_json["credits"] = graph.credit_rows(release_id, hop_artist_ids)
        releases_json.append(release_json)

    artist_names = {aid: graph.artist_name(aid) or f"Artist {aid}" for aid in used_artist_ids}
    artists_json = [
        {"artist_id": aid, "name": artist_names[aid]} for aid in sorted(used_artist_ids)
    ]
    albums_json = [
        {
            "id": album.album_id,
            "master_id": album.master_id,
            "main_release_id": album.main_release_id,
            "title": album.title,
            "artist_id": album.artist_id,
            "artist": album.artist_name,
            "year": album.year,
            "cover_image": album.cover_image,
        }
        for album in ordered
    ]

    artifact: dict[str, Any] = {
        "schema_version": CHALLENGE_SCHEMA_VERSION,
        "provenance": {
            "source": "Discogs monthly data dump (CC0), one-hop working set",
            "license": (
                "Derived from the Discogs monthly CC0 data dumps. See docs/DATA_AND_RIGHTS.md."
            ),
            "snapshot_date": snapshot_date,
            "generated_by": generated_by,
            "graph_core_version": __version__,
            "catalog_version": catalog_version,
            "note": (
                "Derived from a bounded one-hop working set; the private "
                "collection seed used to build that working set is never "
                "published. The album list is an editorial selection, not a "
                "ranking. catalog_version identifies the canonical "
                "apps/web/public/data/catalog/albums.v1.json this artifact's "
                "album set was resolved from, when built from that artifact "
                "(null for a hand-written {artist,title} query list)."
            ),
        },
        "albums": albums_json,
        "artists": artists_json,
        "paths": paths_json,
        "releases": releases_json,
    }
    report = {
        "albums_matched": len(matched),
        "albums_missed": len(missed),
        "missed_queries": missed,
        "paths_found": len(paths_json),
        "paths_attempted": attempted,
        "paths_capped": capped_count,
    }
    return artifact, report


def validate_challenge(artifact: dict[str, Any], catalog: dict[str, Any] | None = None) -> None:
    """Generation-time validation -- delegates to the same dependency-free
    checklist the Pi fleet and web build run
    (`networked_players_contracts.challenge::challenge_failures`), so the
    two can never drift. `catalog`, if given, is used to cross-check
    `provenance.catalog_version` when the artifact carries one (see
    `challenge_failures`'s own docstring for the legitimate `None` case)."""
    failures = challenge_failures(artifact, catalog)
    if failures:
        raise ChallengeValidationError("; ".join(failures))
