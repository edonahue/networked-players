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
4. Pool composition per theme (so a theme surfaces the SCENE, not one discography):
   the SQL gates give a PRE-CAP considered set (all seed-route masters; the best
   `PRECAP_FACTOR * candidate_cap` overlap candidates). Eligibility is decided over it, and
   `select_theme_pool` then applies the caps to ELIGIBLE masters only: explicit seed masters
   are exempt from the per-artist cap and the overlap quota; seed-artist masters take at
   most `max_masters_per_seed_artist` per seed artist; overlap fills the rest, with
   `ceil(cap * min_overlap_share_percent / 100)` slots reserved. Within each route ranking
   is shared performers desc, then master id. Ineligible masters are kept in the output
   with their reason, outside the cap accounting. A shortfall of overlap is reported in the
   summary, never padded.

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

import re
import sys
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import duckdb

from .album_policy import master_non_studio_reason, master_non_studio_sql
from .collection_candidates import _release_artist
from .editorial_seed import EDITORIAL_SEED_KIND, EDITORIAL_SEED_SCHEMA_VERSION
from .graph import CreditGraph, _not_placeholder_sql, read_parquet_sql
from .master_eligibility import master_studio_verdicts_batch
from .relationship_pool import performer_qualifying_credit_sql

_SOURCE_NAMES = {0: "seed_master", 1: "seed_artist_master", 2: "shared_performers"}


def _progress(quiet: bool, message: str) -> None:
    if not quiet:
        print(message, file=sys.stderr)


def overlap_quota(theme: Mapping[str, Any]) -> int:
    """Pool slots reserved for shared-performer candidates: ceil(cap * share / 100)."""
    cap, share = int(theme["candidate_cap"]), int(theme["min_overlap_share_percent"])
    return -(-cap * share // 100)


def _theme_pool_query(excluded_master_ids: Sequence[int]) -> str:
    exclusions_sql = ""
    if excluded_master_ids:
        ids = ", ".join(str(int(m)) for m in sorted(set(excluded_master_ids)))
        exclusions_sql = f"AND m.master_id NOT IN ({ids})"
    qualifying = performer_qualifying_credit_sql()
    not_placeholder = _not_placeholder_sql("c.artist_id")
    return f"""
        WITH seed_masters AS (
            SELECT theme_idx, master_id, 0 AS source_rank, NULL::BIGINT AS seed_artist_id
            FROM theme_seed_masters
            UNION
            SELECT ta.theme_idx, r.master_id, 1 AS source_rank, ta.artist_id
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
        -- One row per (theme, master): its best route, the seed artist it is capped
        -- under (route 1 only; a collaboration counts under the lowest seed artist id),
        -- and its shared-performer count (used only to RANK within a route). Masters
        -- under a seed artist or seed master never re-enter as overlap candidates, so a
        -- per-artist cap cannot be bypassed through the overlap route.
        candidates AS (
            SELECT sm.theme_idx, sm.master_id, min(sm.source_rank) AS source_rank,
                   min(sm.seed_artist_id) FILTER (WHERE sm.source_rank = 1) AS seed_artist_id,
                   max(o.shared) AS shared
            FROM seed_masters sm
            LEFT JOIN overlap o ON o.theme_idx = sm.theme_idx AND o.master_id = sm.master_id
            GROUP BY sm.theme_idx, sm.master_id
            UNION ALL
            SELECT o.theme_idx, o.master_id, 2, NULL::BIGINT, o.shared
            FROM overlap o
            JOIN themes t ON t.theme_idx = o.theme_idx
            WHERE o.shared >= t.min_shared_performers
              AND NOT EXISTS (
                  SELECT 1 FROM seed_master_set s
                  WHERE s.theme_idx = o.theme_idx AND s.master_id = o.master_id
              )
        ),
        gated AS (
            SELECT p.theme_idx, p.master_id, p.source_rank, p.seed_artist_id, p.shared,
                   m.main_release_id, m.title, m.year, m.genres, m.styles
            FROM candidates p
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
        ),
        -- Eligibility is decided in Python over THIS pre-cap set, and the per-artist cap,
        -- overlap reservation and candidate_cap then apply to ELIGIBLE masters only (an
        -- ineligible live album or box set must never push an eligible master out). The
        -- seed routes are bounded by the seed artists' discographies; the overlap route is
        -- cut to the best `precap` by shared performers, with the true total reported so a
        -- truncation is visible.
        ranked AS (
            SELECT g.*,
                   row_number() OVER (
                       PARTITION BY g.theme_idx, g.source_rank
                       ORDER BY g.shared DESC NULLS LAST, g.master_id
                   ) AS rn,
                   count(*) FILTER (WHERE g.source_rank = 2)
                       OVER (PARTITION BY g.theme_idx) AS overlap_total
            FROM gated g
        )
        SELECT r.theme_idx, r.master_id, r.source_rank, r.shared, r.main_release_id, r.title,
               r.year, r.genres, r.styles, r.seed_artist_id, r.overlap_total
        FROM ranked r
        JOIN themes t ON t.theme_idx = r.theme_idx
        WHERE r.source_rank < 2 OR r.rn <= t.precap
        ORDER BY r.theme_idx, r.source_rank, r.shared DESC NULLS LAST, r.master_id
    """


PRECAP_FACTOR = 10  # overlap candidates considered per theme = factor * candidate_cap

_MEMORY_LIMIT_PATTERN = re.compile(r"^\d+(\.\d+)?\s?(KB|MB|GB|TB|KiB|MiB|GiB|TiB)$", re.IGNORECASE)


def safe_memory_limit(value: str) -> str:
    """A DuckDB `memory_limit` literal, validated before it is interpolated into SET."""
    if not _MEMORY_LIMIT_PATTERN.match(str(value)):
        raise ValueError(f"invalid memory limit {value!r} (expected e.g. '2GB', '512MiB')")
    return str(value)


def select_theme_pool(
    theme: Mapping[str, Any], considered: Sequence[Mapping[str, Any]]
) -> list[int]:
    """Master ids selected for one theme from its ELIGIBLE considered candidates.

    `considered` entries carry `master_id`, `source_rank` (0 explicit seed master,
    1 seed-artist master, 2 shared-performer overlap), `shared`, `seed_artist_id` and
    `eligible`. Explicit seed masters are exempt from the per-artist cap and the overlap
    quota (they neither count toward nor get cut by either). Seed-artist masters take
    at most `max_masters_per_seed_artist` per seed artist, in `cap - n_seed - quota`
    slots; overlap fills the remaining slots. Within each route ranking is shared
    performers desc, then master id. Ineligible masters never occupy a slot.
    """
    cap = int(theme["candidate_cap"])
    per_artist = int(theme["max_masters_per_seed_artist"])
    quota = overlap_quota(theme)

    def order(e: Mapping[str, Any]) -> tuple[int, int]:
        return (-(e["shared"] or 0), int(e["master_id"]))

    eligible = [e for e in considered if e["eligible"]]
    seeds = sorted(
        (e for e in eligible if e["source_rank"] == 0), key=lambda e: int(e["master_id"])
    )[:cap]
    seed_slots = max(0, cap - len(seeds) - quota)
    per_artist_count: dict[Any, int] = {}
    artist_kept: list[Mapping[str, Any]] = []
    for e in sorted((e for e in eligible if e["source_rank"] == 1), key=order):
        if len(artist_kept) >= seed_slots:
            break
        if per_artist_count.get(e["seed_artist_id"], 0) >= per_artist:
            continue
        per_artist_count[e["seed_artist_id"]] = per_artist_count.get(e["seed_artist_id"], 0) + 1
        artist_kept.append(e)
    overlap_slots = cap - len(seeds) - len(artist_kept)
    overlap_kept = sorted((e for e in eligible if e["source_rank"] == 2), key=order)[
        : max(0, overlap_slots)
    ]
    return [int(e["master_id"]) for e in (*seeds, *artist_kept, *overlap_kept)]


def _seed_master_drop_reason(
    master_id: int,
    facts: Sequence[Any] | None,
    theme: Mapping[str, Any],
    *,
    excluded: frozenset[int],
    published: frozenset[int],
) -> str:
    """Why an explicit seed master did not reach its theme's pool, so an operator's
    seed is never silently lost. `facts` is `(master_id, main_release_id, year,
    genres, styles)` from the masters table, or None when it has no row."""
    if master_id in published:
        return "already_published"
    if master_id in excluded:
        return "curated_master_exclusion"
    if facts is None:
        return "not_in_masters_table"
    _, main_release_id, year, genres, styles = facts
    if main_release_id is None:
        return "no_main_release"
    if master_non_studio_reason(list(genres or []), list(styles or [])):
        return "non_studio_genre_style"
    lo, hi = theme.get("year_min"), theme.get("year_max")
    if (lo is not None or hi is not None) and year is None:
        return "no_year_but_year_bounds_set"
    if (lo is not None and year < lo) or (hi is not None and year > hi):
        return "outside_year_bounds"
    return "cut_by_candidate_cap"


def derive_theme_candidates(
    graph: CreditGraph,
    dataset_root: str | Path,
    masters_root: str | Path,
    spec: Mapping[str, Any],
    *,
    allowed_release_ids: frozenset[int],
    classify_pool_releases: Callable[[Sequence[int]], frozenset[int]] | None = None,
    master_exclusions: frozenset[int] = frozenset(),
    already_published_master_ids: frozenset[int] = frozenset(),
    memory_limit: str = "3GB",
    threads: int = 2,
    quiet: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """`(rows, theme_summaries)` for a VALID round seed spec (the caller runs
    `round_seed_spec_failures` first). `graph` must be open over the same full
    corpus as `dataset_root` with masters attached.

    Per theme: SQL gates produce a PRE-CAP considered set, eligibility is decided over
    it, and the per-artist cap, overlap reservation and `candidate_cap` then apply to
    ELIGIBLE masters only (`select_theme_pool`). Rows: one per distinct master, sorted
    by `master_id`: every selected (eligible) master, plus every considered INELIGIBLE
    master with its reason (outside the cap accounting, so reviewable). `themes` lists
    each theme that surfaced it and whether it was `selected` there.

    `allowed_release_ids` is the existing (one-hop) format allow-list, which has no
    entries for masters outside that corpus. `classify_pool_releases`, when given, is
    called ONCE with every release id under the considered masters and returns the
    subset the release-format rules allow (the catalog package supplies a bounded
    classification of the full corpus; graph-core never imports it). The effective
    allow-list is the explicit UNION of the two.
    """
    themes = list(spec["themes"])
    memory_limit = safe_memory_limit(memory_limit)
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
            "styles VARCHAR[], genres VARCHAR[], precap INTEGER)"
        )
        connection.execute("CREATE TABLE theme_seed_artists (theme_idx INTEGER, artist_id BIGINT)")
        connection.execute("CREATE TABLE theme_seed_masters (theme_idx INTEGER, master_id BIGINT)")
        connection.executemany(
            "INSERT INTO themes VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                [
                    i,
                    int(t["min_shared_performers"]),
                    int(t["candidate_cap"]),
                    t.get("year_min"),
                    t.get("year_max"),
                    list(t.get("styles", [])),
                    list(t.get("genres", [])),
                    PRECAP_FACTOR * int(t["candidate_cap"]),
                ]
                for i, t in enumerate(themes)
            ],
        )
        seed_artist_rows = [
            [i, int(a)] for i, t in enumerate(themes) for a in t.get("seed_artist_ids", [])
        ]
        if seed_artist_rows:
            connection.executemany("INSERT INTO theme_seed_artists VALUES (?, ?)", seed_artist_rows)
        seed_master_rows = [
            [i, int(m)] for i, t in enumerate(themes) for m in t.get("seed_master_ids", [])
        ]
        if seed_master_rows:
            connection.executemany("INSERT INTO theme_seed_masters VALUES (?, ?)", seed_master_rows)
        connection.execute(
            "CREATE TEMP TABLE theme_pool AS "
            + _theme_pool_query(sorted(master_exclusions | already_published_master_ids))
        )
        pool_rows = connection.execute(
            "SELECT theme_idx, master_id, source_rank, shared, main_release_id, title, year, "
            "genres, styles, seed_artist_id, overlap_total FROM theme_pool"
        ).fetchall()
        # Set-based eligibility inputs: every considered master's releases in ONE query,
        # not several full-corpus scans per master.
        release_rows = connection.execute(
            "SELECT r.release_id, r.master_id, r.released, r.title FROM releases r "
            "WHERE r.master_id IN (SELECT DISTINCT master_id FROM theme_pool)"
        ).fetchall()
        seed_master_facts = connection.execute(
            "SELECT m.master_id, m.main_release_id, m.year, m.genres, m.styles "
            "FROM masters m WHERE m.master_id IN (SELECT master_id FROM theme_seed_masters)"
        ).fetchall()
    finally:
        connection.close()
    _progress(quiet, f"{len(pool_rows)} theme/master pairs considered after SQL gates")

    # Per distinct master: its facts once, and its per-theme entry.
    entries: dict[int, dict[int, dict[str, Any]]] = {}  # master -> theme_idx -> entry
    facts: dict[int, dict[str, Any]] = {}
    overlap_totals: dict[int, int] = {}
    for (
        theme_idx,
        master_id,
        source_rank,
        shared,
        main,
        title,
        year,
        genres,
        styles,
        seed_artist_id,
        overlap_total,
    ) in pool_rows:
        facts[int(master_id)] = {
            "main_release_id": main,
            "title": title,
            "year": year,
            "genres": genres,
            "styles": styles,
        }
        overlap_totals[int(theme_idx)] = int(overlap_total or 0)
        entries.setdefault(int(master_id), {})[int(theme_idx)] = {
            "master_id": int(master_id),
            "source_rank": int(source_rank),
            "shared": None if shared is None else int(shared),
            "seed_artist_id": None if seed_artist_id is None else int(seed_artist_id),
        }

    releases_by_master: dict[int, list[tuple[int, str | None]]] = {}
    release_titles: dict[int, str | None] = {}
    for release_id, master_id, released, release_title in release_rows:
        releases_by_master.setdefault(int(master_id), []).append((int(release_id), released))
        release_titles[int(release_id)] = release_title
    if classify_pool_releases is not None:
        bounded_allowed = classify_pool_releases(
            sorted({r for rs in releases_by_master.values() for r, _ in rs})
        )
        _progress(
            quiet,
            f"bounded classification allowed {len(bounded_allowed)} considered releases "
            f"(union with {len(allowed_release_ids)} supplied allowed ids)",
        )
        allowed_release_ids = allowed_release_ids | frozenset(bounded_allowed)
    verdicts = master_studio_verdicts_batch(
        facts,
        releases_by_master,
        allowed_release_ids=allowed_release_ids,
        master_exclusions=master_exclusions,
    )

    # One batched credit query across every eligible considered master's main release.
    eligible_release_ids = sorted({r for _, r, _ in verdicts.values() if r is not None})
    credits_by_release = graph.credit_rows_for_releases(eligible_release_ids)
    eligibility: dict[int, str] = {}
    release_artist: dict[int, tuple[int | None, str | None]] = {}
    for master_id in sorted(entries):
        verdict, main_release_id, _reason = verdicts[master_id]
        if main_release_id is not None:
            artist = _release_artist(credits_by_release.get(main_release_id, []))
            release_artist[master_id] = artist
            if artist[0] is None:
                verdict = "no_release_artist_credit"
        eligibility[master_id] = verdict

    # Select per theme over ELIGIBLE masters only.
    selected_by_theme: dict[int, list[int]] = {}
    for i, theme in enumerate(themes):
        considered = [
            {**per_theme[i], "eligible": eligibility[mid] == "eligible"}
            for mid, per_theme in entries.items()
            if i in per_theme
        ]
        selected_by_theme[i] = select_theme_pool(theme, considered)
    selected_sets = {i: set(ids) for i, ids in selected_by_theme.items()}

    rows: list[dict[str, Any]] = []
    for master_id in sorted(entries):
        selected_anywhere = any(master_id in selected_sets[i] for i in entries[master_id])
        if eligibility[master_id] == "eligible" and not selected_anywhere:
            continue  # eligible but cut by every theme's caps: not in the pool
        _verdict, main_release_id, release_reason = verdicts[master_id]
        master = facts[master_id]
        artist_id, artist_name = release_artist.get(master_id, (None, None))
        rows.append(
            {
                "master_id": master_id,
                "artist_id": artist_id,
                "artist_name": artist_name,
                "sample_title": master["title"],
                "main_release_title": (
                    release_titles.get(main_release_id) if main_release_id is not None else None
                ),
                "main_release_id": main_release_id,
                "year": master["year"],
                "eligibility": eligibility[master_id],
                "main_release_selection_reason": release_reason,
                "themes": [
                    {
                        "theme": themes[i]["name"],
                        "source": _SOURCE_NAMES[entry["source_rank"]],
                        "shared_performers": entry["shared"],
                        "selected": master_id in selected_sets[i],
                    }
                    for i, entry in sorted(entries[master_id].items())
                    if master_id in selected_sets[i] or eligibility[master_id] != "eligible"
                ],
            }
        )

    seed_facts = {int(r[0]): r for r in seed_master_facts}
    row_by_master = {r["master_id"]: r for r in rows}
    summaries = []
    for i, theme in enumerate(themes):
        considered_ids = [mid for mid, per_theme in entries.items() if i in per_theme]
        selected = selected_by_theme[i]
        selected_set = selected_sets[i]
        ineligible = [m for m in considered_ids if eligibility[m] != "eligible"]
        route_of = {m: entries[m][i]["source_rank"] for m in considered_ids}
        selected_mix = Counter(_SOURCE_NAMES[route_of[m]] for m in selected)
        considered_mix = Counter(_SOURCE_NAMES[route_of[m]] for m in considered_ids)
        per_seed_artist = Counter(
            entries[m][i]["seed_artist_id"]
            for m in selected
            if route_of[m] == 1 and entries[m][i]["seed_artist_id"] is not None
        )
        per_billed_artist = Counter(
            row_by_master[m]["artist_id"]
            for m in selected
            if row_by_master[m]["artist_id"] is not None
        )
        n_seed = sum(1 for m in selected if route_of[m] == 0)
        quota = max(0, min(overlap_quota(theme), int(theme["candidate_cap"]) - n_seed))
        overlap_selected = selected_mix.get("shared_performers", 0)
        dropped = [
            {
                "master_id": int(mid),
                "reason": (
                    eligibility[int(mid)]
                    if int(mid) in entries and i in entries[int(mid)]
                    else _seed_master_drop_reason(
                        int(mid),
                        seed_facts.get(int(mid)),
                        theme,
                        excluded=master_exclusions,
                        published=already_published_master_ids,
                    )
                ),
            }
            for mid in theme.get("seed_master_ids", [])
            if int(mid) not in selected_set
        ]
        summaries.append(
            {
                "theme": theme["name"],
                "considered_count": len(considered_ids),
                "considered_route_mix": {
                    n: considered_mix.get(n, 0) for n in _SOURCE_NAMES.values()
                },
                "overlap_candidates_total": overlap_totals.get(i, 0),
                "overlap_candidates_truncated": max(
                    0, overlap_totals.get(i, 0) - PRECAP_FACTOR * int(theme["candidate_cap"])
                ),
                "pool_size": len(selected),
                "eligible_count": len(selected),
                "eligible_unselected_count": sum(
                    1
                    for m in considered_ids
                    if eligibility[m] == "eligible" and m not in selected_set
                ),
                "route_mix": {n: selected_mix.get(n, 0) for n in _SOURCE_NAMES.values()},
                "ineligible_count": len(ineligible),
                "ineligibility_reasons": dict(
                    sorted(Counter(eligibility[m] for m in ineligible).items())
                ),
                "max_masters_per_seed_artist_selected": max(per_seed_artist.values(), default=0),
                "max_masters_per_billed_artist_selected": max(
                    per_billed_artist.values(), default=0
                ),
                "overlap_quota": quota,
                "overlap_shortfall": max(0, quota - overlap_selected),
                "dropped_seed_masters": dropped,
                "candidate_cap": int(theme["candidate_cap"]),
            }
        )
    _progress(
        quiet,
        f"done in {time.monotonic() - start:.1f}s, "
        f"{sum(len(v) for v in selected_by_theme.values())} theme selections "
        f"over {len(rows)} output masters",
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
            connection.execute(f"SET memory_limit = '{safe_memory_limit(memory_limit)}'")
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
                       min(c.artist_id) AS artist_id,
                       arg_min(c.name, c.artist_id) AS artist_name
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
