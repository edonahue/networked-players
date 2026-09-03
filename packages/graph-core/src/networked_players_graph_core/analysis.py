"""Proxy ranking for album curation: release-variant count x credit richness.

This is the medium-term mechanism for growing the editorial album list
(data/albums/top-albums-v1.json) beyond hand-picked entries -- a signal to
look at, not an automatic ranking. Output is a local-only shortlist; it is
never committed (see data/albums/README.md).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import duckdb

from .album_policy import master_non_studio_sql
from .challenge import MatchedAlbum, _year_from_released, match_albums, release_eligibility_reason
from .graph import CreditGraph, _not_placeholder_sql, read_parquet_sql


def rank_album_candidates(
    dataset_root: Path,
    *,
    limit: int = 200,
    memory_limit: str = "3GB",
    threads: int = 2,
    release_format_policy: Path | None = None,
    masters_root: Path | None = None,
    master_exclusions: frozenset[int] | None = None,
    already_published_master_ids: frozenset[int] | None = None,
) -> list[dict[str, Any]]:
    """Rank master_ids by variant_count * credit_rows, resolved to a real
    {artist, title} query pair via the main release's release_artist credit.

    `release_format_policy`, when given, is a `release-format-scoring-index`
    (see `discogs/release_format_policy.py`) -- candidates whose main release
    isn't in the allow-list never surface at all, so a graph-rich but
    non-studio-album candidate (a compilation, a bootleg) can't be proposed
    for the hybrid catalog in the first place. A candidate whose main
    release has no resolvable release-artist credit is dropped -- there is
    no `{artist, title}` query to hand to `match_albums` without one.

    `already_published_master_ids`, when given, drops any master already in
    the published catalog before ranking -- not after. Measured on the real
    catalog-expansion readiness report (Phase 7 preflight, 2026-08-27): 76 of
    200 candidates (38%) were already-published masters, including 7 of the
    top 20 by score, which meant a "top-20 pilot" figure derived from that
    report over-counted its own marginal value by ~36%. This was never a
    review-time filter (`candidate_review.py` decorates whatever it's given,
    it does not gate membership) -- excluding here, at the ranking stage,
    means every count downstream of this function (the shortlist size, the
    percentile breakdowns, a "top N" slice) is honestly over candidates that
    could actually be added, not a mix of new and already-there.
    """
    dataset_root = Path(dataset_root)
    releases_glob = str(dataset_root / "table=releases" / "*.parquet")
    credits_glob = str(dataset_root / "table=credits" / "*.parquet")

    connection = duckdb.connect(database=":memory:")
    connection.execute(f"SET memory_limit = '{memory_limit}'")
    connection.execute(f"SET threads = {int(threads)}")
    connection.execute(f"CREATE VIEW releases AS SELECT * FROM {read_parquet_sql(releases_glob)}")
    connection.execute(f"CREATE VIEW credits AS SELECT * FROM {read_parquet_sql(credits_glob)}")

    # Masters carry the original release year (not an edition/reissue date) and
    # Discogs' editorial genre/style -- the only reliable non-studio signal for
    # soundtracks/stage recordings (release format descriptors miss them). When
    # absent, year falls back to the main-release edition date as before and no
    # genre/style exclusion is applied.
    master_meta_join = ""
    master_year_expr = "NULL"
    master_exclude_filter = ""
    if masters_root is not None:
        masters_glob = str(Path(masters_root) / "table=masters" / "*.parquet")
        connection.execute(f"CREATE VIEW masters AS SELECT * FROM {read_parquet_sql(masters_glob)}")
        master_meta_join = "LEFT JOIN masters m ON m.master_id = v.master_id"
        master_year_expr = "m.year"
        master_exclude_filter = f"AND NOT {master_non_studio_sql('m.genres', 'm.styles')}"
    if master_exclusions:
        ids = ", ".join(str(int(mid)) for mid in sorted(master_exclusions))
        master_exclude_filter += f" AND v.master_id NOT IN ({ids})"
    if already_published_master_ids:
        ids = ", ".join(str(int(mid)) for mid in sorted(already_published_master_ids))
        master_exclude_filter += f" AND v.master_id NOT IN ({ids})"

    not_placeholder = _not_placeholder_sql()
    policy_filter_sql = ""
    if release_format_policy is not None:
        payload = json.loads(Path(release_format_policy).read_text())
        if payload.get("kind") != "release-format-scoring-index":
            raise ValueError("release_format_policy must be a release-format-scoring-index")
        connection.execute(
            "CREATE TABLE allowed_releases AS "
            "SELECT UNNEST(allowed_release_ids)::BIGINT AS release_id "
            "FROM read_json_auto(?)",
            [str(release_format_policy)],
        )
        policy_filter_sql = "AND v.main_release_id IN (SELECT release_id FROM allowed_releases)"

    rows = connection.execute(
        f"""
        WITH variants AS (
            SELECT master_id, count(*) AS variant_count,
                   min(release_id) FILTER (WHERE master_is_main_release) AS main_release_id
            FROM releases
            WHERE master_id IS NOT NULL
            GROUP BY master_id
        ),
        credit_counts AS (
            SELECT r.master_id, count(*) AS credit_rows
            FROM credits c
            JOIN releases r USING (release_id)
            WHERE r.master_id IS NOT NULL
            GROUP BY r.master_id
        ),
        titles AS (
            SELECT master_id, title, released
            FROM releases
            WHERE master_is_main_release
            QUALIFY row_number() OVER (PARTITION BY master_id ORDER BY release_id) = 1
        ),
        release_artists AS (
            -- Excluded by numeric artist_id, never by name (a real band could
            -- be named "Anonymous") -- same placeholder-identity guard
            -- credit_edges_sql uses, so a compilation billed to "Various
            -- Artists" (id 194) can never surface as an album candidate.
            SELECT release_id, artist_id, name
            FROM credits
            WHERE credit_scope = 'release_artist' AND playable_identity AND artist_id IS NOT NULL
              AND {not_placeholder}
            QUALIFY row_number() OVER (PARTITION BY release_id ORDER BY artist_id) = 1
        )
        SELECT v.master_id, t.title AS sample_title, v.variant_count,
               coalesce(cc.credit_rows, 0) AS credit_rows,
               v.variant_count * coalesce(cc.credit_rows, 0) AS score,
               v.main_release_id, ra.artist_id, ra.name AS artist_name, t.released,
               {master_year_expr} AS master_year
        FROM variants v
        LEFT JOIN credit_counts cc USING (master_id)
        LEFT JOIN titles t USING (master_id)
        LEFT JOIN release_artists ra ON ra.release_id = v.main_release_id
        {master_meta_join}
        WHERE ra.artist_id IS NOT NULL
        {policy_filter_sql}
        {master_exclude_filter}
        ORDER BY score DESC, v.master_id
        LIMIT ?
        """,
        [limit],
    ).fetchall()
    connection.close()
    return [
        {
            "master_id": int(row[0]),
            "sample_title": row[1],
            "variant_count": int(row[2]),
            "credit_rows": int(row[3]),
            "score": int(row[4]),
            "main_release_id": int(row[5]),
            "artist_id": int(row[6]),
            "artist_name": row[7],
            # Master original year wins over the main-release edition date, which
            # is often a reissue in the bounded working set (the reissue-year bug).
            "year": int(row[9]) if row[9] is not None else _year_from_released(row[8]),
        }
        for row in rows
    ]


def _catalog_version(albums: list[dict[str, Any]], snapshot_date: str | None) -> str:
    """Deterministic, content-derived version identifier -- changes if and
    only if the resolved album set (or the snapshot it was resolved against)
    changes, so a downstream artifact can prove which catalog it consumed
    without trusting a hand-bumped number."""
    fingerprint = "|".join(
        sorted(
            f"{a['artist_id']}:{a['main_release_id']}:{a.get('master_id')}:{a['year']}"
            for a in albums
        )
    )
    digest = hashlib.sha256(fingerprint.encode()).hexdigest()[:12]
    prefix = f"catalog-v1-{snapshot_date}" if snapshot_date else "catalog-v1"
    return f"{prefix}-{digest}"


# graph-expansion Phase 0 slice 0-B (ADR 0069): catalog schema v2 adds
# per-album `selection_source`/`featured`/`expansion_round` -- presentation
# metadata that must NEVER perturb `catalog_version` (identity stays
# `artist_id:main_release_id:master_id:year` only, so a `featured` flip or a
# selection-source correction never cascades the 11 downstream artifact
# groups that key off `catalog_version`). This sibling hash exists so a
# consumer that DOES care about presentation (apps/web, the audit) can still
# prove which presentation state it read, without conflating the two.
CATALOG_SCHEMA_VERSION_V2 = 2
VALID_SELECTION_SOURCES = frozenset(
    {"editorial", "already_published", "graph_rich", "coverage_gap", "generic_candidate"}
)


def _catalog_presentation_version(albums: list[dict[str, Any]], snapshot_date: str | None) -> str:
    """Sibling to `_catalog_version`, hashing `id:featured:selection_source`
    instead of the identity fields -- changes only when a v2 catalog's
    presentation (which albums are featured, why each was selected) changes,
    never on identity-only rebuilds."""
    fingerprint = "|".join(
        sorted(f"{a.get('id')}:{a.get('featured')}:{a.get('selection_source')}" for a in albums)
    )
    digest = hashlib.sha256(fingerprint.encode()).hexdigest()[:12]
    prefix = (
        f"catalog-presentation-v1-{snapshot_date}" if snapshot_date else "catalog-presentation-v1"
    )
    return f"{prefix}-{digest}"


def exploration_corpus_version(albums: list[dict[str, Any]], snapshot_date: str | None) -> str:
    """The exploration-tier sibling of `_catalog_version` -- same fingerprint
    shape, deliberately different prefix (`explore-v1-` vs `catalog-v1-`) so
    an exploration-tier artifact can never be confused with, or accidentally
    validated against, the real editorial/game catalog (mirrors the
    Record-Routes-vs-Connection-Guesser non-collision discipline in ADR
    0046). Exploration tiers are local-only measurement artifacts (ADR 0049);
    this version identifies a tier run, it does not make one publishable."""
    fingerprint = "|".join(
        sorted(
            f"{a['artist_id']}:{a['main_release_id']}:{a.get('master_id')}:{a['year']}"
            for a in albums
        )
    )
    digest = hashlib.sha256(fingerprint.encode()).hexdigest()[:12]
    prefix = f"explore-v1-{snapshot_date}" if snapshot_date else "explore-v1"
    return f"{prefix}-{digest}"


_PRE_RESOLVED_PUBLISHABLE_FIELDS = (
    "query_artist",
    "query_title",
    "master_id",
    "main_release_id",
    "artist_id",
    "artist",
    "title",
    "year",
)


def _pre_resolved_missed_entry(album: dict[str, Any], *, reason: str) -> dict[str, Any]:
    """Only the documented `editorial-seed-v1.json` fields, plus `reason` --
    NEVER `{**album}`. `pre_resolved_missed` is published verbatim inside
    the committed, public catalog artifact. Its own contract
    (`data/contracts/editorial-seed-v1.md`) already promises the seed file
    carries only these fields, but `build-public-album-catalog`'s
    `--personal-seed` check only validated `kind`/`snapshot_date`, not the
    complete contract -- an out-of-contract field on a REJECTED entry (a
    stray note, or worse) would otherwise be copied straight into
    `apps/web/public/data/catalog/albums.v1.json`. Whitelisting here is
    defense in depth alongside the CLI's own full `editorial_seed_failures`
    check, not a substitute for it."""
    return {field: album.get(field) for field in _PRE_RESOLVED_PUBLISHABLE_FIELDS} | {
        "reason": reason
    }


def _pre_resolved_to_matched_album(graph: CreditGraph, album: dict[str, Any]) -> MatchedAlbum:
    """`data/albums/editorial-seed-v1.json`'s shape -> `MatchedAlbum`,
    without any text search: identity (`artist_id`/`main_release_id`) is
    already resolved (see `data/contracts/editorial-seed-v1.md`) and is
    never re-derived here. Title/year still prefer the CURRENTLY attached
    master over the seed file's own values, exactly like `match_albums`'s
    editorial path -- both paths should stay in sync with the master data a
    given catalog build actually runs against, not a value frozen at
    editorial-seed resolution time, which could predate a later Discogs
    correction to that master's title or year."""
    master_id = int(album["master_id"]) if album.get("master_id") is not None else None
    master = graph.master(master_id) if master_id is not None else None
    title = str(album["title"])
    year = album.get("year")
    if master is not None:
        title = master["title"] or title
        year = int(master["year"]) if master["year"] else year
    return MatchedAlbum(
        artist_query=str(album.get("query_artist") or album.get("artist") or ""),
        title_query=str(album.get("query_title") or album.get("title") or ""),
        master_id=master_id,
        main_release_id=int(album["main_release_id"]),
        title=title,
        artist_id=int(album["artist_id"]),
        artist_name=str(album["artist"]),
        year=year,
    )


# ADR 0069: the public per-album `selection_source` field never says
# "personal_editorial" -- the owner's decision is that a collection-sourced
# pick and a top-albums-v1.json pick are both just "editorial" to the
# public. `pre_resolved_buckets`' own lane label is intentionally left
# alone (see the comment above `pre_resolved_source_labels`).
_SELECTION_SOURCE_ALIASES = {"personal_editorial": "editorial"}


def load_featured_master_ids(path: Path | None) -> frozenset[int]:
    """Load `data/albums/featured-v1.json` (or an empty set) -- see
    `data/albums/README.md`. Same shape/precedent as
    `release_format_policy.load_master_exclusions`: a small, committed,
    editorial pin list, never derived from the corpus. A blurb is presentation
    (read only by apps/web), not eligibility -- this loader deliberately
    returns just the id set `assemble_album_catalog`'s `featured_master_ids`
    needs, not the blurbs themselves."""
    if path is None:
        return frozenset()
    payload = json.loads(Path(path).read_text())
    return frozenset(int(entry["master_id"]) for entry in payload.get("entries", []))


def assemble_album_catalog(
    graph: CreditGraph,
    editorial_albums: list[dict[str, str]],
    candidates: list[dict[str, Any]],
    *,
    target_count: int,
    pre_resolved_albums: list[dict[str, Any]] | None = None,
    additional_pre_resolved: list[tuple[str, list[dict[str, Any]], bool]] | None = None,
    private_weight_fn: Callable[[int], float] | None = None,
    allowed_release_ids: frozenset[int] | None = None,
    master_exclusions: frozenset[int] | None = None,
    snapshot_date: str | None = None,
    generated_by: str | None = None,
    featured_master_ids: frozenset[int] | None = None,
    expansion_round: int = 0,
) -> dict[str, Any]:
    """Combine the editorial backbone, an already-resolved personal bucket,
    and graph-rich candidates up to `target_count` (see ADR 0038, ADR 0065).
    Deterministic given a fixed graph snapshot, editorial list, pre-resolved
    list, candidate list, and weighting function.

    The editorial list always wins: every editorial entry is kept exactly as
    given, and any candidate whose artist_id matches an already-matched
    editorial artist is dropped rather than duplicated. Remaining candidates
    are ranked by `score` (optionally nudged by `private_weight_fn`, a
    local-only hook -- see ADR 0038/docs/PUBLIC_PRIVATE_BOUNDARY.md; never
    published, and this function never records which albums it affected) and
    added in that order until `target_count` is reached or candidates run
    out. Never pads past what real candidates support.

    `allowed_release_ids`, when given, fail-closed gates the *editorial* and
    *pre-resolved* sides by the same studio-album-v1 policy `candidates` was
    already filtered by upstream in `rank_album_candidates` -- an entry
    whose release isn't in the allow-list is dropped, never silently
    included, and never fabricated back in from the candidate pool.

    `pre_resolved_albums` (Phase 7 Bucket A: a personal/editorial anchor
    lane deliberately allowed MULTIPLE albums by the same artist -- e.g.
    five Jamiroquai albums) is **never** run through `match_albums`. That
    function's `seen_artist_ids` dedup keeps at most one album per artist,
    which is correct for `editorial_albums` (`top-albums-v1.json`'s
    one-album-per-notable-artist backbone) and would be a real, silent bug
    here: it would keep only the first of five Jamiroquai entries and drop
    the other four to nothing (ADR 0065 recorded this exact risk before any
    code existed to cause it). Each pre-resolved entry already carries a
    real identity, so it is converted to a `MatchedAlbum` directly and
    re-checked against `allowed_release_ids`/`master_exclusions` via the
    same `release_eligibility_reason` `match_albums` itself calls -- one
    rule, two entry points, never two copies of it. A pre-resolved entry
    whose `master_id` duplicates the editorial list or an earlier
    pre-resolved entry is dropped and reported in `pre_resolved_missed`,
    never silently included twice. Candidates -- and each other -- are
    excluded by ARTIST for both editorial and pre-resolved entries (an
    artist already covered by either lane doesn't need a graph-rich pick
    too), the one place multiple-albums-per-artist is deliberately NOT
    extended to Bucket B.

    `additional_pre_resolved` (Phase 7 Buckets B/C: `select-graph-rich-
    candidates`'s exact marginal-value picks and a human-reviewed coverage-
    gap selection -- and an already-published-catalog preservation lane for
    expanding a live catalog) is a list of `(label, albums,
    enforce_artist_uniqueness)` groups, each processed with the exact same
    eligibility re-check and cross-bucket master-dedup as `pre_resolved_albums`
    -- one rule, applied uniformly to every pre-resolved lane, never a
    second copy of it. `enforce_artist_uniqueness` is per-group, not global:
    `False` for a lane that -- like Bucket A -- may legitimately carry
    multiple albums by one artist (an already-published preservation lane
    MUST use `False`: real bug found in review -- a `True` here would let an
    earlier multi-album-per-artist lane's pick, e.g. Bucket A's own "Revolver"
    for The Beatles, lock out that SAME artist's already-published "Abbey
    Road" in a later lane, silently dropping a live album the whole
    preservation mechanism exists to protect). `True` for Bucket B/C, which
    get one album per artist, same as the generic candidates pool. Every
    KEPT entry locks its artist_id for every later lane regardless of its
    OWN group's flag -- only whether a group's OWN entries can be rejected
    for artist collision is what the flag controls, not whether its results
    block someone else. Unlike Bucket A, these lanes are algorithmic output
    (or externally-sourced, for the preservation lane), not hand-curated, so
    this function still never chooses which albums go in any of them; it
    only places already-decided picks. Group order matters: it determines
    both dedup priority (an earlier group's master_id wins a collision) and
    the returned `pre_resolved_buckets` ordering, which is what lets
    `catalog_audit.py` report each album's real provenance (personal
    editorial vs. graph-rich vs. coverage-gap vs. already-published) instead
    of collapsing every pre-resolved lane into one label.

    The returned `albums[]` are ID-resolved (`MatchedAlbum.to_resolved_dict()`
    shape: `artist_id`, `main_release_id`, ...), not `{artist, title}` name
    queries -- editorial, pre-resolved, and candidate entries alike already
    carry a real, known `artist_id`. Re-serializing any of them back to a
    name string and re-matching downstream would reopen exactly the
    collision risk `match_albums` already resolved once -- a common display
    name, or a placeholder identity, could resolve to the wrong artist on a
    second, blind pass.
    """
    if target_count <= 0:
        raise ValueError("target_count must be positive")

    matched_editorial, missed_editorial = match_albums(
        graph,
        editorial_albums,
        allowed_release_ids=allowed_release_ids,
        master_exclusions=master_exclusions,
    )
    editorial_artist_ids = {m.artist_id for m in matched_editorial}
    seen_master_ids: set[int] = {m.master_id for m in matched_editorial if m.master_id is not None}

    pre_resolved_kept: list[MatchedAlbum] = []
    pre_resolved_missed: list[dict[str, Any]] = []
    pre_resolved_buckets: list[dict[str, Any]] = []

    # Bucket A (`pre_resolved_albums`) deliberately allows multiple albums
    # by the same artist (ADR 0065) -- `locked_artist_ids` is seeded from
    # `editorial_artist_ids` alone, so Bucket A's own loop never checks it.
    # Every OTHER pre-resolved lane (Bucket B/C, `additional_pre_resolved`)
    # gets ONE album per artist, same as the generic candidates pool: a
    # graph-rich or coverage-gap entry whose artist already has an editorial,
    # personal, or earlier-additional-lane album -- or an earlier entry in
    # its OWN lane -- is dropped and reported in `pre_resolved_missed`,
    # never silently spending a second expansion slot on one artist.
    locked_artist_ids: set[int] = set(editorial_artist_ids)
    # Public-facing selection_source per kept pre-resolved album, parallel to
    # `pre_resolved_kept` -- normalizes the internal Bucket A lane name to
    # the owner's decided public label (ADR 0069: never "personal_editorial"
    # on a v2 catalog's own per-album field), while `pre_resolved_buckets`
    # below keeps its raw lane name unchanged (positional-reconstruction
    # callers, e.g. `catalog_audit.py`'s v1 fallback, are unaffected).
    pre_resolved_source_labels: list[str] = []

    def _process_pre_resolved_group(
        label: str, albums_in_group: list[dict[str, Any]], *, enforce_artist_uniqueness: bool
    ) -> None:
        group_kept_count = 0
        for album in albums_in_group:
            master_id = album.get("master_id")
            main_release_id = int(album["main_release_id"])
            artist_id = int(album["artist_id"])
            if master_id is not None and int(master_id) in seen_master_ids:
                pre_resolved_missed.append(
                    _pre_resolved_missed_entry(
                        album, reason="duplicate master_id already resolved earlier"
                    )
                )
                continue
            if enforce_artist_uniqueness and artist_id in locked_artist_ids:
                pre_resolved_missed.append(
                    _pre_resolved_missed_entry(
                        album,
                        reason=(
                            "artist already covered by the editorial list, a personal "
                            "seed entry, or an earlier pre-resolved lane"
                        ),
                    )
                )
                continue
            reason = release_eligibility_reason(
                graph,
                release_id=main_release_id,
                master_id=int(master_id) if master_id is not None else None,
                allowed_release_ids=allowed_release_ids,
                master_exclusions=master_exclusions,
            )
            if reason is not None:
                pre_resolved_missed.append(_pre_resolved_missed_entry(album, reason=reason))
                continue
            if master_id is not None:
                seen_master_ids.add(int(master_id))
            # Locked unconditionally, regardless of whether THIS group
            # enforces uniqueness on itself -- a multi-album-per-artist lane
            # (Bucket A, an already-published preservation lane) must still
            # block a LATER one-album-per-artist lane (Bucket B/C) from
            # spending a slot on an artist it already covers, even though it
            # never rejects its OWN entries for that reason.
            locked_artist_ids.add(artist_id)
            pre_resolved_kept.append(_pre_resolved_to_matched_album(graph, album))
            pre_resolved_source_labels.append(_SELECTION_SOURCE_ALIASES.get(label, label))
            group_kept_count += 1
        if albums_in_group:
            # Only record a bucket that was actually attempted (a non-empty
            # input) -- otherwise every catalog would carry a phantom
            # "personal_editorial: 0" entry even when --personal-seed was
            # never given at all, which is noise in the audit trail, not
            # signal (a genuinely-attempted lane that resolved to zero real
            # picks IS still recorded, since that zero is itself real
            # information).
            pre_resolved_buckets.append({"label": label, "count": group_kept_count})

    _process_pre_resolved_group(
        "personal_editorial", pre_resolved_albums or [], enforce_artist_uniqueness=False
    )
    for label, albums_in_group, enforce_artist_uniqueness in additional_pre_resolved or []:
        _process_pre_resolved_group(
            label, albums_in_group, enforce_artist_uniqueness=enforce_artist_uniqueness
        )

    pre_resolved_artist_ids = {m.artist_id for m in pre_resolved_kept}
    excluded_artist_ids = editorial_artist_ids | pre_resolved_artist_ids

    def _weighted_score(candidate: dict[str, Any]) -> float:
        base = float(candidate["score"])
        if private_weight_fn is None:
            return base
        return base * (1.0 + private_weight_fn(int(candidate["artist_id"])))

    excluded_masters = master_exclusions or frozenset()
    eligible_candidates = [
        c
        for c in candidates
        if c["artist_id"] not in excluded_artist_ids
        and (c.get("master_id") is None or int(c["master_id"]) not in excluded_masters)
    ]
    ranked_candidates = sorted(
        eligible_candidates, key=lambda c: (-_weighted_score(c), c["master_id"])
    )

    # Sized against matched_editorial + pre_resolved_kept (real inclusions),
    # not the raw input counts -- an entry that misses the snapshot or fails
    # policy shouldn't silently shrink how many candidates fill out the target.
    remaining_slots = max(0, target_count - len(matched_editorial) - len(pre_resolved_kept))
    added_candidate_ids: set[int] = set()
    candidate_albums: list[MatchedAlbum] = []
    for candidate in ranked_candidates:
        if len(candidate_albums) >= remaining_slots:
            break
        artist_id = int(candidate["artist_id"])
        candidate_master_id = candidate.get("master_id")
        if artist_id in added_candidate_ids:
            continue
        if candidate_master_id is not None and int(candidate_master_id) in seen_master_ids:
            continue
        added_candidate_ids.add(artist_id)
        if candidate_master_id is not None:
            seen_master_ids.add(int(candidate_master_id))
        candidate_albums.append(
            MatchedAlbum(
                artist_query=candidate["artist_name"],
                title_query=candidate["sample_title"],
                master_id=candidate["master_id"],
                main_release_id=candidate["main_release_id"],
                title=candidate["sample_title"],
                artist_id=artist_id,
                artist_name=candidate["artist_name"],
                year=candidate["year"],
            )
        )

    # v2 fields (ADR 0069) are opt-in via `featured_master_ids`: every
    # existing caller that never passes it keeps today's exact v1 shape
    # (no per-album selection_source/featured/expansion_round, no top-level
    # catalog_schema_version/catalog_presentation_version) -- landing this
    # capability must not perturb any already-committed catalog or existing
    # test's exact-shape assertions.
    is_v2_catalog = featured_master_ids is not None
    featured_set = featured_master_ids or frozenset()

    def _tagged(album_dict: dict[str, Any], selection_source: str) -> dict[str, Any]:
        if not is_v2_catalog:
            return album_dict
        return {
            **album_dict,
            "selection_source": selection_source,
            "featured": album_dict.get("master_id") in featured_set,
            "expansion_round": expansion_round,
        }

    albums = [
        *(_tagged(m.to_resolved_dict(), "editorial") for m in matched_editorial),
        *(
            _tagged(m.to_resolved_dict(), source)
            for m, source in zip(pre_resolved_kept, pre_resolved_source_labels, strict=True)
        ),
        *(_tagged(m.to_resolved_dict(), "generic_candidate") for m in candidate_albums),
    ]

    source_note = (
        "Hybrid catalog: an editorial backbone plus graph-rich additions selected by "
        "deterministic candidate scoring (ADR 0038). The canonical, single source of "
        "truth for which albums exist across every real public surface (album browser, "
        "Connection Guesser, Record Routes) -- every one derives its album set from "
        "this artifact's own catalog_version, never re-deriving or narrowing it "
        "independently (see ADR 0043). Combined at build time from "
        "data/albums/top-albums-v1.json and a rank-album-candidates shortlist. Albums "
        "are ID-resolved (artist_id/main_release_id), not name queries."
    )
    if pre_resolved_kept or pre_resolved_missed:
        # Only claim a pre-resolved lane participated when it was actually
        # given a non-empty input -- every lane is optional, and a source
        # note naming a lane that never ran would be misleading provenance
        # on a public artifact. Named generically (by whichever labels the
        # caller passed), not hardcoded to Bucket A/B/C, since this function
        # doesn't know which files backed each label -- that specificity is
        # the CLI layer's job.
        participating_labels = [bucket["label"] for bucket in pre_resolved_buckets]
        lane_phrase = (
            f"{len(participating_labels)} pre-resolved lane(s) ({', '.join(participating_labels)})"
            if participating_labels
            else "a pre-resolved lane"
        )
        source_note = (
            f"Hybrid catalog: an editorial backbone, {lane_phrase}, "
            "and graph-rich additions selected by deterministic candidate scoring "
            "(ADR 0038, ADR 0065). The canonical, single source of truth for which "
            "albums exist across every real public surface (album browser, Connection "
            "Guesser, Record Routes) -- every one derives its album set from this "
            "artifact's own catalog_version, never re-deriving or narrowing it "
            "independently (see ADR 0043). Combined at build time from "
            "data/albums/top-albums-v1.json, one or more pre-resolved lanes, and a "
            "rank-album-candidates shortlist. Albums are ID-resolved "
            "(artist_id/main_release_id), not name queries."
        )

    result: dict[str, Any] = {
        "version": 1,
        "catalog_version": _catalog_version(albums, snapshot_date),
        "snapshot_date": snapshot_date,
        "generated_by": generated_by,
        "source_note": source_note,
        "target_count": target_count,
        "editorial_count": len(matched_editorial),
        "editorial_missed": missed_editorial,
        "pre_resolved_count": len(pre_resolved_kept),
        "pre_resolved_missed": pre_resolved_missed,
        "pre_resolved_buckets": pre_resolved_buckets,
        "candidate_count_considered": len(candidates),
        "candidate_count_added": len(candidate_albums),
        "albums": albums,
    }
    if is_v2_catalog:
        result["catalog_schema_version"] = CATALOG_SCHEMA_VERSION_V2
        result["catalog_presentation_version"] = _catalog_presentation_version(
            albums, snapshot_date
        )
    return result


class AlbumCatalogValidationError(RuntimeError):
    """Raised when the canonical album catalog artifact violates its contract."""


_CATALOG_FORBIDDEN_SUBSTRINGS = ("/home/", "data/private", "local/", "DISCOGS_TOKEN", ".ssh")
_CATALOG_FORBIDDEN_PHRASES = ("worked with", "collaborated with", "influenced")


def validate_album_catalog(catalog: dict[str, Any]) -> None:
    """Structural/provenance validation for the canonical
    `apps/web/public/data/catalog/albums.v1.json` artifact (ADR 0043) --
    every real public surface (album browser, Connection Guesser, Record
    Routes) derives its album set from this file, so a malformed or
    unversioned catalog would silently break every downstream consumer's
    ability to prove which catalog it consumed."""
    failures: list[str] = []
    if not catalog.get("catalog_version"):
        failures.append("catalog_version is required")
    if not catalog.get("snapshot_date"):
        failures.append("snapshot_date is required")
    if not catalog.get("generated_by"):
        failures.append("generated_by is required")

    albums = catalog.get("albums", [])
    if not albums:
        failures.append("albums must not be empty")
    seen_ids: set[str] = set()
    for album in albums:
        album_id = album.get("id")
        if not album_id:
            failures.append(f"album missing id: {album!r}")
            continue
        if album_id in seen_ids:
            failures.append(f"duplicate album id: {album_id}")
        seen_ids.add(album_id)
        for field_name in ("artist_id", "artist", "main_release_id", "title", "year"):
            if field_name not in album:
                failures.append(f"album {album_id} missing required field {field_name!r}")
        if not isinstance(album.get("main_release_id"), int) or album["main_release_id"] <= 0:
            failures.append(f"album {album_id} has an invalid main_release_id")

    schema_version = catalog.get("catalog_schema_version")
    if schema_version is not None:
        if schema_version != CATALOG_SCHEMA_VERSION_V2:
            failures.append(f"unsupported catalog_schema_version: {schema_version!r}")
        else:
            for album in albums:
                album_id = album.get("id", "<unknown>")
                selection_source = album.get("selection_source")
                if selection_source not in VALID_SELECTION_SOURCES:
                    failures.append(
                        f"album {album_id} has an invalid selection_source: {selection_source!r}"
                    )
                if not isinstance(album.get("featured"), bool):
                    failures.append(f"album {album_id} missing/invalid boolean 'featured'")
                expansion_round = album.get("expansion_round")
                if (
                    not isinstance(expansion_round, int)
                    or isinstance(expansion_round, bool)
                    or expansion_round < 0
                ):
                    failures.append(
                        f"album {album_id} missing/invalid non-negative 'expansion_round'"
                    )
            expected_presentation_version = _catalog_presentation_version(
                albums, catalog.get("snapshot_date")
            )
            if catalog.get("catalog_presentation_version") != expected_presentation_version:
                failures.append(
                    "catalog_presentation_version "
                    f"{catalog.get('catalog_presentation_version')!r} does not match its own "
                    f"content (expected {expected_presentation_version!r})"
                )

    expected_version = _catalog_version(albums, catalog.get("snapshot_date"))
    if catalog.get("catalog_version") != expected_version:
        failures.append(
            f"catalog_version {catalog.get('catalog_version')!r} does not match its own "
            f"content (expected {expected_version!r}) -- the file was hand-edited or corrupted"
        )

    serialized = str(catalog)
    for forbidden in _CATALOG_FORBIDDEN_SUBSTRINGS:
        if forbidden in serialized:
            failures.append(f"catalog contains forbidden substring: {forbidden!r}")
    lowered = serialized.lower()
    for phrase in _CATALOG_FORBIDDEN_PHRASES:
        if phrase in lowered:
            failures.append(f"catalog contains forbidden phrase: {phrase!r}")

    if failures:
        raise AlbumCatalogValidationError("; ".join(failures))
