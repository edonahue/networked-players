"""A DuckDB-backed, evidence-preserving credit graph over a one-hop dataset.

Design decision: query-per-hop BFS over DuckDB views, never a materialized
in-Python adjacency. A one-hop corpus can hold hundreds of thousands of
credit rows; the coordination host's working budget is ~4GB. NetworkX or an
in-memory adjacency structure is the recorded revisit path if a measured
need appears (e.g. path lookups become a proven bottleneck) -- not assumed
up front. See AGENTS.md's "measured implementation need" requirement.

This package must not import from ``networked_players_catalog`` -- the
dependency direction is catalog CLI -> graph-core only, never the reverse.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import duckdb

# Discogs placeholder identities -- IDs that stand in for "we don't know who"
# or "many people", not for a person. Defined in `placeholder_artists.json`
# beside this module so the list is reviewable and editable without touching
# code; see ADR 0035 for the audit that produced it.
#
# Filtering is ALWAYS by numeric artist_id. The `name` in that file documents
# the ID, it never selects it -- a real band can be called "Anonymous".
#
# Two policies, per entry:
#   exclude -- the identity never enters `credit_edges`, so it cannot be a hop
#              endpoint, a curator suggestion, or a site path node.
#   flag    -- the identity stays traversable; `cohort_connectivity` tags every
#              hop through it `placeholder_artist_hop` for human review.
PLACEHOLDER_ARTISTS_CONFIG = "placeholder_artists.json"


def _load_placeholder_artists() -> tuple[dict[int, str], frozenset[int], frozenset[int]]:
    raw = json.loads(
        resources.files(__package__).joinpath(PLACEHOLDER_ARTISTS_CONFIG).read_text("utf-8")
    )
    default = str(raw.get("default_policy", "exclude"))
    policies: dict[int, str] = {}
    names: dict[int, str] = {}
    for entry in raw["artists"]:
        artist_id = int(entry["artist_id"])
        policy = str(entry.get("policy", default))
        if policy not in ("exclude", "flag"):
            raise ValueError(
                f"{PLACEHOLDER_ARTISTS_CONFIG}: artist_id {artist_id} has unknown "
                f"policy {policy!r}; expected 'exclude' or 'flag'"
            )
        policies[artist_id] = policy
        names[artist_id] = str(entry["name"])
    excluded = frozenset(a for a, p in policies.items() if p == "exclude")
    flagged = frozenset(a for a, p in policies.items() if p == "flag")
    return names, excluded, flagged


PLACEHOLDER_ARTIST_NAMES, NON_INDIVIDUAL_ARTIST_IDS, FLAGGED_PLACEHOLDER_ARTIST_IDS = (
    _load_placeholder_artists()
)

# Every placeholder identity, whatever its policy -- what `cohort_connectivity`
# arms its `placeholder_artist_hop` alarm on.
PLACEHOLDER_ARTIST_IDS = NON_INDIVIDUAL_ARTIST_IDS | FLAGGED_PLACEHOLDER_ARTIST_IDS

# Names that mark an identity as a placeholder rather than a person. Used ONLY
# by `placeholder_artist_candidates()` to *propose* additions to the config for
# human review -- never to exclude an artist at query time, and never as a join
# key. Deliberately anchored and conservative: "Untitled" and "None" are
# omitted because both are plausible band names.
PLACEHOLDER_NAME_PATTERN = (
    r"^(various|various artists|unknown|unknown artist|no artist|not on label|"
    r"traditional|trad\.?|anonymous|uncredited|n/a|artist unknown|no artist listed)"
    r"( \([0-9]+\))?$"
)

# --- Two independent compilation guards (ADR 0035). ---
#
# A release with at least this many distinct `track_artist` identities is a
# compilation/sampler/mashup container rather than one artist's record. Its
# billed "artist" is a DJ, a label, or "Various" -- never a party to the
# music -- so its tracks must not be treated as that artist's performances.
COMPILATION_TRACK_ARTIST_THRESHOLD = 5

# ...but a documentary or video compilation has NO `track_artist` rows at all:
# it names its acts with `Featuring` track credits, so the guard above reads it
# as a one-artist album and lets its billed director inherit every track. The
# second guard is the track itself: a `track_index` naming more than this many
# distinct edge-eligible artists is a container (a DVD chapter, a festival
# film, a mixed set), not a recording.
#
# Measured over the 2026-06-01 one-hop corpus, distinct edge-eligible artists
# per track: p50=1, p90=5, p99=14, p99.9=27, max=576. The containers this
# guard exists to catch sit at 19 ("Glastonbury" DVD), 25 (its reissue) and
# 314 ("The Work Of Director Spike Jonze"); every collaboration verified by
# hand during the audit sits at <= 5 ("Man Next Door" is the widest, at 5).
# 16 clears p99 while still excluding all three containers. A large orchestral
# or big-band session can legitimately exceed it; that is an accepted false
# negative, and the recorded revisit path is to gate on release format instead
# (which this dataset does not currently parse).
MAX_ARTISTS_PER_TRACK = 16

# The one-hop snapshot does not retain Discogs' format descriptions, so it
# cannot prove that an evidence release is a studio album. It *does* retain
# track titles. A track explicitly labelled as a live, demo, remix, edit, or
# acoustic version is a poor basis for the first curated cohort: it commonly
# represents a B-side, reissue bonus track, or later reworking rather than the
# album session the player expects. Keep these out of track-scoped edges. This
# is deliberately narrow and title-based; it is not a claim to classify every
# single or every studio album.
_NON_STUDIO_TRACK_VARIANT_PATTERN = r"\b(live|demo|remix|re-?edit|acoustic|radio edit)\b"

# Temporary curation guard for evidence releases. The normalized snapshot does
# not yet preserve Discogs format descriptions, so these obvious title signals
# keep the worst compilation-like containers out of the first cohort while a
# format-aware release model is researched (ADR 0036).
_NON_STUDIO_RELEASE_TITLE_PATTERN = (
    r"\b(compilations?|samplers?|greatest hits|best of|antholog(?:y|ies)|"
    r"collections?|rarit(?:y|ies)|bootlegs?|mash[- ]?ups?|live(?:box)?|"
    r"remixes?|reissues?|soundtracks?|sound collages?|singles?|box sets?|mixtapes?)\b"
)

# Roles whose credit records a *quotation* of an artist, not a contribution
# by them: a sample, an interpolation, an excerpt. Discogs writes these as a
# bracketed qualifier ("Performer [Sample]", "Featuring [Samples From]",
# "Written-By [Interpolation]") or as the bare role "Samples". The bracket is
# load-bearing and must NOT be stripped before matching: "Sampler [Fairlight]"
# is an *instrument* credit -- a real performance -- and has to survive.
_QUOTATION_ROLE_PATTERN = r"\[[^\]]*(sample|interpolat|excerpt|contains)"
_BARE_QUOTATION_ROLES = ("samples", "sampled by")

# Roles that never justify an edge because they are not collaboration on a
# recording: authorship of an underlying composition (which links a cover to
# a songwriter, not two collaborators -- this is what made "Lennon-McCartney"
# a 36,857-release hub) and packaging/business credits. Studio roles
# (Producer, Engineer, Mixed By, Mastered By, Recorded By, Arranged By) are
# deliberately NOT here: those people were in the room. A role only counts as
# non-collaborative when EVERY comma-separated component matches, so
# "Written-By, Producer" (Butch Vig on Nevermind) stays edge-eligible; an
# unlisted component always means "keep", so this list can only under-filter.
_NON_COLLABORATIVE_ROLE_TOKENS = frozenset(
    {
        "written-by",
        "written by",
        "composed by",
        "music by",
        "lyrics by",
        "words by",
        "songwriter",
        "song by",
        "libretto by",
        "design",
        "design concept",
        "art direction",
        "artwork",
        "artwork by",
        "layout",
        "illustration",
        "photography by",
        "photography",
        "liner notes",
        "sleeve notes",
        "a&r",
        "management",
        "translation",
        "lacquer cut by",
        # Business/logistics credits. "Executive-Producer" (181,979 rows) and
        # "Coordinator" (143,312) are the two largest; a photo coordinator on
        # both Nevermind and a Coltrane reissue is what put Nirvana two hops
        # from John Coltrane in the first post-ADR-0035 rescore. Note these are
        # distinct from "Producer", which stays edge-eligible.
        "executive-producer",
        "executive producer",
        "coordinator",
        "supervised by",
        "authoring",
        "other",
        # Rework credits. A remixer, re-editor or mix DJ takes a finished
        # recording and reworks it; they were never in the room with the artist.
        # "Remix" alone holds 188,152 rows across 24,519 artists, and one
        # remixer working on two compilations bridges every artist on them --
        # Aaron Scofield ("Remix" on a Strokes track, "Edited By" on a Cure
        # track) was a top-10 curator suggestion before this.
        #
        # NOT to be confused with "Mixed By" (733,088 rows), which is studio
        # mixing of the original session and stays edge-eligible: that is Andy
        # Wallace on Nevermind. A compound role like "Remix, Producer" also
        # stays eligible, per the every-component rule -- this list can only
        # under-filter.
        "remix",
        "remixed by",
        "re-edit",
        "re-edited by",
        "edit",
        "edited by",
        "dj mix",
        "mashup",
    }
)


def _not_placeholder_sql(artist_column: str = "artist_id") -> str:
    """SQL predicate excluding hard-`exclude` placeholder identities.

    Every entry in `placeholder_artists.json` may be softened to `flag`, in
    which case the exclusion set is empty and `NOT IN ()` would be a syntax
    error -- so an empty set means "exclude nobody", not "exclude everybody".
    """
    if not NON_INDIVIDUAL_ARTIST_IDS:
        return "TRUE"
    ids = ", ".join(str(i) for i in sorted(NON_INDIVIDUAL_ARTIST_IDS))
    return f"{artist_column} NOT IN ({ids})"


def _non_studio_track_variant_sql(track_title_column: str = "track_title") -> str:
    """SQL predicate for a plainly non-studio track-title variant."""
    return (
        "NOT regexp_matches(lower(coalesce("
        f"{track_title_column}, '')), '{_NON_STUDIO_TRACK_VARIANT_PATTERN}')"
    )


def _non_studio_release_title_sql(title_column: str = "title") -> str:
    """SQL predicate for an obvious compilation-like release title."""
    return (
        "NOT regexp_matches(lower(coalesce("
        f"{title_column}, '')), '{_NON_STUDIO_RELEASE_TITLE_PATTERN}')"
    )


def edge_ineligible_role(role_text: str | None) -> bool:
    """Python mirror of `_edge_ineligible_role_sql`: True when a credit's role
    means it cannot create an edge.

    Kept in step with the SQL by `test_edge_ineligible_role_matches_the_sql`,
    which runs both over the same role strings. Used to tell a curator which of
    a release's credits actually justify a hop, versus which merely sit on the
    same record (a `Written-By` on the same track is evidence of nothing).
    """
    if role_text is None:
        return False
    lowered = role_text.lower()
    if re.search(_QUOTATION_ROLE_PATTERN, lowered):
        return True
    if lowered.strip() in _BARE_QUOTATION_ROLES:
        return True
    for component in role_text.split(","):
        stripped = re.sub(r"\[.*\]", "", component).strip().lower()
        if stripped not in _NON_COLLABORATIVE_ROLE_TOKENS:
            return False
    return True


def _edge_ineligible_role_sql(role_column: str) -> str:
    """SQL boolean: true when a credit's role means it must not create an edge.

    False for a NULL role (a main artist/track artist credit). True when the
    role is a quotation (see `_QUOTATION_ROLE_PATTERN`) or when *every*
    comma-separated component is a known `_NON_COLLABORATIVE_ROLE_TOKENS`
    entry.
    """
    tokens = ", ".join(f"'{token}'" for token in sorted(_NON_COLLABORATIVE_ROLE_TOKENS))
    return f"""(
        {role_column} IS NOT NULL
        AND (
            regexp_matches(lower({role_column}), '{_QUOTATION_ROLE_PATTERN}')
            OR lower(trim({role_column})) IN {_BARE_QUOTATION_ROLES!r}
            OR NOT list_bool_or(
                list_transform(
                    str_split({role_column}, ','),
                    x -> NOT (lower(trim(regexp_replace(x, '\\[.*\\]', ''))) IN ({tokens}))
                )
            )
        )
    )"""


def credit_edges_sql(
    *,
    max_artists_per_release: int,
    compilation_track_artist_threshold: int = COMPILATION_TRACK_ARTIST_THRESHOLD,
    max_artists_per_track: int = MAX_ARTISTS_PER_TRACK,
    credits_relation: str = "credits",
    release_format_policy_relation: str | None = None,
) -> str:
    """A SELECT producing the directed, deduplicated co-credit edge relation
    `(artist_a_id, artist_b_id, release_id)` over `credits_relation`.

    An edge means "these two artists contributed to the same recording", not
    "these two artists appear somewhere on the same disc". Sharing a
    `release_id` is emphatically NOT enough: a 46-track DJ compilation would
    otherwise make a 46-artist clique, which is exactly how a 2026-07-10 audit
    found Pink Floyd one hop from Nas. Three rules, all keyed on numeric
    `artist_id` (see ADR 0035):

    * `same_recording` -- a track's performers (its `track_artist` rows; or,
      when a track has none and the release is billed to exactly one artist,
      that artist) are joined to every other edge-eligible credit on that same
      `track_index`, PROVIDED one endpoint is a billed artist on the release.
      This is a star from the performers outward, not a clique (two `Featuring`
      guests on one DVD chapter never touch each other), and the billed-anchor
      keeps a DJ sampler's track from connecting the two unrelated artists it
      samples ("2 Worlds Collide", billed to DJ KO).
    * `co_performers` -- performers of one track are joined to each other, but
      only on an album-shaped release. On a mashup ("New Dress / The Robots")
      or a bootleg split, the co-billed "performers" of a track never played
      together.
    * `release_scope` -- an album-shaped release's billed artist is joined to
      its release-scope contributors (an album-wide producer, engineer, or
      mixer). Track-scope credits are excluded here: they belong to their own
      track's performers, not to whoever is billed on the sleeve.

    Two compilation guards apply throughout. `compilation_track_artist_threshold`
    catches releases that bill many artists per track; `max_artists_per_track`
    catches the container tracks a documentary or video compilation uses instead
    (a single DVD chapter naming 314 acts with `Featuring` credits). No rule may
    read a track above the second cap, including the single-billed fallback --
    otherwise a festival film's director inherits every act on the bill.
    """
    ineligible = _edge_ineligible_role_sql("role_text")
    not_placeholder = _not_placeholder_sql()
    studio_track = _non_studio_track_variant_sql()
    studio_release = (
        "TRUE"
        if release_format_policy_relation is not None
        else _non_studio_release_title_sql("r.title")
    )
    cap = int(max_artists_per_release)
    track_cap = int(max_artists_per_track)
    policy_join = ""
    policy_filter = ""
    if release_format_policy_relation is not None:
        policy_join = f"JOIN {release_format_policy_relation} rfp ON rfp.release_id = c.release_id"
        policy_filter = "AND rfp.decision = 'allow'"
    return f"""
    WITH edge_credits AS (
        SELECT c.release_id, c.track_index, c.track_title, c.credit_scope, c.artist_id
        FROM {credits_relation} c
        JOIN releases r USING (release_id)
        {policy_join}
        WHERE c.playable_identity AND c.artist_id IS NOT NULL AND c.artist_id > 0
          AND {not_placeholder}
          AND NOT {ineligible}
          AND {studio_release}
          {policy_filter}
    ), release_shape AS (
        SELECT release_id,
               count(DISTINCT CASE WHEN credit_scope = 'track_artist'
                                   THEN artist_id END) AS track_artist_count,
               count(DISTINCT CASE WHEN credit_scope = 'release_artist'
                                   THEN artist_id END) AS billed_artist_count,
               count(DISTINCT artist_id) AS artist_count
        FROM edge_credits GROUP BY release_id
    ), album_shaped AS (
        SELECT release_id FROM release_shape
        WHERE track_artist_count < {int(compilation_track_artist_threshold)}
          AND artist_count BETWEEN 2 AND {cap}
    ), single_billed AS (
        SELECT release_id FROM release_shape WHERE billed_artist_count = 1
    ), track_groups AS (
        SELECT release_id, track_index, min(track_title) AS track_title FROM edge_credits
        WHERE track_index IS NOT NULL
        GROUP BY release_id, track_index
        HAVING count(DISTINCT artist_id) <= {track_cap}
    ), billed_artists AS (
        SELECT DISTINCT release_id, artist_id FROM edge_credits
        WHERE credit_scope = 'release_artist'
    ), track_performers AS (
        SELECT release_id, track_index, artist_id FROM edge_credits
        WHERE credit_scope = 'track_artist' AND track_index IS NOT NULL
        UNION
        SELECT t.release_id, t.track_index, billed.artist_id
        FROM (SELECT DISTINCT release_id, track_index FROM edge_credits
              WHERE track_index IS NOT NULL) t
        JOIN track_groups tg USING (release_id, track_index)
        JOIN single_billed USING (release_id)
        -- `album_shaped` as well as `single_billed`: without it a documentary
        -- or festival film billed to one director (Julien Temple on the
        -- "Glastonbury" DVD, 21 track artists) inherits every track and stars
        -- out to each featured band.
        JOIN album_shaped USING (release_id)
        JOIN edge_credits billed USING (release_id)
        WHERE billed.credit_scope = 'release_artist'
          AND NOT EXISTS (
              SELECT 1 FROM edge_credits x
              WHERE x.release_id = t.release_id AND x.track_index = t.track_index
                AND x.credit_scope = 'track_artist')
    ), same_recording AS (
        -- One endpoint must be the artist the record is actually BY. A real
        -- feature connects a billed artist to a guest (Wu-Tang billed on "The
        -- W" ↔ Nas "Featuring"; Lauryn Hill billed on her comp ↔ A Tribe
        -- Called Quest). A mashup or DJ sampler connects two artists NEITHER of
        -- whom is billed -- the billed act is the bootlegger ("2 Worlds
        -- Collide" is billed to DJ KO; its track co-credits Nas and Red Hot
        -- Chili Peppers, who never met). Without this anchor every mashup track
        -- is a false collaboration. Real features lost here (a guest spot that
        -- exists only on a various-artists compilation in this corpus) survive
        -- via the same feature on the lead artist's own, billed release.
        SELECT p.artist_id AS artist_a_id, c.artist_id AS artist_b_id, c.release_id
        FROM track_performers p
        JOIN edge_credits c USING (release_id, track_index)
        JOIN track_groups USING (release_id, track_index)
        WHERE p.artist_id <> c.artist_id AND c.credit_scope <> 'track_artist'
          AND {studio_track.replace("track_title", "c.track_title")}
          AND (
              EXISTS (SELECT 1 FROM billed_artists b
                      WHERE b.release_id = p.release_id AND b.artist_id = p.artist_id)
              OR EXISTS (SELECT 1 FROM billed_artists b
                         WHERE b.release_id = c.release_id AND b.artist_id = c.artist_id)
          )
    ), co_performers AS (
        -- Both performers must be BILLED on the release. A duet or a split
        -- single bills both acts; a mashup bootleg bills the bootlegger
        -- ("Satanik Mashups Vol I" is billed to "Inhumanz", and its track
        -- "Shoot The War Pigs" co-credits Nas and Black Sabbath, who never
        -- met). Without this, every mashup track is a false collaboration.
        SELECT p.artist_id AS artist_a_id, q.artist_id AS artist_b_id, p.release_id
        FROM track_performers p
        JOIN track_performers q USING (release_id, track_index)
        JOIN album_shaped USING (release_id)
        JOIN track_groups tg USING (release_id, track_index)
        JOIN billed_artists bp ON bp.release_id = p.release_id AND bp.artist_id = p.artist_id
        JOIN billed_artists bq ON bq.release_id = q.release_id AND bq.artist_id = q.artist_id
        WHERE p.artist_id <> q.artist_id
          AND {studio_track.replace("track_title", "tg.track_title")}
    ), release_scope AS (
        SELECT billed.artist_id AS artist_a_id, c.artist_id AS artist_b_id, billed.release_id
        FROM edge_credits billed
        JOIN edge_credits c USING (release_id)
        JOIN album_shaped USING (release_id)
        WHERE billed.credit_scope = 'release_artist'
          AND c.credit_scope = 'release_credit'
          AND billed.artist_id <> c.artist_id
    ), directed AS (
        SELECT artist_a_id, artist_b_id, release_id FROM same_recording
        UNION ALL SELECT artist_b_id, artist_a_id, release_id FROM same_recording
        UNION ALL SELECT artist_a_id, artist_b_id, release_id FROM co_performers
        UNION ALL SELECT artist_a_id, artist_b_id, release_id FROM release_scope
        UNION ALL SELECT artist_b_id, artist_a_id, release_id FROM release_scope
    )
    SELECT artist_a_id, artist_b_id, min(release_id) AS release_id
    FROM directed GROUP BY artist_a_id, artist_b_id
    """


_CREDIT_COLUMNS = (
    "snapshot_date",
    "release_id",
    "track_index",
    "track_path",
    "track_position",
    "track_title",
    "credit_scope",
    "artist_id",
    "name",
    "anv",
    "join_text",
    "role_text",
    "credited_tracks_text",
    "is_linked",
    "playable_identity",
)


def read_parquet_sql(glob: str) -> str:
    """`read_parquet(...)` with Hive partitioning disabled.

    Every dataset in this project stores tables under
    `.../snapshot=<date>/table=<name>/*.parquet` -- DuckDB's default
    partition auto-detection reads those directory segments as columns and
    silently injects `snapshot`/`table` into every row of a `SELECT *`.
    """
    return f"read_parquet('{glob}', hive_partitioning = false)"


class GraphError(RuntimeError):
    """Raised when a graph can't be opened or queried as requested."""


class FrontierTooLargeError(GraphError):
    """Raised when `find_path`'s BFS hits an artist whose fan-out exceeds
    `max_frontier_expansion` and the target was never reached without
    expanding it. The result is inconclusive, not a confirmed absence of a
    path -- callers must not treat this the same as a `None` return."""

    def __init__(self, capped_artist_ids: frozenset[int]):
        self.capped_artist_ids = capped_artist_ids
        super().__init__(
            f"search hit artist(s) {sorted(capped_artist_ids)} exceeding "
            "max_frontier_expansion before reaching the target; result is "
            "inconclusive, not a confirmed no-path"
        )


@dataclass(frozen=True, slots=True)
class Hop:
    release_id: int
    artist_a_id: int
    artist_b_id: int


@dataclass(frozen=True, slots=True)
class EvidencePath:
    from_artist_id: int
    to_artist_id: int
    hops: tuple[Hop, ...]


class CreditGraph:
    """A lazy, DuckDB-backed view over one dataset's playable-identity credits."""

    def __init__(
        self,
        connection: duckdb.DuckDBPyConnection,
        *,
        max_artists_per_release: int,
        edges_built: bool = True,
    ):
        self._connection = connection
        self._max_artists_per_release = max_artists_per_release
        self._masters_attached = False
        self._edges_built = edges_built

    def _require_edges(self) -> None:
        if not self._edges_built:
            raise GraphError(
                "this CreditGraph was opened with build_edges=False -- it can read "
                "evidence (credit_rows, release, artist_name) but cannot traverse"
            )

    @classmethod
    def open(
        cls,
        dataset_root: Path,
        *,
        memory_limit: str = "1GB",
        threads: int = 2,
        max_artists_per_release: int = 50,
        temp_dir: Path | None = None,
        build_edges: bool = True,
        release_format_policy: Path | None = None,
    ) -> CreditGraph:
        """`build_edges=False` skips materializing `credit_edges` -- the ~2.5
        minute step on the real corpus. The result can read evidence rows
        (`credit_rows`, `release`, `artist_name`) but raises on any traversal
        call. Used by the editorial packet, which explains hops that were
        already found rather than searching for new ones."""
        dataset_root = Path(dataset_root)
        manifest_path = dataset_root / "manifest.json"
        if not manifest_path.exists():
            raise GraphError(f"no manifest.json under {dataset_root}")

        credits_glob = str(dataset_root / "table=credits" / "*.parquet")
        releases_glob = str(dataset_root / "table=releases" / "*.parquet")

        # Without an explicit temp_directory, DuckDB spills to `.tmp/`
        # relative to the process's CWD -- on a host where CWD sits on a
        # small boot disk and the real dataset lives on a larger separate
        # volume, that silently risks a disk-full crash on a query that
        # spills. Default alongside the dataset itself, which is already
        # known to have room for a dataset this size.
        spill_dir = temp_dir if temp_dir is not None else dataset_root / ".graph-core-tmp"
        spill_dir.mkdir(parents=True, exist_ok=True)

        connection = duckdb.connect(database=":memory:")
        connection.execute(f"SET memory_limit = '{memory_limit}'")
        connection.execute(f"SET threads = {int(threads)}")
        connection.execute(f"SET temp_directory = '{spill_dir}'")

        try:
            connection.execute(
                f"CREATE VIEW credits AS SELECT * FROM {read_parquet_sql(credits_glob)}"
            )
            connection.execute(
                f"CREATE VIEW releases AS SELECT * FROM {read_parquet_sql(releases_glob)}"
            )
        except duckdb.IOException as exc:
            raise GraphError(f"could not open dataset at {dataset_root}: {exc}") from exc

        policy_relation: str | None = None
        if release_format_policy is not None:
            try:
                policy_payload = json.loads(Path(release_format_policy).read_text())
                if policy_payload.get("snapshot_date") != str(
                    json.loads(manifest_path.read_text())["snapshot_date"]
                ):
                    raise GraphError("release format policy snapshot does not match dataset")
                if policy_payload.get("policy_name") != "studio-album-v1":
                    raise GraphError("unsupported release format policy")
                classifications = policy_payload["classifications"]
                connection.execute(
                    "CREATE TABLE release_format_policy (release_id BIGINT, decision VARCHAR)"
                )
                connection.executemany(
                    "INSERT INTO release_format_policy VALUES (?, ?)",
                    [(int(row["release_id"]), str(row["decision"])) for row in classifications],
                )
                policy_relation = "release_format_policy"
            except (OSError, KeyError, TypeError, ValueError) as exc:
                raise GraphError(f"could not load release format policy: {exc}") from exc

        credit_count = connection.execute("SELECT count(*) FROM credits").fetchone()
        if credit_count is None or credit_count[0] == 0:
            raise GraphError(f"no credit rows found under {dataset_root}")

        # Materialized TABLEs, not VIEWs: every BFS hop re-queries these
        # relations with a fresh WHERE/JOIN, and left as views each of those
        # queries would re-scan and re-filter the full underlying credits
        # Parquet data from scratch. Plain TABLE, not TEMP TABLE: DuckDB's
        # TEMP schema is connection/cursor-local, so a `cursor()` (see below)
        # can't see a TEMP TABLE created on its parent connection -- a plain
        # table in an in-memory database is exactly as ephemeral (gone when
        # the connection closes) but lives in the shared `main` schema every
        # cursor can read.
        #
        # `linked_credits` is NOT the traversal relation -- `credit_edges` is.
        # It survives only to answer "what is this artist_id's display name"
        # and to report corpus size; joining it to itself on `release_id` is
        # what produced the compilation cliques ADR 0035 removes.
        connection.execute(
            "CREATE TABLE linked_credits AS "
            "SELECT release_id, artist_id, name FROM credits "
            "WHERE playable_identity AND artist_id IS NOT NULL AND artist_id > 0 "
            f"AND {_not_placeholder_sql()}"
        )
        if build_edges:
            connection.execute(
                "CREATE TABLE credit_edges AS "
                + credit_edges_sql(
                    max_artists_per_release=max_artists_per_release,
                    release_format_policy_relation=policy_relation,
                )
            )
            connection.execute("CREATE INDEX credit_edges_a ON credit_edges (artist_a_id)")
        return cls(
            connection,
            max_artists_per_release=max_artists_per_release,
            edges_built=build_edges,
        )

    def attach_masters(self, masters_root: Path) -> None:
        masters_root = Path(masters_root)
        masters_glob = str(masters_root / "table=masters" / "*.parquet")
        try:
            self._connection.execute(
                f"CREATE VIEW masters AS SELECT * FROM {read_parquet_sql(masters_glob)}"
            )
        except duckdb.IOException as exc:
            raise GraphError(f"could not open masters dataset at {masters_root}: {exc}") from exc
        self._masters_attached = True

    @property
    def masters_attached(self) -> bool:
        return self._masters_attached

    def cursor(self) -> CreditGraph:
        """A new `CreditGraph` sharing this one's underlying database --
        same materialized `linked_credits`/`credit_edges` tables, same
        `credits`/`releases` views -- via an independent DuckDB cursor. Safe
        to use concurrently from another thread: each cursor has its own
        query/interrupt state, per DuckDB's own concurrency model, while
        reading the same already-materialized data with no re-scan cost."""
        return CreditGraph(
            self._connection.cursor(),
            max_artists_per_release=self._max_artists_per_release,
            edges_built=self._edges_built,
        )

    def interrupt(self) -> None:
        """Cancel the currently running query on this graph's connection, if
        any. DuckDB's own supported cancellation primitive -- lets a caller
        enforce a wall-clock timeout around a single expensive call (e.g.
        `neighbors()`/`find_path()`) without corrupting the connection for
        subsequent calls."""
        self._connection.interrupt()

    def degree(self, artist_id: int) -> int:
        """`artist_id`'s exact traversal fan-out: how many artists it has an
        edge to. Now that `credit_edges` is materialized this is a direct
        count, not the credit-row-count proxy the old release-container
        traversal had to estimate with."""
        self._require_edges()
        row = self._connection.execute(
            "SELECT count(*) FROM credit_edges WHERE artist_a_id = ?", [artist_id]
        ).fetchone()
        assert row is not None
        return int(row[0])

    # One INSERT statement's worth of ids for `_scratch_id_table`. Bounds the
    # generated SQL text (~7 bytes/id -> ~350KB/statement) without giving up
    # the bulk win; scaling stays linear well past this size.
    _SCRATCH_INSERT_CHUNK = 50_000

    def _scratch_id_table(self, artist_ids: Sequence[int]) -> str:
        """A uniquely-named TEMP TABLE holding `artist_ids`, for a batched
        query's `JOIN`/`IN (SELECT ...)` -- callers are responsible for
        dropping it. TEMP TABLEs are cursor-local (not shared database-wide,
        unlike `linked_credits`/`credit_edges`), which is exactly what
        we want here: pure per-call scratch state, never meant to be visible
        to another cursor.

        Population is one inline-literal `unnest` INSERT per chunk, not
        per-row `executemany`: measured on a real hub frontier, 17,612 ids
        took 54.3s to insert row-by-row while the batched query they fed took
        1.06s -- the insert, not the query, was blowing per-seed timeout
        budgets. Inline int literals measured ~170x faster than executemany
        and ~20x faster than a parameterized list bind at that size; `int()`
        coercion below keeps the inlining injection-safe."""
        table = f"scratch_ids_{uuid.uuid4().hex}"
        self._connection.execute(f"CREATE TEMP TABLE {table} (artist_id BIGINT)")
        for start in range(0, len(artist_ids), self._SCRATCH_INSERT_CHUNK):
            chunk = artist_ids[start : start + self._SCRATCH_INSERT_CHUNK]
            literals = ",".join(str(int(a)) for a in chunk)
            self._connection.execute(f"INSERT INTO {table} SELECT unnest([{literals}]::BIGINT[])")
        return table

    def degrees(self, artist_ids: Sequence[int]) -> dict[int, int]:
        """Batched `degree`: one query for the whole list instead of one per
        artist. An artist_id with no edges is simply absent from the result --
        callers should treat a missing key as 0, not an error."""
        self._require_edges()
        if not artist_ids:
            return {}
        table = self._scratch_id_table(artist_ids)
        try:
            rows = self._connection.execute(
                "SELECT artist_a_id, count(*) FROM credit_edges "
                f"WHERE artist_a_id IN (SELECT artist_id FROM {table}) "
                "GROUP BY artist_a_id"
            ).fetchall()
        finally:
            self._connection.execute(f"DROP TABLE {table}")
        return {int(artist_id): int(count) for artist_id, count in rows}

    def neighbors(self, artist_id: int) -> dict[int, tuple[int, ...]]:
        """`artist_id`'s neighbors, each mapped to the single deterministic
        release that evidences the edge (the lowest `release_id` among the
        releases that justify it, per `credit_edges_sql`). The value stays a
        tuple for callers that already index `[0]`."""
        self._require_edges()
        rows = self._connection.execute(
            "SELECT artist_b_id, release_id FROM credit_edges "
            "WHERE artist_a_id = ? ORDER BY artist_b_id",
            [artist_id],
        ).fetchall()
        return {int(row[0]): (int(row[1]),) for row in rows}

    def neighbors_batch(self, artist_ids: Sequence[int]) -> dict[int, dict[int, tuple[int, ...]]]:
        """Batched `neighbors`: one scan for every requested artist_id's
        fan-out instead of one query each. Every requested artist_id is a key
        in the result, even with an empty dict value, so callers can't mistake
        "not yet queried" for "queried, no neighbors"."""
        self._require_edges()
        if not artist_ids:
            return {}
        table = self._scratch_id_table(artist_ids)
        try:
            rows = self._connection.execute(
                "SELECT e.artist_a_id, e.artist_b_id, e.release_id "
                "FROM credit_edges e "
                f"JOIN {table} f ON f.artist_id = e.artist_a_id "
                "ORDER BY e.artist_a_id, e.artist_b_id"
            ).fetchall()
        finally:
            self._connection.execute(f"DROP TABLE {table}")
        result: dict[int, dict[int, tuple[int, ...]]] = {int(a): {} for a in artist_ids}
        for a_id, b_id, release_id in rows:
            result[int(a_id)][int(b_id)] = (int(release_id),)
        return result

    def find_path(
        self,
        from_artist_id: int,
        to_artist_id: int,
        *,
        max_hops: int = 4,
        max_frontier_expansion: int | None = None,
    ) -> EvidencePath | None:
        """Bounded BFS. `max_frontier_expansion`, when given, is a degree
        threshold (see `degree`): a frontier artist above it is excluded from
        *expansion* this call (its own edges are never explored), though it
        can still be *reached* as a target via another artist's edges. If the
        target is never reached and any artist was excluded this way, raises
        `FrontierTooLargeError` instead of returning None -- the search result
        is inconclusive, not a confirmed no-path, and must never be reported
        as one."""
        self._require_edges()
        if from_artist_id == to_artist_id:
            raise GraphError("from_artist_id and to_artist_id must differ")

        suffix = uuid.uuid4().hex
        frontier_table = f"frontier_{suffix}"
        visited_table = f"visited_{suffix}"
        self._connection.execute(f"CREATE TEMP TABLE {frontier_table} (artist_id BIGINT)")
        self._connection.execute(f"CREATE TEMP TABLE {visited_table} (artist_id BIGINT)")
        self._connection.execute(f"INSERT INTO {frontier_table} VALUES (?)", [from_artist_id])
        self._connection.execute(f"INSERT INTO {visited_table} VALUES (?)", [from_artist_id])

        parent: dict[int, tuple[int, int]] = {}  # artist_id -> (parent_artist_id, release_id)
        capped_artist_ids: set[int] = set()
        try:
            for _ in range(max_hops):
                expand_from_table = frontier_table
                safe_table = f"safe_frontier_{suffix}"
                if max_frontier_expansion is not None:
                    degrees = self._connection.execute(
                        "SELECT artist_a_id, count(*) FROM credit_edges "
                        f"WHERE artist_a_id IN (SELECT artist_id FROM {frontier_table}) "
                        "GROUP BY artist_a_id"
                    ).fetchall()
                    newly_capped = {
                        int(artist_id)
                        for artist_id, edge_count in degrees
                        if edge_count > max_frontier_expansion
                    }
                    if newly_capped:
                        capped_artist_ids |= newly_capped
                        placeholders = ", ".join(str(a) for a in sorted(newly_capped))
                        self._connection.execute(
                            f"CREATE TEMP TABLE {safe_table} AS "
                            f"SELECT artist_id FROM {frontier_table} "
                            f"WHERE artist_id NOT IN ({placeholders})"
                        )
                        expand_from_table = safe_table

                level = self._connection.execute(
                    "SELECT e.artist_a_id, e.artist_b_id, e.release_id "
                    "FROM credit_edges e "
                    f"JOIN {expand_from_table} f ON f.artist_id = e.artist_a_id "
                    f"WHERE e.artist_b_id NOT IN (SELECT artist_id FROM {visited_table}) "
                    "ORDER BY e.artist_a_id, e.artist_b_id"
                ).fetchall()

                if expand_from_table != frontier_table:
                    self._connection.execute(f"DROP TABLE {expand_from_table}")

                if not level:
                    if capped_artist_ids:
                        raise FrontierTooLargeError(frozenset(capped_artist_ids))
                    return None

                next_frontier: list[int] = []
                seen_this_level: set[int] = set()
                for from_id, to_id, release_id in level:
                    to_id = int(to_id)
                    if to_id in seen_this_level:
                        continue
                    seen_this_level.add(to_id)
                    parent[to_id] = (int(from_id), int(release_id))
                    next_frontier.append(to_id)
                    if to_id == to_artist_id:
                        return self._reconstruct_path(from_artist_id, to_artist_id, parent)

                self._connection.execute(f"DELETE FROM {frontier_table}")
                self._connection.executemany(
                    f"INSERT INTO {frontier_table} VALUES (?)",
                    [[a] for a in next_frontier],
                )
                self._connection.executemany(
                    f"INSERT INTO {visited_table} VALUES (?)",
                    [[a] for a in next_frontier],
                )

            if capped_artist_ids:
                raise FrontierTooLargeError(frozenset(capped_artist_ids))
            return None
        finally:
            self._connection.execute(f"DROP TABLE {frontier_table}")
            self._connection.execute(f"DROP TABLE {visited_table}")

    @staticmethod
    def _reconstruct_path(
        from_artist_id: int, to_artist_id: int, parent: dict[int, tuple[int, int]]
    ) -> EvidencePath:
        hops: list[Hop] = []
        current = to_artist_id
        while current != from_artist_id:
            parent_id, release_id = parent[current]
            hops.append(Hop(release_id=release_id, artist_a_id=parent_id, artist_b_id=current))
            current = parent_id
        hops.reverse()
        return EvidencePath(
            from_artist_id=from_artist_id, to_artist_id=to_artist_id, hops=tuple(hops)
        )

    def credit_rows(self, release_id: int, artist_ids: set[int]) -> list[dict[str, Any]]:
        placeholders = ", ".join("?" for _ in artist_ids)
        columns = ", ".join(_CREDIT_COLUMNS)
        rows = self._connection.execute(
            f"SELECT {columns} FROM credits "
            f"WHERE release_id = ? AND artist_id IN ({placeholders}) "
            "ORDER BY ALL",
            [release_id, *sorted(artist_ids)],
        ).fetchall()
        return [dict(zip(_CREDIT_COLUMNS, row, strict=True)) for row in rows]

    def release(self, release_id: int) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT * FROM releases WHERE release_id = ?", [release_id]
        ).fetchone()
        if row is None:
            return None
        columns = [d[0] for d in self._connection.description]
        return dict(zip(columns, row, strict=True))

    def find_release_by_title_artist(self, title: str, artist_name: str) -> dict[str, Any] | None:
        """The release-artist-scope playable credit matching an exact title + name/ANV.

        Prefers the master's main release, then the lowest release_id, so album
        matching is deterministic. Used to resolve an editorial {artist, title}
        query against real catalog rows.
        """
        row = self._connection.execute(
            "SELECT r.release_id, r.title, r.released, r.master_id, c.artist_id, c.name "
            "FROM releases r "
            "JOIN credits c USING (release_id) "
            "WHERE lower(r.title) = lower(?) "
            "AND c.credit_scope = 'release_artist' AND c.playable_identity "
            "AND (lower(c.name) = lower(?) OR lower(c.anv) = lower(?)) "
            "ORDER BY (r.master_is_main_release IS NOT TRUE), r.release_id",
            [title, artist_name, artist_name],
        ).fetchone()
        if row is None:
            return None
        return {
            "release_id": int(row[0]),
            "title": row[1],
            "released": row[2],
            "master_id": int(row[3]) if row[3] is not None else None,
            "artist_id": int(row[4]),
            "name": row[5],
        }

    def find_release_by_id_hint(
        self,
        *,
        release_id: int | None = None,
        master_id: int | None = None,
        artist_hint: str | None = None,
    ) -> dict[str, Any] | None:
        """Resolve a release from an explicit Discogs release_id or master_id,
        as opposed to `find_release_by_title_artist`'s text match. Exactly one
        of `release_id`/`master_id` should be given; `release_id` takes
        precedence if both are.

        A `release_id` that turns out to be a non-main pressing of a master is
        redirected to that master's actual main release, matching
        `find_release_by_title_artist`'s own main-release preference -- an
        explicit release_id hint should not overfit to a particular reissue.
        Returns None if the hint doesn't resolve to anything in this dataset
        (never guessed).
        """
        if release_id is not None:
            anchor = self._connection.execute(
                "SELECT master_id, master_is_main_release FROM releases WHERE release_id = ?",
                [release_id],
            ).fetchone()
            if anchor is None:
                return None
            anchor_master_id, is_main = anchor
            if anchor_master_id is None or is_main:
                return self._release_with_artist(release_id, artist_hint)
            master_id = int(anchor_master_id)

        if master_id is None:
            raise GraphError("find_release_by_id_hint needs release_id or master_id")

        main = self._connection.execute(
            "SELECT release_id FROM releases WHERE master_id = ? "
            "ORDER BY (master_is_main_release IS NOT TRUE), release_id LIMIT 1",
            [master_id],
        ).fetchone()
        if main is None:
            return None
        return self._release_with_artist(int(main[0]), artist_hint)

    def _release_with_artist(
        self, release_id: int, artist_hint: str | None
    ) -> dict[str, Any] | None:
        rows = self._connection.execute(
            "SELECT r.release_id, r.title, r.released, r.master_id, "
            "c.artist_id, c.name, c.anv "
            "FROM releases r JOIN credits c USING (release_id) "
            "WHERE r.release_id = ? AND c.credit_scope = 'release_artist' "
            "AND c.playable_identity "
            "ORDER BY c.artist_id",
            [release_id],
        ).fetchall()
        if not rows:
            return None

        chosen = rows[0]
        if artist_hint:
            lowered_hint = artist_hint.lower()
            for row in rows:
                if (row[5] and row[5].lower() == lowered_hint) or (
                    row[6] and row[6].lower() == lowered_hint
                ):
                    chosen = row
                    break

        return {
            "release_id": int(chosen[0]),
            "title": chosen[1],
            "released": chosen[2],
            "master_id": int(chosen[3]) if chosen[3] is not None else None,
            "artist_id": int(chosen[4]),
            "name": chosen[5],
        }

    def master(self, master_id: int) -> dict[str, Any] | None:
        """Row from the attached masters table, or None if not attached/found."""
        if not self._masters_attached:
            return None
        row = self._connection.execute(
            "SELECT title, year FROM masters WHERE master_id = ?", [master_id]
        ).fetchone()
        return None if row is None else {"title": row[0], "year": row[1]}

    def placeholder_artist_candidates(self) -> list[dict[str, Any]]:
        """Playable identities whose name looks like a placeholder ("Various",
        "Unknown Artist", "Anonymous", "Trad.", …), with their release counts.

        A maintenance aid, not a filter: `credit_edges` excludes placeholders by
        the numeric `NON_INDIVIDUAL_ARTIST_IDS` list, and nothing here changes
        that. Run this against a new snapshot and review anything it reports
        that the list does not already contain -- a real band can be named
        "Anonymous", so the promotion from candidate to exclusion is a human
        decision. Reads `credits`, not `credit_edges`, so already-excluded
        identities still show up (that is the point: it should re-find the
        whole list).
        """
        rows = self._connection.execute(
            "SELECT artist_id, any_value(name), count(DISTINCT release_id) "
            "FROM credits "
            "WHERE playable_identity AND artist_id IS NOT NULL AND artist_id > 0 "
            f"AND regexp_matches(lower(name), '{PLACEHOLDER_NAME_PATTERN}') "
            "GROUP BY artist_id ORDER BY count(DISTINCT release_id) DESC, artist_id"
        ).fetchall()
        return [
            {
                "artist_id": int(artist_id),
                "name": str(name),
                "release_count": int(release_count),
                "already_excluded": int(artist_id) in NON_INDIVIDUAL_ARTIST_IDS,
            }
            for artist_id, name, release_count in rows
        ]

    def artist_name(self, artist_id: int) -> str | None:
        row = self._connection.execute(
            "SELECT name FROM linked_credits WHERE artist_id = ? "
            "GROUP BY name ORDER BY count(*) DESC, name LIMIT 1",
            [artist_id],
        ).fetchone()
        return None if row is None else str(row[0])

    def stats(self) -> dict[str, int]:
        """Corpus size (`linked_credits`) alongside traversable graph size
        (`credit_edges`). The gap between `artist_count` and
        `connected_artist_count` is artists who hold a playable credit but
        contributed to no recording alongside anyone else."""
        self._require_edges()
        artist_count = self._connection.execute(
            "SELECT count(DISTINCT artist_id) FROM linked_credits"
        ).fetchone()
        release_count = self._connection.execute(
            "SELECT count(DISTINCT release_id) FROM linked_credits"
        ).fetchone()
        connected = self._connection.execute(
            "SELECT count(DISTINCT artist_a_id) FROM credit_edges"
        ).fetchone()
        edge_count = self._connection.execute("SELECT count(*) FROM credit_edges").fetchone()
        evidence_releases = self._connection.execute(
            "SELECT count(DISTINCT release_id) FROM credit_edges"
        ).fetchone()
        assert artist_count is not None
        assert release_count is not None
        assert connected is not None
        assert edge_count is not None
        assert evidence_releases is not None
        return {
            "artist_count": int(artist_count[0]),
            "release_count": int(release_count[0]),
            "connected_artist_count": int(connected[0]),
            # `credit_edges` holds both directions of every edge.
            "edge_count": int(edge_count[0]) // 2,
            "evidence_release_count": int(evidence_releases[0]),
        }

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> CreditGraph:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
