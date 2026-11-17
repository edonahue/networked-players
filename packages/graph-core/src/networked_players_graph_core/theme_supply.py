"""Theme-seed candidate supply from the FULL parsed corpus (Campaign Atlas SS).

ADR 0072 section 7: a round's themes are seeds, and themes outside the current
one-hop corpus must be supplied from the full corpus. Round 1 shipped 6 albums
instead of 30 because every candidate-supply source was missing -- scorers and
re-rankers are consumers, not producers. This module is the producer for the
theme lane, the sibling of `collection_candidates` (private-seed lane) and
`relationship_pool` (graph lane).

Strategy, per theme, in ONE batched DuckDB query over all themes (never a
per-theme or per-seed loop):

1. Seed masters: the theme's explicit `seed_master_ids`, plus every master under
   a release the theme's `seed_artist_ids` are billed on (`release_artist`).
2. Seed performers: artists with a performer-qualifying credit
   (`relationship_pool.performer_qualifying_credit_sql`, i.e. ADR 0068's
   `is_performer_role_sql` or a billing scope -- the same rule the graph and
   the scorer use) on any release under a seed master.
3. Candidates: the seed masters themselves, plus masters sharing at least
   `min_shared_performers` distinct seed performers. Overlap candidates must
   match one of the theme's optional `styles`/`genres` tags; every candidate
   must fall inside the optional `year_min..year_max` and clear the editorial
   non-studio genre/style gate. Already-published and curated-excluded masters
   are dropped in SQL.
4. Ranked per theme (seed master, seed-artist master, then overlap desc) and
   capped at the theme's `candidate_cap` BEFORE the eligibility verdict. The
   cap bounds the per-master eligibility lookups below; a theme whose capped
   pool is mostly ineligible yields fewer eligible rows, which the summary
   reports per theme rather than hiding.

Studio-album eligibility then runs through `master_eligibility`
(`master_studio_eligibility_reason` / `select_master_main_release_id`) exactly
as `collection_candidates` does -- one source of truth. Those are deliberately
per-master lookups (see that module's docstring); the per-theme cap is what
bounds them. Not measured against the real corpus in this change.

Rows are `rank-album-candidates`-shaped and drop into
`score-expansion-candidates --candidates` with no downstream change, plus
`eligibility`, `main_release_selection_reason` and a `themes` list saying which
theme(s) surfaced the master and why. A row whose `eligibility` is not
`"eligible"` is kept with its reason (reviewable), and must be filtered by the
caller before greedy selection.

Naming a theme approves nothing: output is a private, pre-decision candidate
list (the CLI refuses a committable output path).

`build_rewiden_seed` is the post-approval counterpart: it turns the approved
pool into the release-ID seed `expand-one-hop` needs so the one-hop corpus is
re-widened only for approved albums.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import duckdb

from .album_policy import master_non_studio_sql
from .collection_candidates import _release_artist
from .editorial_seed import EDITORIAL_SEED_KIND, EDITORIAL_SEED_SCHEMA_VERSION
from .graph import CreditGraph, _not_placeholder_sql, read_parquet_sql
from .master_eligibility import master_studio_eligibility_reason, select_master_main_release_id
from .relationship_pool import performer_qualifying_credit_sql

_SOURCE_NAMES = {0: "seed_master", 1: "seed_artist_master", 2: "shared_performers"}


def _progress(quiet: bool, message: str) -> None:
    if not quiet:
        print(message, file=sys.stderr)


def _theme_pool_query(excluded_master_ids: Sequence[int]) -> str:
    exclusions_sql = ""
    if excluded_master_ids:
        ids = ", ".join(str(int(m)) for m in sorted(set(excluded_master_ids)))
        exclusions_sql = f"AND m.master_id NOT IN ({ids})"
    qualifying = performer_qualifying_credit_sql()
    not_placeholder = _not_placeholder_sql("c.artist_id")
    return f"""
        WITH seed_masters AS (
            SELECT theme_idx, master_id, 0 AS source_rank FROM theme_seed_masters
            UNION
            SELECT ta.theme_idx, r.master_id, 1 AS source_rank
            FROM theme_seed_artists ta
            JOIN credits c ON c.artist_id = ta.artist_id
            JOIN releases r ON r.release_id = c.release_id
            WHERE c.credit_scope = 'release_artist'
              AND c.playable_identity
              AND r.master_id IS NOT NULL
        ),
        seed_master_set AS (SELECT DISTINCT theme_idx, master_id FROM seed_masters),
        seed_performers AS (
            SELECT DISTINCT s.theme_idx, c.artist_id
            FROM seed_master_set s
            JOIN releases r ON r.master_id = s.master_id
            JOIN credits c ON c.release_id = r.release_id
            WHERE c.playable_identity
              AND c.artist_id IS NOT NULL
              AND {not_placeholder}
              AND {qualifying}
        ),
        overlap AS (
            SELECT sp.theme_idx, r.master_id, count(DISTINCT c.artist_id) AS shared
            FROM seed_performers sp
            JOIN credits c ON c.artist_id = sp.artist_id
            JOIN releases r ON r.release_id = c.release_id
            WHERE r.master_id IS NOT NULL
              AND c.playable_identity
              AND {not_placeholder}
              AND {qualifying}
            GROUP BY sp.theme_idx, r.master_id
        ),
        pool AS (
            SELECT theme_idx, master_id, min(source_rank) AS source_rank, max(shared) AS shared
            FROM (
                SELECT theme_idx, master_id, source_rank, NULL::BIGINT AS shared FROM seed_masters
                UNION ALL
                SELECT o.theme_idx, o.master_id, 2 AS source_rank, o.shared
                FROM overlap o
                JOIN themes t ON t.theme_idx = o.theme_idx
                WHERE o.shared >= t.min_shared_performers
            )
            GROUP BY theme_idx, master_id
        ),
        gated AS (
            SELECT p.theme_idx, p.master_id, p.source_rank, p.shared,
                   m.main_release_id, m.title, m.year,
                   row_number() OVER (
                       PARTITION BY p.theme_idx
                       ORDER BY p.source_rank, p.shared DESC NULLS LAST, p.master_id
                   ) AS rank_in_theme,
                   t.candidate_cap
            FROM pool p
            JOIN themes t ON t.theme_idx = p.theme_idx
            JOIN masters m ON m.master_id = p.master_id
            WHERE m.main_release_id IS NOT NULL
              AND NOT {master_non_studio_sql("m.genres", "m.styles")}
              AND (t.year_min IS NULL OR m.year >= t.year_min)
              AND (t.year_max IS NULL OR m.year <= t.year_max)
              AND (
                  p.source_rank < 2
                  OR (len(t.styles) = 0 AND len(t.genres) = 0)
                  OR list_has_any(m.styles, t.styles)
                  OR list_has_any(m.genres, t.genres)
              )
              {exclusions_sql}
        )
        SELECT theme_idx, master_id, source_rank, shared, main_release_id, title, year
        FROM gated
        WHERE rank_in_theme <= candidate_cap
        ORDER BY theme_idx, rank_in_theme
    """


def derive_theme_candidates(
    graph: CreditGraph,
    dataset_root: str | Path,
    masters_root: str | Path,
    spec: Mapping[str, Any],
    *,
    allowed_release_ids: frozenset[int],
    master_exclusions: frozenset[int] = frozenset(),
    already_published_master_ids: frozenset[int] = frozenset(),
    memory_limit: str = "3GB",
    threads: int = 2,
    quiet: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """`(rows, theme_summaries)` for a VALID round seed spec (the caller runs
    `round_seed_spec_failures` first). `graph` must be open over the same full
    corpus as `dataset_root` with masters attached.

    One row per distinct master, sorted by `master_id`; `themes` lists each
    theme that surfaced it. `theme_summaries` reports, per theme, the capped
    pool size and the eligible count, so a theme that under-delivers is visible.
    """
    themes = list(spec["themes"])
    start = time.monotonic()
    _progress(quiet, f"supplying candidates for {len(themes)} themes from the full corpus...")

    credits_glob = str(Path(dataset_root) / "table=credits" / "*.parquet")
    releases_glob = str(Path(dataset_root) / "table=releases" / "*.parquet")
    masters_glob = str(Path(masters_root) / "table=masters" / "*.parquet")
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(f"SET memory_limit = '{memory_limit}'")
        connection.execute(f"SET threads = {int(threads)}")
        connection.execute(f"CREATE VIEW credits AS SELECT * FROM {read_parquet_sql(credits_glob)}")
        connection.execute(
            f"CREATE VIEW releases AS SELECT * FROM {read_parquet_sql(releases_glob)}"
        )
        connection.execute(f"CREATE VIEW masters AS SELECT * FROM {read_parquet_sql(masters_glob)}")
        connection.execute(
            "CREATE TABLE themes (theme_idx INTEGER, min_shared_performers INTEGER, "
            "candidate_cap INTEGER, year_min INTEGER, year_max INTEGER, "
            "styles VARCHAR[], genres VARCHAR[])"
        )
        connection.execute("CREATE TABLE theme_seed_artists (theme_idx INTEGER, artist_id BIGINT)")
        connection.execute("CREATE TABLE theme_seed_masters (theme_idx INTEGER, master_id BIGINT)")
        connection.executemany(
            "INSERT INTO themes VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                [
                    i,
                    int(t["min_shared_performers"]),
                    int(t["candidate_cap"]),
                    t.get("year_min"),
                    t.get("year_max"),
                    list(t.get("styles", [])),
                    list(t.get("genres", [])),
                ]
                for i, t in enumerate(themes)
            ],
        )
        connection.executemany(
            "INSERT INTO theme_seed_artists VALUES (?, ?)",
            [[i, int(a)] for i, t in enumerate(themes) for a in t.get("seed_artist_ids", [])],
        )
        connection.executemany(
            "INSERT INTO theme_seed_masters VALUES (?, ?)",
            [[i, int(m)] for i, t in enumerate(themes) for m in t.get("seed_master_ids", [])],
        )
        pool_rows = connection.execute(
            _theme_pool_query(sorted(master_exclusions | already_published_master_ids))
        ).fetchall()
    finally:
        connection.close()
    _progress(quiet, f"{len(pool_rows)} theme/master pairs after SQL gates and per-theme caps")

    # Per distinct master: its facts once, and which themes surfaced it.
    surfaced: dict[int, list[dict[str, Any]]] = {}
    pool_by_theme: dict[int, int] = {}
    for theme_idx, master_id, source_rank, shared, _main, _title, _year in pool_rows:
        pool_by_theme[int(theme_idx)] = pool_by_theme.get(int(theme_idx), 0) + 1
        surfaced.setdefault(int(master_id), []).append(
            {
                "theme": themes[int(theme_idx)]["name"],
                "source": _SOURCE_NAMES[int(source_rank)],
                "shared_performers": None if shared is None else int(shared),
            }
        )
    master_ids = sorted(surfaced)

    verdicts: dict[int, tuple[str, int | None, str]] = {}
    for master_id in master_ids:
        reason = master_studio_eligibility_reason(
            graph,
            master_id,
            allowed_release_ids=allowed_release_ids,
            master_exclusions=master_exclusions,
        )
        if reason is not None:
            verdicts[master_id] = (reason, None, reason)
            continue
        main_release_id, release_reason = select_master_main_release_id(
            graph, master_id, allowed_release_ids=allowed_release_ids
        )
        if main_release_id is None:
            verdicts[master_id] = (release_reason, None, release_reason)
            continue
        verdicts[master_id] = ("eligible", main_release_id, release_reason)

    # One batched credit query across every eligible candidate's selected main release.
    eligible_release_ids = sorted({r for _, r, _ in verdicts.values() if r is not None})
    credits_by_release = graph.credit_rows_for_releases(eligible_release_ids)

    rows: list[dict[str, Any]] = []
    for master_id in master_ids:
        eligibility, main_release_id, release_reason = verdicts[master_id]
        master = graph.master(master_id) or {}
        artist_id: int | None = None
        artist_name: str | None = None
        if main_release_id is not None:
            artist_id, artist_name = _release_artist(credits_by_release.get(main_release_id, []))
            if artist_id is None:
                eligibility = "no_release_artist_credit"
        rows.append(
            {
                "master_id": master_id,
                "artist_id": artist_id,
                "artist_name": artist_name,
                "sample_title": master.get("title"),
                "main_release_id": main_release_id,
                "year": master.get("year"),
                "eligibility": eligibility,
                "main_release_selection_reason": release_reason,
                "themes": surfaced[master_id],
            }
        )

    eligible_by_master = {r["master_id"]: r["eligibility"] == "eligible" for r in rows}
    summaries = []
    for i, theme in enumerate(themes):
        names = [
            mid
            for mid, entries in surfaced.items()
            if any(e["theme"] == theme["name"] for e in entries)
        ]
        summaries.append(
            {
                "theme": theme["name"],
                "pool_size": pool_by_theme.get(i, 0),
                "eligible_count": sum(1 for mid in names if eligible_by_master[mid]),
                "candidate_cap": int(theme["candidate_cap"]),
            }
        )
    _progress(
        quiet,
        f"done in {time.monotonic() - start:.1f}s, "
        f"{sum(eligible_by_master.values())} of {len(rows)} distinct masters eligible",
    )
    return rows, summaries


def build_rewiden_seed(
    dataset_root: str | Path,
    masters_root: str | Path,
    *,
    approved_master_ids: Sequence[int],
    base_editorial_seed: Mapping[str, Any],
    snapshot_date: str,
    generated_at: str,
    generated_by: str,
    note: str,
    memory_limit: str = "3GB",
    threads: int = 2,
) -> tuple[dict[str, Any], list[int]]:
    """A `public-editorial-seed` payload for `expand-one-hop --additional-seed`.

    `expand_one_hop` takes ONE additional seed and seeds the frontier from
    `main_release_id`s only, so re-widening must carry the committed editorial
    seed's albums forward (otherwise the corpus would shrink for them) and add
    one entry per approved master. Base entries win on a shared `master_id`.
    Resolution of the approved masters is one batched query over the full
    corpus: the master's `main_release_id`, its billed release artist.

    Returns `(payload, unresolved_master_ids)`; an approved master with no
    main release or no billed playable artist cannot be seeded and the caller
    must fail on it rather than silently re-widen without it.
    """
    base_albums = list(base_editorial_seed.get("albums", []))
    have = {int(a["master_id"]) for a in base_albums if a.get("master_id") is not None}
    wanted = sorted({int(m) for m in approved_master_ids} - have)

    resolved: dict[int, dict[str, Any]] = {}
    if wanted:
        credits_glob = str(Path(dataset_root) / "table=credits" / "*.parquet")
        masters_glob = str(Path(masters_root) / "table=masters" / "*.parquet")
        connection = duckdb.connect(database=":memory:")
        try:
            connection.execute(f"SET memory_limit = '{memory_limit}'")
            connection.execute(f"SET threads = {int(threads)}")
            connection.execute(
                f"CREATE VIEW credits AS SELECT * FROM {read_parquet_sql(credits_glob)}"
            )
            connection.execute(
                f"CREATE VIEW masters AS SELECT * FROM {read_parquet_sql(masters_glob)}"
            )
            connection.execute("CREATE TABLE wanted (master_id BIGINT)")
            connection.executemany("INSERT INTO wanted VALUES (?)", [[m] for m in wanted])
            rows = connection.execute(
                f"""
                SELECT m.master_id, m.main_release_id, m.title, m.year,
                       min(c.artist_id) AS artist_id, min(c.name) AS artist_name
                FROM wanted w
                JOIN masters m ON m.master_id = w.master_id
                JOIN credits c ON c.release_id = m.main_release_id
                WHERE m.main_release_id IS NOT NULL
                  AND c.credit_scope = 'release_artist'
                  AND c.playable_identity
                  AND c.artist_id IS NOT NULL
                  AND {_not_placeholder_sql("c.artist_id")}
                GROUP BY m.master_id, m.main_release_id, m.title, m.year
                """
            ).fetchall()
        finally:
            connection.close()
        for master_id, main_release_id, title, year, artist_id, artist_name in rows:
            resolved[int(master_id)] = {
                "query_artist": None,
                "query_title": None,
                "master_id": int(master_id),
                "main_release_id": int(main_release_id),
                "artist_id": int(artist_id),
                "artist": artist_name,
                "title": title,
                "year": year,
            }
    unresolved = [m for m in wanted if m not in resolved]
    albums = base_albums + [resolved[m] for m in sorted(resolved)]
    payload = {
        "schema_version": EDITORIAL_SEED_SCHEMA_VERSION,
        "kind": EDITORIAL_SEED_KIND,
        "snapshot_date": snapshot_date,
        "generated_by": generated_by,
        "generated_at": generated_at,
        "note": note,
        "albums": albums,
    }
    return payload, unresolved
