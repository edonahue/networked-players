"""Command-line entry point for the initial catalog vertical slice."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from pathlib import Path

from . import __version__
from .discogs.download import download_file
from .discogs.manifest import DumpKind, SnapshotManifest, build_manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="networked-players-catalog")
    subparsers = parser.add_subparsers(dest="command", required=True)

    manifest = subparsers.add_parser("manifest", help="create an offline monthly dump manifest")
    manifest.add_argument("--snapshot", required=True, help="monthly date as YYYYMM01")
    manifest.add_argument("--output", type=Path, required=True)
    manifest.add_argument("--base-url", default=None)
    manifest.add_argument("--terms-reviewed-at", default=date.today().isoformat())

    download = subparsers.add_parser("download", help="download one object from a manifest")
    download.add_argument("--manifest", type=Path, required=True)
    download.add_argument("--kind", choices=[kind.value for kind in DumpKind], required=True)
    download.add_argument("--raw-dir", type=Path, required=True)

    parse = subparsers.add_parser("parse-releases", help="stream a release dump into Parquet")
    parse.add_argument("--input", type=Path, required=True)
    parse.add_argument("--snapshot", required=True)
    parse.add_argument("--source-url", required=True)
    parse.add_argument("--output-root", type=Path, required=True)
    parse.add_argument("--max-releases", type=int)
    parse.add_argument("--chunk-releases", type=int, default=5_000)
    parse.add_argument("--overwrite", action="store_true")

    parse_masters = subparsers.add_parser(
        "parse-masters", help="stream a masters dump into Parquet"
    )
    parse_masters.add_argument("--input", type=Path, required=True)
    parse_masters.add_argument("--snapshot", required=True)
    parse_masters.add_argument("--source-url", required=True)
    parse_masters.add_argument("--output-root", type=Path, required=True)
    parse_masters.add_argument("--max-masters", type=int)
    parse_masters.add_argument("--chunk-masters", type=int, default=10_000)
    parse_masters.add_argument("--overwrite", action="store_true")

    parse_artist_relations = subparsers.add_parser(
        "parse-artist-relations",
        help="stream an artists dump's <groups>/<members> tags into Parquet",
    )
    parse_artist_relations.add_argument("--input", type=Path, required=True)
    parse_artist_relations.add_argument("--snapshot", required=True)
    parse_artist_relations.add_argument("--source-url", required=True)
    parse_artist_relations.add_argument("--output-root", type=Path, required=True)
    parse_artist_relations.add_argument("--max-artists", type=int)
    parse_artist_relations.add_argument("--chunk-artists", type=int, default=50_000)
    parse_artist_relations.add_argument("--overwrite", action="store_true")

    artist_family = subparsers.add_parser(
        "build-artist-family-exclusions",
        help="build a scoped person->group_act_ids exclusion artifact from parsed artist relations",
    )
    artist_family.add_argument("--dataset", type=Path, required=True)
    artist_family.add_argument(
        "--artist-ids-file",
        type=Path,
        required=True,
        help="JSON file containing a flat array of artist IDs to scope the artifact to",
    )
    artist_family.add_argument("--snapshot", required=True)
    artist_family.add_argument("--output", type=Path, required=True)

    validate = subparsers.add_parser("validate", help="validate a normalized snapshot with DuckDB")
    validate.add_argument("--dataset", type=Path, required=True)

    validate_masters = subparsers.add_parser(
        "validate-masters", help="validate a parsed masters dataset with DuckDB"
    )
    validate_masters.add_argument("--dataset", type=Path, required=True)

    format_policy = subparsers.add_parser(
        "classify-release-formats",
        help="classify normalized release formats with a named local policy",
    )
    format_policy.add_argument("--dataset", type=Path, required=True)
    format_policy.add_argument("--output", type=Path, required=True)
    format_policy.add_argument("--policy", default="studio-album-v1")

    format_shadow = subparsers.add_parser(
        "compare-release-format-policy",
        help="compare the title safeguard with a generated release-format policy",
    )
    format_shadow.add_argument("--dataset", type=Path, required=True)
    format_shadow.add_argument("--policy", type=Path, required=True)
    format_shadow.add_argument("--output", type=Path, required=True)

    format_index = subparsers.add_parser(
        "build-release-format-scoring-index",
        help="write a compact allowed-release index from a review policy",
    )
    format_index.add_argument("--policy", type=Path, required=True)
    format_index.add_argument("--output", type=Path, required=True)

    format_migration = subparsers.add_parser(
        "migrate-release-formats",
        help="copy a dataset and add structured release formats from a local dump",
    )
    format_migration.add_argument("--input-dataset", type=Path, required=True)
    format_migration.add_argument("--raw-dump", type=Path, required=True)
    format_migration.add_argument("--snapshot", required=True)
    format_migration.add_argument("--source-url", required=True)
    format_migration.add_argument("--output-root", type=Path, required=True)
    format_migration.add_argument("--chunk-rows", type=int, default=50_000)
    format_migration.add_argument("--overwrite", action="store_true")

    import_seed = subparsers.add_parser(
        "import-seed", help="reduce a local Discogs collection export to a release-ID seed"
    )
    import_seed.add_argument("--input", type=Path, required=True)
    import_seed.add_argument("--output", type=Path, required=True)
    import_seed.add_argument("--source", default="discogs-collection-export-csv")

    expand = subparsers.add_parser(
        "expand-one-hop",
        help="expand the private seed one hop over a parsed snapshot (Milestone 5)",
    )
    expand.add_argument("--seed", type=Path, default=Path("data/private/discogs-seed.json"))
    expand.add_argument("--dataset", type=Path, required=True, help="parsed snapshot root")
    expand.add_argument("--output-root", type=Path, required=True)
    expand.add_argument("--memory-limit", default="3GB", help="DuckDB memory ceiling")
    expand.add_argument("--threads", type=int, default=2)
    expand.add_argument("--temp-dir", type=Path, default=None, help="DuckDB spill directory")
    expand.add_argument(
        "--max-retained-releases",
        type=int,
        default=None,
        help="abort (writing nothing) if the retained release count exceeds this bound",
    )
    expand.add_argument("--overwrite", action="store_true")

    build_demo = subparsers.add_parser(
        "build-demo-challenge",
        help="fetch curated Discogs API releases and emit a real challenge.v1-shaped artifact",
    )
    build_demo.add_argument("--seed", type=Path, default=Path("data/private/discogs-seed.json"))
    build_demo.add_argument(
        "--cache-dir", type=Path, default=Path("data/private/discogs-api-cache")
    )
    build_demo.add_argument("--output", type=Path, required=True)
    build_demo.add_argument("--snapshot", default=date.today().strftime("%Y%m%d"))
    build_demo.add_argument("--max-paths", type=int, default=8)
    build_demo.add_argument("--seed-artists", type=int, default=10)
    build_demo.add_argument("--request-delay", type=float, default=1.1)

    build_challenge = subparsers.add_parser(
        "build-challenge-from-dump",
        help="build a real, album-centered challenge.v2 artifact from a one-hop dataset",
    )
    build_challenge.add_argument(
        "--onehop-root", type=Path, required=True, help="one-hop snapshot root"
    )
    build_challenge.add_argument(
        "--albums", type=Path, default=Path("data/albums/top-albums-v1.json")
    )
    build_challenge.add_argument(
        "--masters-root", type=Path, default=None, help="optional parsed masters snapshot root"
    )
    build_challenge.add_argument("--output", type=Path, required=True)
    build_challenge.add_argument("--max-paths", type=int, default=12)
    build_challenge.add_argument("--max-hops", type=int, default=4)
    build_challenge.add_argument(
        "--max-frontier-expansion",
        type=int,
        default=300,
        help="bound each find_path search's per-hop degree (same default as the cohort scorer); "
        "0 or negative disables the bound",
    )
    build_challenge.add_argument("--max-artists-per-release", type=int, default=50)
    build_challenge.add_argument("--memory-limit", default="1GB")
    build_challenge.add_argument("--threads", type=int, default=2)
    build_challenge.add_argument(
        "--max-workers",
        type=int,
        default=1,
        help="find_path() candidate pairs concurrently across this many DuckDB cursors; "
        "default 1 preserves the original sequential, early-stopping behavior",
    )
    build_challenge.add_argument(
        "--artist-family-exclusions",
        type=Path,
        default=None,
        help="optional artist-family-exclusions-v1.json; drops trivial group/frontperson pairs",
    )
    build_challenge.add_argument(
        "--release-format-policy",
        type=Path,
        default=None,
        help=(
            "optional release-format-scoring-index.json; fail-closed gates every matched "
            "album (editorial or hybrid-catalog) by the studio-album-v1 policy"
        ),
    )
    build_challenge.add_argument(
        "--studio-album-exclusions",
        type=Path,
        default=None,
        help="optional studio-album-master-exclusions-v1.json; curated non-studio master deny-list",
    )
    build_challenge.add_argument("--enrich-images", action="store_true")
    build_challenge.add_argument(
        "--cache-dir", type=Path, default=Path("data/private/discogs-api-cache")
    )
    build_challenge.add_argument("--request-delay", type=float, default=1.1)

    validate_challenge = subparsers.add_parser(
        "validate-challenge", help="validate a challenge.v2 artifact against its contract"
    )
    validate_challenge.add_argument("--input", type=Path, required=True)

    build_rounds = subparsers.add_parser(
        "build-rounds-from-dump",
        help=(
            "LEGACY/exploratory -- ordinal round ids, no mode field, embedded cover art. "
            "Use build-record-routes for the production Record Routes artifact pair "
            "(content-derived ids, mode='record_routes', art-free, ADR 0046). Builds a real "
            "performer-only universe.v1/rounds.v1 artifact pair from a one-hop dataset"
        ),
    )
    build_rounds.add_argument("--onehop-root", type=Path, required=True)
    build_rounds.add_argument(
        "--albums",
        type=Path,
        required=True,
        help='an {"albums": [...]} file, e.g. build-album-catalog\'s output',
    )
    build_rounds.add_argument(
        "--masters-root", type=Path, default=None, help="optional parsed masters snapshot root"
    )
    build_rounds.add_argument(
        "--artist-family-exclusions",
        type=Path,
        default=None,
        help="optional artist-family-exclusions-v1.json; drops trivial group/frontperson pairs",
    )
    build_rounds.add_argument(
        "--release-format-policy",
        type=Path,
        default=None,
        help=(
            "optional release-format-scoring-index.json; gates matched albums and every "
            "two-hop round's bridge evidence by the studio-album-v1 policy"
        ),
    )
    build_rounds.add_argument(
        "--studio-album-exclusions",
        type=Path,
        default=None,
        help="optional studio-album-master-exclusions-v1.json; curated non-studio master deny-list",
    )
    build_rounds.add_argument("--one-hop-target", type=int, default=400)
    build_rounds.add_argument("--two-hop-target", type=int, default=100)
    build_rounds.add_argument("--max-endpoint-share", type=float, default=0.15)
    build_rounds.add_argument("--max-bridge-share", type=float, default=0.2)
    build_rounds.add_argument("--pool-version", required=True)
    build_rounds.add_argument("--max-artists-per-release", type=int, default=50)
    build_rounds.add_argument("--memory-limit", default="1GB")
    build_rounds.add_argument("--threads", type=int, default=2)
    build_rounds.add_argument("--output-universe", type=Path, required=True)
    build_rounds.add_argument("--output-rounds", type=Path, required=True)

    validate_rounds = subparsers.add_parser(
        "validate-rounds",
        help="validate a universe.v1/rounds.v1 artifact pair against its contract",
    )
    validate_rounds.add_argument("--universe", type=Path, required=True)
    validate_rounds.add_argument("--rounds", type=Path, required=True)

    build_connection_rounds = subparsers.add_parser(
        "build-connection-rounds",
        help=(
            "build the real Connection Guesser universe.v1/rounds.v1 pair (apps/web's "
            "GameUniverse/GameRounds contract) -- a performer credited on BOTH displayed "
            "albums directly, distinct from build-rounds-from-dump's path semantic"
        ),
    )
    build_connection_rounds.add_argument("--onehop-root", type=Path, required=True)
    build_connection_rounds.add_argument(
        "--albums",
        type=Path,
        required=True,
        help=(
            "the canonical catalog artifact (apps/web/public/data/catalog/albums.v1.json, "
            "build-album-catalog's output) -- the same --albums input build-challenge-from-dump "
            "consumes, so both real public surfaces derive their album set from one source"
        ),
    )
    build_connection_rounds.add_argument(
        "--artist-family-exclusions",
        type=Path,
        default=None,
        help="optional artist-family-exclusions-v1.json; drops trivial group/frontperson pairs",
    )
    build_connection_rounds.add_argument("--one-hop-target", type=int, default=300)
    build_connection_rounds.add_argument("--two-hop-target", type=int, default=200)
    build_connection_rounds.add_argument("--max-endpoint-share", type=float, default=0.15)
    build_connection_rounds.add_argument("--max-bridge-share", type=float, default=0.2)
    build_connection_rounds.add_argument("--memory-limit", default="1GB")
    build_connection_rounds.add_argument("--threads", type=int, default=2)
    build_connection_rounds.add_argument("--output-universe", type=Path, required=True)
    build_connection_rounds.add_argument("--output-rounds", type=Path, required=True)

    validate_connection_rounds = subparsers.add_parser(
        "validate-connection-rounds",
        help="validate a real Connection Guesser universe.v1/rounds.v1 pair against its contract",
    )
    validate_connection_rounds.add_argument("--universe", type=Path, required=True)
    validate_connection_rounds.add_argument("--rounds", type=Path, required=True)

    build_record_routes = subparsers.add_parser(
        "build-record-routes",
        help=(
            "build the real Record Routes universe/rounds pair "
            "(apps/web/public/data/routes/*, the path-guessing mode) -- album->artist->album "
            "documented credit paths, mode='record_routes', content-derived route ids, "
            "art-free; NOT the Connection Guesser's game/rounds.v1.json (ADR 0046)"
        ),
    )
    build_record_routes.add_argument("--onehop-root", type=Path, required=True)
    build_record_routes.add_argument(
        "--albums",
        type=Path,
        required=True,
        help="the canonical catalog artifact (apps/web/public/data/catalog/albums.v1.json)",
    )
    build_record_routes.add_argument("--artist-family-exclusions", type=Path, default=None)
    build_record_routes.add_argument("--release-format-policy", type=Path, default=None)
    build_record_routes.add_argument("--studio-album-exclusions", type=Path, default=None)
    build_record_routes.add_argument("--masters-root", type=Path, default=None)
    build_record_routes.add_argument("--one-hop-target", type=int, default=150)
    build_record_routes.add_argument("--two-hop-target", type=int, default=100)
    build_record_routes.add_argument("--max-endpoint-share", type=float, default=0.15)
    build_record_routes.add_argument("--max-bridge-share", type=float, default=0.2)
    build_record_routes.add_argument("--max-artists-per-release", type=int, default=50)
    build_record_routes.add_argument("--memory-limit", default="1GB")
    build_record_routes.add_argument("--threads", type=int, default=2)
    build_record_routes.add_argument("--output-universe", type=Path, required=True)
    build_record_routes.add_argument("--output-rounds", type=Path, required=True)

    validate_record_routes = subparsers.add_parser(
        "validate-record-routes",
        help="validate a Record Routes universe/rounds pair against its contract (ADR 0046)",
    )
    validate_record_routes.add_argument("--universe", type=Path, required=True)
    validate_record_routes.add_argument("--rounds", type=Path, required=True)

    build_daily = subparsers.add_parser(
        "build-daily-manifest",
        help=(
            "Record Routes ONLY -- schedules rounds.py's path-shaped rounds (top-level "
            "pool_version). NOT for the flagship Connection Guesser's Connection of the "
            "Day: use build-connection-daily-manifest for that (different contract, "
            "provenance.pool_version not a top-level field, one-hop/real-records "
            "filtering built in). See ADR 0043's corrective-slice-4.6 addendum."
        ),
    )
    build_daily.add_argument("--rounds", type=Path, required=True)
    build_daily.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    build_daily.add_argument("--days", type=int, default=365)
    build_daily.add_argument("--output", type=Path, required=True)

    extend_daily = subparsers.add_parser(
        "extend-daily-manifest",
        help=(
            "Record Routes ONLY (see build-daily-manifest); append new dates to an "
            "existing daily manifest without touching history"
        ),
    )
    extend_daily.add_argument("--manifest", type=Path, required=True)
    extend_daily.add_argument("--rounds", type=Path, required=True)
    extend_daily.add_argument("--days", type=int, default=365)
    extend_daily.add_argument("--output", type=Path, required=True)

    validate_daily = subparsers.add_parser(
        "validate-daily-manifest",
        help=(
            "Record Routes ONLY (see build-daily-manifest); validate a daily-manifest.v1 "
            "artifact against its contract"
        ),
    )
    validate_daily.add_argument("--manifest", type=Path, required=True)
    validate_daily.add_argument("--rounds", type=Path, required=True)

    build_connection_daily = subparsers.add_parser(
        "build-connection-daily-manifest",
        help=(
            "the flagship Connection Guesser's Connection of the Day: build a frozen, "
            "append-only date->round schedule from real one-hop rounds only (filters "
            "out two-hop, Record Routes, and synthetic rounds explicitly; ADR 0043)"
        ),
    )
    build_connection_daily.add_argument(
        "--rounds", type=Path, required=True, help="apps/web/public/data/game/rounds.v1.json"
    )
    build_connection_daily.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    build_connection_daily.add_argument("--days", type=int, default=90)
    build_connection_daily.add_argument("--output", type=Path, required=True)
    build_connection_daily.add_argument(
        "--generated-at",
        required=True,
        help="explicit ISO datetime for this build, e.g. 2026-08-01T00:00:00+00:00 -- "
        "never the wall clock, so identical arguments reproduce a byte-identical "
        "manifest (corrective slice 5.1)",
    )

    extend_connection_daily = subparsers.add_parser(
        "extend-connection-daily-manifest",
        help=(
            "append new dates to an existing Connection Guesser daily manifest; "
            "re-verifies every existing entry's content fingerprint before appending "
            "anything, and never touches an already-published date"
        ),
    )
    extend_connection_daily.add_argument("--manifest", type=Path, required=True)
    extend_connection_daily.add_argument("--rounds", type=Path, required=True)
    extend_connection_daily.add_argument("--days", type=int, default=90)
    extend_connection_daily.add_argument("--output", type=Path, required=True)
    extend_connection_daily.add_argument(
        "--generated-at",
        required=True,
        help="explicit ISO datetime for this extension -- never the wall clock "
        "(corrective slice 5.1)",
    )

    validate_connection_daily = subparsers.add_parser(
        "validate-connection-daily-manifest",
        help="validate a Connection Guesser daily-manifest artifact against its contract",
    )
    validate_connection_daily.add_argument("--manifest", type=Path, required=True)
    validate_connection_daily.add_argument("--rounds", type=Path, required=True)

    connection_daily_diagnostics = subparsers.add_parser(
        "connection-daily-manifest-diagnostics",
        help=(
            "report honest, non-optimizing schedule diagnostics for a Connection "
            "Guesser daily manifest (endpoint/performer reuse, difficulty/decade "
            "distribution, repeat streaks)"
        ),
    )
    connection_daily_diagnostics.add_argument("--manifest", type=Path, required=True)
    connection_daily_diagnostics.add_argument("--rounds", type=Path, required=True)

    connection_daily_status = subparsers.add_parser(
        "connection-daily-manifest-status",
        help=(
            "how much schedule runway remains before a Connection Guesser daily "
            "manifest needs extending; exits 1 only if already expired, 0 while "
            "merely inside the warning window (a non-alarmist periodic check)"
        ),
    )
    connection_daily_status.add_argument("--manifest", type=Path, required=True)
    connection_daily_status.add_argument(
        "--as-of",
        default=None,
        help="explicit ISO date to evaluate from; defaults to today (UTC) if omitted",
    )
    connection_daily_status.add_argument("--warn-within-days", type=int, default=14)

    rank_albums = subparsers.add_parser(
        "rank-album-candidates",
        help="rank master_ids by release-variant count x credit richness (local-only shortlist)",
    )
    rank_albums.add_argument("--dataset", type=Path, required=True)
    rank_albums.add_argument("--output", type=Path, required=True)
    rank_albums.add_argument("--limit", type=int, default=200)
    rank_albums.add_argument("--memory-limit", default="3GB")
    rank_albums.add_argument("--threads", type=int, default=2)
    rank_albums.add_argument(
        "--release-format-policy",
        type=Path,
        default=None,
        help="optional release-format-scoring-index.json; excludes non-studio-album candidates",
    )
    rank_albums.add_argument(
        "--masters-root",
        type=Path,
        default=None,
        help="optional parsed masters snapshot root; supplies the original album year and "
        "the Discogs genre/style non-studio (soundtrack/stage) exclusion",
    )
    rank_albums.add_argument(
        "--studio-album-exclusions",
        type=Path,
        default=None,
        help="optional studio-album-master-exclusions-v1.json; curated master-ID deny-list",
    )

    build_album_catalog = subparsers.add_parser(
        "build-album-catalog",
        help=(
            "EXPLORATORY/internal only -- policy inputs are optional here, so this can "
            "silently omit masters/format-policy/exclusions. NOT the correct way to "
            "produce the committed public catalog (apps/web/public/data/catalog/"
            "albums.v1.json): use build-public-album-catalog for that, which requires "
            "every policy input and fails closed if one is missing (ADR 0038, ADR 0043)"
        ),
    )
    build_album_catalog.add_argument("--onehop-root", type=Path, required=True)
    build_album_catalog.add_argument(
        "--editorial-albums", type=Path, default=Path("data/albums/top-albums-v1.json")
    )
    build_album_catalog.add_argument(
        "--candidates", type=Path, required=True, help="rank-album-candidates output"
    )
    build_album_catalog.add_argument("--target-count", type=int, required=True)
    build_album_catalog.add_argument("--output", type=Path, required=True)
    build_album_catalog.add_argument("--memory-limit", default="1GB")
    build_album_catalog.add_argument("--threads", type=int, default=2)
    build_album_catalog.add_argument(
        "--release-format-policy",
        type=Path,
        default=None,
        help="optional release-format-scoring-index.json; also gates the editorial entries",
    )
    build_album_catalog.add_argument(
        "--masters-root",
        type=Path,
        default=None,
        help="optional parsed masters snapshot root; original album year + genre/style "
        "non-studio exclusion for both the editorial and candidate sides",
    )
    build_album_catalog.add_argument(
        "--studio-album-exclusions",
        type=Path,
        default=None,
        help="optional studio-album-master-exclusions-v1.json; curated master-ID deny-list",
    )

    validate_album_catalog = subparsers.add_parser(
        "validate-album-catalog",
        help="validate the canonical apps/web/public/data/catalog/albums.v1.json artifact",
    )
    validate_album_catalog.add_argument("--input", type=Path, required=True)

    build_public_album_catalog = subparsers.add_parser(
        "build-public-album-catalog",
        help=(
            "the ONLY correct way to produce the committed public catalog "
            "(apps/web/public/data/catalog/albums.v1.json). Every policy input "
            "(masters, release-format policy, studio-album exclusions) is REQUIRED and "
            "cross-checked for a matching snapshot_date; fails immediately rather than "
            "silently building an under-gated catalog (ADR 0038, ADR 0043)"
        ),
    )
    build_public_album_catalog.add_argument("--onehop-root", type=Path, required=True)
    build_public_album_catalog.add_argument(
        "--editorial-albums", type=Path, default=Path("data/albums/top-albums-v1.json")
    )
    build_public_album_catalog.add_argument(
        "--candidates", type=Path, required=True, help="rank-album-candidates output"
    )
    build_public_album_catalog.add_argument("--target-count", type=int, required=True)
    build_public_album_catalog.add_argument("--output", type=Path, required=True)
    build_public_album_catalog.add_argument("--memory-limit", default="1GB")
    build_public_album_catalog.add_argument("--threads", type=int, default=2)
    build_public_album_catalog.add_argument(
        "--release-format-policy",
        type=Path,
        required=True,
        help="release-format-scoring-index.json; REQUIRED, gates every editorial and "
        "candidate entry -- no fallback that admits an ungated album",
    )
    build_public_album_catalog.add_argument(
        "--masters-root",
        type=Path,
        required=True,
        help="parsed masters snapshot root; REQUIRED for original album years and the "
        "genre/style non-studio (soundtrack/stage) exclusion",
    )
    build_public_album_catalog.add_argument(
        "--studio-album-exclusions",
        type=Path,
        required=True,
        help="studio-album-master-exclusions-v1.json; REQUIRED curated master-ID deny-list "
        "(the human-curation backstop for non-studio masters with no structured signal)",
    )

    build_catalog_audit = subparsers.add_parser(
        "build-album-catalog-audit",
        help=(
            "build a committed, machine-readable, one-row-per-INCLUDED-album inclusion "
            "audit of the canonical public catalog -- NOT an accept-and-reject ledger; "
            "excluded masters never get a row here (see "
            "data/albums/studio-album-master-exclusions-v1.json for those decisions). "
            "Writes docs/data/studio-album-catalog-inclusion-audit-v1.json (ADR 0043)"
        ),
    )
    build_catalog_audit.add_argument(
        "--catalog", type=Path, required=True, help="apps/web/public/data/catalog/albums.v1.json"
    )
    build_catalog_audit.add_argument("--onehop-root", type=Path, required=True)
    build_catalog_audit.add_argument("--masters-root", type=Path, required=True)
    build_catalog_audit.add_argument("--release-format-policy", type=Path, required=True)
    build_catalog_audit.add_argument("--studio-album-exclusions", type=Path, required=True)
    build_catalog_audit.add_argument("--output", type=Path, required=True)
    build_catalog_audit.add_argument("--memory-limit", default="1GB")
    build_catalog_audit.add_argument("--threads", type=int, default=2)

    validate_catalog_audit = subparsers.add_parser(
        "validate-album-catalog-audit",
        help=(
            "prove exact 1:1 correspondence between a catalog and its INCLUSION audit "
            "artifact -- validates only the one-row-per-included-album guarantee, not "
            "any claim about excluded candidates"
        ),
    )
    validate_catalog_audit.add_argument("--catalog", type=Path, required=True)
    validate_catalog_audit.add_argument("--audit", type=Path, required=True)

    build_art_registry = subparsers.add_parser(
        "build-album-art-registry",
        help=(
            "OPERATOR/coordination-host only: build the public album-art registry "
            "(apps/web/public/data/catalog/album-art.v1.json) by hotlinking Discogs cover "
            "art per canonical album. Rate-limited, cache-first/resumable, hotlink URLs only "
            "(no image bytes stored); DISCOGS_TOKEN from env. Presentation-only -- never "
            "embedded in frozen game content (ADR 0044/0045)"
        ),
    )
    build_art_registry.add_argument(
        "--catalog", type=Path, required=True, help="apps/web/public/data/catalog/albums.v1.json"
    )
    build_art_registry.add_argument("--output", type=Path, required=True)
    build_art_registry.add_argument(
        "--cache-dir", type=Path, default=Path("data/private/discogs-api-cache")
    )
    build_art_registry.add_argument("--request-delay", type=float, default=1.1)
    build_art_registry.add_argument(
        "--generated-at",
        required=True,
        help="explicit ISO datetime for this build (never the wall clock), e.g. "
        "2026-07-22T00:00:00+00:00",
    )

    validate_art_registry = subparsers.add_parser(
        "validate-album-art-registry",
        help=(
            "validate an album-art registry against the canonical catalog it claims to belong "
            "to (catalog_version agreement, album-id membership, approved https hosts, "
            "art_version recomputation, no private/token data)"
        ),
    )
    validate_art_registry.add_argument("--registry", type=Path, required=True)
    validate_art_registry.add_argument("--catalog", type=Path, required=True)

    fetch_dataset_parser = subparsers.add_parser(
        "fetch-dataset",
        help="fetch and verify a served dataset into a local, disposable cache (ADR 0025)",
    )
    fetch_dataset_parser.add_argument(
        "--base-url", help="dataset root URL, e.g. http://host:8791/discogs/snapshot=20260601"
    )
    fetch_dataset_parser.add_argument("--dest", type=Path, required=True)
    fetch_dataset_parser.add_argument("--verify-only", action="store_true")
    fetch_dataset_parser.add_argument("--max-total-bytes", type=int, default=None)
    fetch_dataset_parser.add_argument("--headroom-bytes", type=int, default=1_000_000_000)
    fetch_dataset_parser.add_argument("--timeout", type=float, default=60.0)
    fetch_dataset_parser.add_argument("--overwrite", action="store_true")

    verify_dataset_parser = subparsers.add_parser(
        "verify-dataset", help="re-verify a local dataset cache against its own manifest.json"
    )
    verify_dataset_parser.add_argument("--dest", type=Path, required=True)

    export_snapshot = subparsers.add_parser(
        "export-graph-snapshot",
        help="export a materialized co-credit adjacency snapshot (see graph-snapshot-v1.md)",
    )
    export_snapshot.add_argument(
        "--dataset", type=Path, required=True, help="a parsed dataset root"
    )
    export_snapshot.add_argument("--output-root", type=Path, required=True)
    export_snapshot.add_argument("--max-artists-per-release", type=int, default=50)
    export_snapshot.add_argument("--memory-limit", default="1GB")
    export_snapshot.add_argument("--threads", type=int, default=2)
    export_snapshot.add_argument(
        "--temp-dir", type=Path, default=None, help="DuckDB spill directory"
    )
    export_snapshot.add_argument("--overwrite", action="store_true")

    import_cohort = subparsers.add_parser(
        "import-cohort-source",
        help=(
            "extract album candidates from a saved cohort-source HTML page "
            "(curated source ingestion; no live fetching)"
        ),
    )
    import_cohort.add_argument(
        "--input",
        type=Path,
        required=True,
        help="saved HTML file (never committed; keep under data/private/source-html/)",
    )
    import_cohort.add_argument("--output", type=Path, required=True)
    import_cohort.add_argument(
        "--source-url",
        required=True,
        help="URL the page was saved from; recorded as provenance only, never re-fetched",
    )
    import_cohort.add_argument("--source-title", required=True)
    import_cohort.add_argument("--saved-at", default=date.today().isoformat())
    import_cohort.add_argument("--operator-note", default="")

    resolve_cohort = subparsers.add_parser(
        "resolve-cohort",
        help="resolve extracted cohort candidates against a real parsed Discogs dataset",
    )
    resolve_cohort.add_argument(
        "--extracted", type=Path, required=True, help="album-cohort-extracted-v1.json"
    )
    resolve_cohort.add_argument(
        "--dataset", type=Path, required=True, help="a parsed dataset root (not one-hop)"
    )
    resolve_cohort.add_argument("--output", type=Path, required=True)
    resolve_cohort.add_argument("--memory-limit", default="1GB")
    resolve_cohort.add_argument("--threads", type=int, default=2)
    resolve_cohort.add_argument("--max-artists-per-release", type=int, default=50)
    resolve_cohort.add_argument(
        "--temp-dir", type=Path, default=None, help="DuckDB spill directory"
    )
    resolve_cohort.add_argument(
        "--max-workers",
        type=int,
        default=1,
        help="resolve candidates concurrently across this many DuckDB cursors; default 1 "
        "preserves the original sequential behavior",
    )

    score_connectivity = subparsers.add_parser(
        "score-cohort-connectivity",
        help="compute real graph paths between every pair of resolved cohort albums",
    )
    score_connectivity.add_argument(
        "--resolved", type=Path, required=True, help="album-cohort-resolved-v1.json"
    )
    score_connectivity.add_argument(
        "--dataset", type=Path, required=True, help="a one-hop dataset root"
    )
    score_connectivity.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="writes connectivity.json, playable-pairs.json, review-report.md here",
    )
    score_connectivity.add_argument("--max-hops", type=int, default=3)
    score_connectivity.add_argument(
        "--max-pairs",
        type=int,
        default=1000,
        help="abort with a clear message rather than silently sampling/truncating "
        "if the cohort's pair count would exceed this",
    )
    score_connectivity.add_argument("--memory-limit", default="1GB")
    score_connectivity.add_argument("--threads", type=int, default=2)
    score_connectivity.add_argument("--max-artists-per-release", type=int, default=50)
    score_connectivity.add_argument(
        "--temp-dir", type=Path, default=None, help="DuckDB spill directory"
    )
    score_connectivity.add_argument(
        "--release-format-policy",
        type=Path,
        default=None,
        help="local studio-album-v1 policy JSON; omit for legacy title-only scoring",
    )
    score_connectivity.add_argument(
        "--max-frontier-expansion",
        type=int,
        default=300,
        help="degree threshold above which an artist is excluded from BFS expansion "
        "(still reachable as a target, and never applied to a cohort seed itself); "
        "with reach scoring (ADR 0033) this bounds time, not memory, so it can be "
        "raised per cohort/dataset. Since ADR 0035 this is an artist's exact "
        "credit_edges degree, not the old credit-row proxy, so equivalent caps are "
        "much smaller -- Pink Floyd's degree is 540, Stevie Wonder's 4,844",
    )
    score_connectivity.add_argument(
        "--pair-timeout-seconds",
        type=float,
        default=30.0,
        help="wall-clock budget for each cohort artist's own reach expansion; on timeout "
        "every pair needing that artist's search is reported status=skipped rather "
        "than hanging or guessing; real hub-heavy cohorts need 120-180 (see "
        "docs/OPERATOR_SETUP.md)",
    )
    score_connectivity.add_argument(
        "--max-workers",
        type=int,
        default=1,
        help="accepted for compatibility; local scoring now runs inside DuckDB where "
        "--threads is the effective parallelism lever (ADR 0033)",
    )
    score_connectivity.add_argument(
        "--max-reach-rows",
        type=int,
        default=2_000_000,
        help="per-seed bound on materialized reach rows; a seed exceeding it is reported "
        "skipped/reach_too_large rather than ground on (worst real seed measured "
        "445k rows at depth 2)",
    )
    score_connectivity.add_argument(
        "--skip-preflight",
        action="store_true",
        help="skip the MemAvailable check that refuses a --memory-limit above half of "
        "this host's available RAM (the measured swap-death mode of a real run)",
    )

    promote_cohort = subparsers.add_parser(
        "promote-playable-cohort",
        help="promote a human-reviewed selection of connectivity pairs into a small, "
        "public playable-cohort artifact",
    )
    promote_cohort.add_argument(
        "--resolved", type=Path, required=True, help="album-cohort-resolved-v1.json"
    )
    promote_cohort.add_argument(
        "--connectivity", type=Path, required=True, help="album-cohort-connectivity-v1.json"
    )
    promote_cohort.add_argument(
        "--selection",
        type=Path,
        required=True,
        help="operator-authored selection file naming approved pairs (private-only, "
        "conventionally under data/private/cohort-review/)",
    )
    promote_cohort.add_argument(
        "--cohort-id", required=True, help="stable identifier for this cohort"
    )
    promote_cohort.add_argument("--output", type=Path, required=True)

    validate_playable = subparsers.add_parser(
        "validate-playable-cohort", help="validate a playable-cohort-v1 artifact"
    )
    validate_playable.add_argument("--input", type=Path, required=True)

    validate_connectivity_parser = subparsers.add_parser(
        "validate-connectivity", help="validate an album-cohort-connectivity-v1 artifact"
    )
    validate_connectivity_parser.add_argument("--input", type=Path, required=True)

    draft_review = subparsers.add_parser(
        "draft-cohort-review",
        help="draft a private selection-file template from connectivity.json for human "
        "review (never pre-approves anything)",
    )
    draft_review.add_argument(
        "--connectivity", type=Path, required=True, help="album-cohort-connectivity-v1.json"
    )
    draft_review.add_argument("--output", type=Path, required=True)

    editorial_review = subparsers.add_parser(
        "draft-cohort-editorial-review",
        help="write a local suggestions-only editorial packet from scored cohort artifacts",
    )
    editorial_review.add_argument("--resolved", type=Path, required=True)
    editorial_review.add_argument("--connectivity", type=Path, required=True)
    editorial_review.add_argument("--output-json", type=Path, required=True)
    editorial_review.add_argument("--output-markdown", type=Path, required=True)
    editorial_review.add_argument(
        "--api-cache-dir", type=Path, default=Path("data/private/discogs-api-cache")
    )
    editorial_review.add_argument(
        "--enrich-images",
        action="store_true",
        help=(
            "explicitly fetch missing release metadata into the private API cache "
            "before writing hotlinks"
        ),
    )
    editorial_review.add_argument("--request-delay", type=float, default=1.1)
    editorial_review.add_argument(
        "--dataset",
        type=Path,
        help=(
            "one-hop dataset root; when given, every hop is explained with its "
            "release title, the shared recording, and each artist's credited role, "
            "so a curator can judge a connection without opening Discogs"
        ),
    )

    status = subparsers.add_parser(
        "cohort-pipeline-status",
        help=(
            "read-only status summary for a cohort rehearsal; prints the next action, runs nothing"
        ),
    )
    status.add_argument("--source-id", required=True)
    status.add_argument(
        "--analysis-dir",
        type=Path,
        default=None,
        help="analysis root (default: local/analysis/cohorts/<source-id>)",
    )
    status.add_argument(
        "--review-dir",
        type=Path,
        default=Path("data/private/cohort-review"),
        help="private review directory (default: data/private/cohort-review)",
    )
    status.add_argument(
        "--promoted-artifact",
        type=Path,
        default=None,
        help="promoted cohort artifact (default: data/albums/cohorts/<source-id>-playable-v1.json)",
    )
    status.add_argument(
        "--web-manifest",
        type=Path,
        default=Path("apps/web/public/data/cohorts/index.json"),
        help="web manifest (default: apps/web/public/data/cohorts/index.json)",
    )
    status.add_argument(
        "--web-import-map",
        type=Path,
        default=Path("apps/web/src/data/cohortArtifacts.ts"),
        help="static web import map (default: apps/web/src/data/cohortArtifacts.ts)",
    )
    status.add_argument(
        "--jobs-dir",
        type=Path,
        default=Path("local/jobs"),
        help="optional Pi job-record directory (default: local/jobs)",
    )
    status.add_argument(
        "--json", action="store_true", help="print the machine-readable report instead of text"
    )

    preflight = subparsers.add_parser(
        "cohort-pipeline-preflight",
        help="read-only readiness check for a real cohort rehearsal; prints the exact "
        "next commands, runs nothing",
    )
    preflight.add_argument("--source-id", required=True)
    preflight.add_argument(
        "--source-html", type=Path, required=True, help="the operator's manually saved page"
    )
    preflight.add_argument(
        "--parsed-dataset", type=Path, required=True, help="a parsed dataset root (not one-hop)"
    )
    preflight.add_argument(
        "--onehop-dataset", type=Path, required=True, help="a one-hop dataset root"
    )
    preflight.add_argument(
        "--source-url", required=True, help="URL the page was saved from; provenance only"
    )
    preflight.add_argument("--source-title", required=True)
    preflight.add_argument(
        "--json", action="store_true", help="print the machine-readable report instead of text"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "manifest":
        kwargs = {}
        if args.base_url:
            kwargs["base_url"] = args.base_url
        manifest = build_manifest(
            args.snapshot,
            terms_reviewed_at=args.terms_reviewed_at,
            **kwargs,
        )
        manifest.write(args.output)
        print(args.output)
        return 0

    if args.command == "download":
        manifest = SnapshotManifest.read(args.manifest)
        item = manifest.object_for(DumpKind(args.kind))
        result = download_file(
            item.url,
            args.raw_dir / manifest.snapshot_date / item.filename,
            expected_size=item.size_bytes,
            expected_sha256=item.sha256,
        )
        item.size_bytes = result.size_bytes
        item.sha256 = result.sha256
        item.etag = result.etag
        item.downloaded_at = datetime.now(UTC).isoformat()
        manifest.write(args.manifest)
        print(json.dumps({"path": str(result.path), "sha256": result.sha256}, indent=2))
        return 0

    if args.command == "parse-releases":
        from .discogs.parquet import write_release_dataset
        from .discogs.releases import iter_releases

        records = iter_releases(
            args.input,
            snapshot_date=args.snapshot,
            source_url=args.source_url,
            max_releases=args.max_releases,
        )
        dataset_manifest = write_release_dataset(
            records,
            args.output_root,
            snapshot_date=args.snapshot,
            source_url=args.source_url,
            chunk_releases=args.chunk_releases,
            overwrite=args.overwrite,
        )
        print(json.dumps(dataset_manifest, indent=2, sort_keys=True))
        return 0

    if args.command == "parse-masters":
        from .discogs.masters import iter_masters
        from .discogs.parquet import write_master_dataset

        master_records = iter_masters(
            args.input,
            snapshot_date=args.snapshot,
            source_url=args.source_url,
            max_masters=args.max_masters,
        )
        masters_manifest = write_master_dataset(
            master_records,
            args.output_root,
            snapshot_date=args.snapshot,
            source_url=args.source_url,
            chunk_masters=args.chunk_masters,
            overwrite=args.overwrite,
        )
        print(json.dumps(masters_manifest, indent=2, sort_keys=True))
        return 0

    if args.command == "parse-artist-relations":
        from .discogs.artists import iter_artist_relations
        from .discogs.parquet import write_artist_relations_dataset

        relation_records = iter_artist_relations(
            args.input,
            snapshot_date=args.snapshot,
            source_url=args.source_url,
            max_artists=args.max_artists,
        )
        relations_manifest = write_artist_relations_dataset(
            relation_records,
            args.output_root,
            snapshot_date=args.snapshot,
            source_url=args.source_url,
            chunk_artists=args.chunk_artists,
            overwrite=args.overwrite,
        )
        print(json.dumps(relations_manifest, indent=2, sort_keys=True))
        return 0

    if args.command == "build-artist-family-exclusions":
        from .discogs.artist_family import (
            build_artist_family_exclusions,
            write_artist_family_exclusions,
        )

        artist_ids = json.loads(args.artist_ids_file.read_text())
        exclusions = build_artist_family_exclusions(
            args.dataset, artist_ids=artist_ids, snapshot_date=args.snapshot
        )
        write_artist_family_exclusions(exclusions, args.output)
        print(
            json.dumps(
                {"output": str(args.output), "entry_count": len(exclusions["entries"])},
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "validate":
        from .discogs.validation import validate_dataset

        print(json.dumps(validate_dataset(args.dataset), indent=2, sort_keys=True))
        return 0

    if args.command == "validate-masters":
        from .discogs.validation import validate_master_dataset

        print(json.dumps(validate_master_dataset(args.dataset), indent=2, sort_keys=True))
        return 0

    if args.command == "classify-release-formats":
        from .discogs.release_format_policy import (
            build_release_format_policy,
            write_release_format_policy,
        )

        policy = build_release_format_policy(args.dataset, policy_name=args.policy)
        write_release_format_policy(policy, args.output)
        counts: dict[str, int] = {}
        for item in policy["classifications"]:
            counts[item["decision"]] = counts.get(item["decision"], 0) + 1
        print(json.dumps({"output": str(args.output), "counts": counts}, indent=2, sort_keys=True))
        return 0

    if args.command == "compare-release-format-policy":
        from .discogs.release_format_policy import build_format_policy_shadow_report

        policy = json.loads(args.policy.read_text())
        report = build_format_policy_shadow_report(args.dataset, policy)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(json.dumps({"output": str(args.output), "counts": report["counts"]}, indent=2))
        return 0

    if args.command == "build-release-format-scoring-index":
        from .discogs.release_format_policy import (
            build_release_format_scoring_index,
            write_release_format_scoring_index,
        )

        index = build_release_format_scoring_index(json.loads(args.policy.read_text()))
        write_release_format_scoring_index(index, args.output)
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "allowed_release_count": index["allowed_release_count"],
                },
                indent=2,
            )
        )
        return 0

    if args.command == "migrate-release-formats":
        from .discogs.format_migration import migrate_dataset_with_formats

        migration_manifest = migrate_dataset_with_formats(
            args.input_dataset,
            args.raw_dump,
            args.output_root,
            snapshot_date=args.snapshot,
            source_url=args.source_url,
            chunk_rows=args.chunk_rows,
            overwrite=args.overwrite,
        )
        print(json.dumps(migration_manifest, indent=2, sort_keys=True))
        return 0

    if args.command == "import-seed":
        from .discogs.seed import import_seed_csv

        seed = import_seed_csv(args.input, source=args.source)
        seed.write(args.output)
        payload = {"path": str(args.output), "release_id_count": len(seed.release_ids)}
        print(json.dumps(payload, indent=2))
        return 0

    if args.command == "expand-one-hop":
        from .discogs.onehop import expand_one_hop

        onehop_manifest = expand_one_hop(
            args.seed,
            args.dataset,
            args.output_root,
            memory_limit=args.memory_limit,
            threads=args.threads,
            temp_dir=args.temp_dir,
            max_retained_releases=args.max_retained_releases,
            overwrite=args.overwrite,
        )
        print(json.dumps(onehop_manifest, indent=2, sort_keys=True))
        return 0

    if args.command == "build-demo-challenge":
        import sys

        from .discogs.api_client import ApiClient, ReleaseCache, fetch_releases, load_token
        from .discogs.demo_challenge import build_challenge, parse_api_release
        from .discogs.seed import SeedManifest

        seed = SeedManifest.read(args.seed)
        client = ApiClient(token=load_token(), request_delay_seconds=args.request_delay)
        cache = ReleaseCache(args.cache_dir)

        def _progress(index: int, total: int, from_cache: bool) -> None:
            print(f"[{index}/{total}] {'cache' if from_cache else 'fetch'}", file=sys.stderr)

        raw = fetch_releases(seed.release_ids, client=client, cache=cache, on_progress=_progress)
        releases_by_id = {
            rid: parse_api_release(payload, snapshot_date=args.snapshot)
            for rid, payload in raw.items()
        }

        challenge = build_challenge(
            releases_by_id,
            snapshot_date=args.snapshot,
            generated_by=f"networked-players-catalog build-demo-challenge {__version__}",
            max_paths=args.max_paths,
            seed_count=args.seed_artists,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(challenge, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "releases_fetched": len(raw),
                    "releases_published": len(challenge["releases"]),
                    "paths_published": len(challenge["paths"]),
                },
                indent=2,
            )
        )
        return 0

    if args.command == "build-challenge-from-dump":
        import sys

        from networked_players_graph_core.challenge import (
            build_challenge_v2,
            build_challenge_v2_from_matched,
            resolved_album_from_dict,
            validate_challenge,
        )
        from networked_players_graph_core.graph import CreditGraph

        onehop_manifest_path = args.onehop_root / "manifest.json"
        onehop_manifest = json.loads(onehop_manifest_path.read_text())
        # Prefer the dataset's own top-level snapshot_date -- always present
        # and, for a format-migrated dataset (e.g. discogs-onehop-v3), the
        # only one present; expansion.source_snapshot_date is kept as a
        # fallback for older manifests that predate this preference.
        snapshot_date = str(
            onehop_manifest.get("snapshot_date")
            or onehop_manifest["expansion"]["source_snapshot_date"]
        )
        albums_payload = json.loads(args.albums.read_text())
        albums = albums_payload["albums"]
        # An ID-resolved album (e.g. build-album-catalog's output) carries
        # artist_id directly; re-matching it by name string would reopen the
        # exact collision risk resolving it once already closed.
        albums_are_resolved = bool(albums) and "artist_id" in albums[0]
        catalog_version = albums_payload.get("catalog_version") if albums_are_resolved else None

        is_family_excluded: Callable[[int, int], bool] | None = None
        if args.artist_family_exclusions is not None:
            from .discogs.artist_family import is_family_excluded_pair

            exclusions = json.loads(args.artist_family_exclusions.read_text())

            def is_family_excluded(a: int, b: int) -> bool:
                return is_family_excluded_pair(a, b, exclusions)

        allowed_release_ids = None
        if args.release_format_policy is not None:
            policy_payload = json.loads(args.release_format_policy.read_text())
            allowed_release_ids = frozenset(policy_payload["allowed_release_ids"])

        from .discogs.release_format_policy import load_master_exclusions

        master_exclusions = load_master_exclusions(args.studio_album_exclusions)

        with CreditGraph.open(
            args.onehop_root,
            memory_limit=args.memory_limit,
            threads=args.threads,
            max_artists_per_release=args.max_artists_per_release,
        ) as graph:
            if args.masters_root is not None:
                graph.attach_masters(args.masters_root)

            max_frontier_expansion = (
                args.max_frontier_expansion if args.max_frontier_expansion > 0 else None
            )
            if albums_are_resolved:
                matched = [resolved_album_from_dict(a) for a in albums]
                if allowed_release_ids is not None:
                    # Defense in depth: assemble_album_catalog already gated
                    # these, but never trust an upstream artifact blindly.
                    matched = [m for m in matched if m.main_release_id in allowed_release_ids]
                if master_exclusions:
                    matched = [m for m in matched if m.master_id not in master_exclusions]
                artifact, report = build_challenge_v2_from_matched(
                    graph,
                    matched,
                    [],
                    snapshot_date=snapshot_date,
                    generated_by=(
                        f"networked-players-catalog build-challenge-from-dump {__version__}"
                    ),
                    max_paths=args.max_paths,
                    max_hops=args.max_hops,
                    max_workers=args.max_workers,
                    is_family_excluded=is_family_excluded,
                    max_frontier_expansion=max_frontier_expansion,
                    catalog_version=catalog_version,
                )
            else:
                artifact, report = build_challenge_v2(
                    graph,
                    albums,
                    snapshot_date=snapshot_date,
                    generated_by=(
                        f"networked-players-catalog build-challenge-from-dump {__version__}"
                    ),
                    max_paths=args.max_paths,
                    max_hops=args.max_hops,
                    max_workers=args.max_workers,
                    is_family_excluded=is_family_excluded,
                    allowed_release_ids=allowed_release_ids,
                    master_exclusions=master_exclusions,
                    max_frontier_expansion=max_frontier_expansion,
                )

        if args.enrich_images:
            from .discogs.album_art import enrich_challenge_albums
            from .discogs.api_client import ApiClient, ReleaseCache, load_token

            client = ApiClient(token=load_token(), request_delay_seconds=args.request_delay)
            cache = ReleaseCache(args.cache_dir)
            report["albums_enriched"] = enrich_challenge_albums(
                artifact, client=client, cache=cache
            )

        validate_challenge(artifact)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(artifact, indent=2) + "\n")
        print(
            f"Wrote {args.output}. Before publishing, walk the prepublish checklist in "
            "docs/PUBLIC_PRIVATE_BOUNDARY.md -- validate_challenge() checks structure and "
            "known leak patterns, not editorial judgment.",
            file=sys.stderr,
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    if args.command == "validate-challenge":
        from networked_players_graph_core.challenge import validate_challenge

        challenge_artifact = json.loads(args.input.read_text())
        validate_challenge(challenge_artifact)
        print(json.dumps({"ok": True}, indent=2))
        return 0

    if args.command == "build-rounds-from-dump":
        from networked_players_graph_core.challenge import match_albums, resolved_album_from_dict
        from networked_players_graph_core.graph import CreditGraph
        from networked_players_graph_core.rounds import build_rounds_v1, validate_rounds_artifact
        from networked_players_graph_core.rounds_generator import generate_round_pool

        onehop_manifest = json.loads((args.onehop_root / "manifest.json").read_text())
        # Prefer the dataset's own top-level snapshot_date -- always present
        # and, for a format-migrated dataset (e.g. discogs-onehop-v3), the
        # only one present; expansion.source_snapshot_date is kept as a
        # fallback for older manifests that predate this preference.
        snapshot_date = str(
            onehop_manifest.get("snapshot_date")
            or onehop_manifest["expansion"]["source_snapshot_date"]
        )
        albums = json.loads(args.albums.read_text())["albums"]
        albums_are_resolved = bool(albums) and "artist_id" in albums[0]

        rounds_is_family_excluded: Callable[[int, int], bool] | None = None
        if args.artist_family_exclusions is not None:
            from .discogs.artist_family import is_family_excluded_pair

            rounds_exclusions = json.loads(args.artist_family_exclusions.read_text())

            def rounds_is_family_excluded(a: int, b: int) -> bool:
                return is_family_excluded_pair(a, b, rounds_exclusions)

        allowed_release_ids = None
        if args.release_format_policy is not None:
            policy_payload = json.loads(args.release_format_policy.read_text())
            allowed_release_ids = frozenset(policy_payload["allowed_release_ids"])

        from .discogs.release_format_policy import load_master_exclusions

        master_exclusions = load_master_exclusions(args.studio_album_exclusions)

        with CreditGraph.open(
            args.onehop_root,
            memory_limit=args.memory_limit,
            threads=args.threads,
            max_artists_per_release=args.max_artists_per_release,
        ) as graph:
            if args.masters_root is not None:
                graph.attach_masters(args.masters_root)

            if albums_are_resolved:
                matched = [resolved_album_from_dict(a) for a in albums]
                if allowed_release_ids is not None:
                    # Defense in depth: assemble_album_catalog already gated
                    # these, but never trust an upstream artifact blindly.
                    matched = [m for m in matched if m.main_release_id in allowed_release_ids]
                if master_exclusions:
                    matched = [m for m in matched if m.master_id not in master_exclusions]
                missed: list[dict[str, str]] = []
            else:
                matched, missed = match_albums(
                    graph,
                    albums,
                    allowed_release_ids=allowed_release_ids,
                    master_exclusions=master_exclusions,
                )
            if len(matched) < 2:
                raise ValueError(
                    f"only {len(matched)} album(s) matched with distinct artists "
                    "(need at least 2); widen the album list or check the snapshot"
                )

            rounds_json, diagnostics = generate_round_pool(
                graph,
                matched,
                one_hop_target=args.one_hop_target,
                two_hop_target=args.two_hop_target,
                is_family_excluded=rounds_is_family_excluded,
                allowed_release_ids=allowed_release_ids,
                max_endpoint_share=args.max_endpoint_share,
                max_bridge_share=args.max_bridge_share,
            )
            if not rounds_json:
                raise ValueError("no eligible rounds were found between any matched albums")

            universe, rounds = build_rounds_v1(
                graph,
                matched,
                rounds_json,
                snapshot_date=snapshot_date,
                generated_by=f"networked-players-catalog build-rounds-from-dump {__version__}",
                pool_version=args.pool_version,
            )

        validate_rounds_artifact(universe, rounds)
        args.output_universe.parent.mkdir(parents=True, exist_ok=True)
        args.output_rounds.parent.mkdir(parents=True, exist_ok=True)
        args.output_universe.write_text(json.dumps(universe, indent=2) + "\n")
        args.output_rounds.write_text(json.dumps(rounds, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "output_universe": str(args.output_universe),
                    "output_rounds": str(args.output_rounds),
                    "albums_matched": len(matched),
                    "albums_missed": len(missed),
                    "diagnostics": diagnostics,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "validate-rounds":
        from networked_players_graph_core.rounds import validate_rounds_artifact

        universe = json.loads(args.universe.read_text())
        rounds = json.loads(args.rounds.read_text())
        validate_rounds_artifact(universe, rounds)
        print(json.dumps({"ok": True}, indent=2))
        return 0

    if args.command == "build-connection-rounds":
        from networked_players_graph_core.connection_rounds import (
            build_connection_universe_and_rounds,
            generate_connection_round_pool,
            validate_connection_rounds_artifact,
        )
        from networked_players_graph_core.graph import CreditGraph

        catalog = json.loads(args.albums.read_text())
        albums = catalog["albums"]
        snapshot_date = catalog["snapshot_date"]
        catalog_version = catalog["catalog_version"]

        connection_is_family_excluded: Callable[[int, int], bool] | None = None
        if args.artist_family_exclusions is not None:
            from .discogs.artist_family import is_family_excluded_pair

            exclusions = json.loads(args.artist_family_exclusions.read_text())

            def connection_is_family_excluded(a: int, b: int) -> bool:
                return is_family_excluded_pair(a, b, exclusions)

        with CreditGraph.open(
            args.onehop_root,
            memory_limit=args.memory_limit,
            threads=args.threads,
            build_edges=False,
        ) as graph:
            rounds_json, diagnostics, performer_index = generate_connection_round_pool(
                graph,
                albums,
                one_hop_target=args.one_hop_target,
                two_hop_target=args.two_hop_target,
                is_family_excluded=connection_is_family_excluded,
                max_endpoint_share=args.max_endpoint_share,
                max_bridge_share=args.max_bridge_share,
            )
            if not rounds_json:
                raise ValueError("no eligible connection rounds were found between any album pair")

            universe, rounds = build_connection_universe_and_rounds(
                albums,
                rounds_json,
                performer_index,
                snapshot_date=snapshot_date,
                generated_by=f"networked-players-catalog build-connection-rounds {__version__}",
                catalog_version=catalog_version,
            )

        validate_connection_rounds_artifact(universe, rounds)
        args.output_universe.parent.mkdir(parents=True, exist_ok=True)
        args.output_rounds.parent.mkdir(parents=True, exist_ok=True)
        args.output_universe.write_text(json.dumps(universe, indent=2) + "\n")
        args.output_rounds.write_text(json.dumps(rounds, indent=2) + "\n")
        print(json.dumps(diagnostics, indent=2))
        return 0

    if args.command == "validate-connection-rounds":
        from networked_players_graph_core.connection_rounds import (
            validate_connection_rounds_artifact,
        )

        universe = json.loads(args.universe.read_text())
        rounds = json.loads(args.rounds.read_text())
        validate_connection_rounds_artifact(universe, rounds)
        print(json.dumps({"ok": True}, indent=2))
        return 0

    if args.command == "build-record-routes":
        from networked_players_graph_core.challenge import resolved_album_from_dict
        from networked_players_graph_core.graph import CreditGraph
        from networked_players_graph_core.record_routes import (
            build_record_routes_pool,
            validate_record_routes_artifact,
        )

        from .discogs.release_format_policy import load_master_exclusions

        catalog = json.loads(args.albums.read_text())
        rr_albums = catalog["albums"]
        rr_snapshot = catalog["snapshot_date"]
        rr_catalog_version = catalog["catalog_version"]

        rr_family_excluded: Callable[[int, int], bool] | None = None
        if args.artist_family_exclusions is not None:
            from .discogs.artist_family import is_family_excluded_pair

            rr_exclusions = json.loads(args.artist_family_exclusions.read_text())

            def rr_family_excluded(a: int, b: int) -> bool:
                return is_family_excluded_pair(a, b, rr_exclusions)

        rr_allowed_release_ids = None
        if args.release_format_policy is not None:
            rr_allowed_release_ids = frozenset(
                json.loads(args.release_format_policy.read_text())["allowed_release_ids"]
            )
        rr_master_exclusions = load_master_exclusions(args.studio_album_exclusions)

        with CreditGraph.open(
            args.onehop_root,
            memory_limit=args.memory_limit,
            threads=args.threads,
            max_artists_per_release=args.max_artists_per_release,
        ) as graph:
            if args.masters_root is not None:
                graph.attach_masters(args.masters_root)
            rr_matched = [resolved_album_from_dict(a) for a in rr_albums]
            if rr_allowed_release_ids is not None:
                rr_matched = [m for m in rr_matched if m.main_release_id in rr_allowed_release_ids]
            if rr_master_exclusions:
                rr_matched = [m for m in rr_matched if m.master_id not in rr_master_exclusions]
            if len(rr_matched) < 2:
                raise ValueError("need at least 2 matched albums to build Record Routes")

            rr_universe, rr_rounds, rr_diag = build_record_routes_pool(
                graph,
                rr_matched,
                one_hop_target=args.one_hop_target,
                two_hop_target=args.two_hop_target,
                snapshot_date=rr_snapshot,
                generated_by=f"networked-players-catalog build-record-routes {__version__}",
                catalog_version=rr_catalog_version,
                is_family_excluded=rr_family_excluded,
                allowed_release_ids=rr_allowed_release_ids,
                max_endpoint_share=args.max_endpoint_share,
                max_bridge_share=args.max_bridge_share,
            )

        validate_record_routes_artifact(rr_universe, rr_rounds)
        args.output_universe.parent.mkdir(parents=True, exist_ok=True)
        args.output_rounds.parent.mkdir(parents=True, exist_ok=True)
        args.output_universe.write_text(json.dumps(rr_universe, indent=2) + "\n")
        args.output_rounds.write_text(json.dumps(rr_rounds, indent=2) + "\n")
        print(json.dumps(rr_diag, indent=2))
        return 0

    if args.command == "validate-record-routes":
        from networked_players_graph_core.record_routes import validate_record_routes_artifact

        rr_universe = json.loads(args.universe.read_text())
        rr_rounds = json.loads(args.rounds.read_text())
        validate_record_routes_artifact(rr_universe, rr_rounds)
        print(json.dumps({"ok": True}, indent=2))
        return 0

    if args.command == "build-daily-manifest":
        from networked_players_graph_core.daily_manifest import build_daily_manifest

        rounds = json.loads(args.rounds.read_text())
        round_ids = [r["id"] for r in rounds["rounds"]]
        daily_manifest = build_daily_manifest(
            round_ids,
            pool_version=rounds["pool_version"],
            start_date=args.start_date,
            days=args.days,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(daily_manifest, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "days_requested": args.days,
                    "days_scheduled": len(daily_manifest["schedule"]),
                    "first_date": daily_manifest["schedule"][0]["date"],
                    "last_date": daily_manifest["schedule"][-1]["date"],
                },
                indent=2,
            )
        )
        return 0

    if args.command == "extend-daily-manifest":
        from networked_players_graph_core.daily_manifest import extend_daily_manifest

        daily_manifest = json.loads(args.manifest.read_text())
        rounds = json.loads(args.rounds.read_text())
        if rounds["pool_version"] != daily_manifest["pool_version"]:
            raise ValueError(
                f"rounds pool_version {rounds['pool_version']!r} does not match "
                f"manifest pool_version {daily_manifest['pool_version']!r}"
            )
        round_ids = [r["id"] for r in rounds["rounds"]]
        extended = extend_daily_manifest(daily_manifest, round_ids, days=args.days)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(extended, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "days_before": len(daily_manifest["schedule"]),
                    "days_after": len(extended["schedule"]),
                    "last_date": extended["schedule"][-1]["date"],
                },
                indent=2,
            )
        )
        return 0

    if args.command == "validate-daily-manifest":
        from networked_players_graph_core.daily_manifest import validate_daily_manifest

        daily_manifest = json.loads(args.manifest.read_text())
        rounds = json.loads(args.rounds.read_text())
        valid_round_ids = {r["id"] for r in rounds["rounds"]}
        validate_daily_manifest(daily_manifest, valid_round_ids=valid_round_ids)
        print(json.dumps({"ok": True}, indent=2))
        return 0

    if args.command == "build-connection-daily-manifest":
        from networked_players_graph_core.connection_daily_manifest import (
            build_connection_daily_manifest,
            schedule_diagnostics,
            validate_connection_daily_manifest,
        )

        conn_rounds = json.loads(args.rounds.read_text())
        conn_daily_manifest = build_connection_daily_manifest(
            conn_rounds, start_date=args.start_date, days=args.days, generated_at=args.generated_at
        )
        validate_connection_daily_manifest(conn_daily_manifest, conn_rounds)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(conn_daily_manifest, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "days_requested": args.days,
                    "days_scheduled": len(conn_daily_manifest["schedule"]),
                    "first_date": conn_daily_manifest["schedule"][0]["date"],
                    "last_date": conn_daily_manifest["schedule"][-1]["date"],
                    "diagnostics": schedule_diagnostics(conn_daily_manifest, conn_rounds),
                },
                indent=2,
            )
        )
        return 0

    if args.command == "extend-connection-daily-manifest":
        from networked_players_graph_core.connection_daily_manifest import (
            extend_connection_daily_manifest,
            schedule_diagnostics,
            validate_connection_daily_manifest,
        )

        conn_daily_manifest = json.loads(args.manifest.read_text())
        conn_rounds = json.loads(args.rounds.read_text())
        days_before = len(conn_daily_manifest["schedule"])
        conn_daily_extended = extend_connection_daily_manifest(
            conn_daily_manifest, conn_rounds, days=args.days, generated_at=args.generated_at
        )
        validate_connection_daily_manifest(conn_daily_extended, conn_rounds)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(conn_daily_extended, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "days_before": days_before,
                    "days_after": len(conn_daily_extended["schedule"]),
                    "last_date": conn_daily_extended["schedule"][-1]["date"],
                    "diagnostics": schedule_diagnostics(conn_daily_extended, conn_rounds),
                },
                indent=2,
            )
        )
        return 0

    if args.command == "validate-connection-daily-manifest":
        from networked_players_graph_core.connection_daily_manifest import (
            validate_connection_daily_manifest,
        )

        conn_daily_manifest = json.loads(args.manifest.read_text())
        conn_rounds = json.loads(args.rounds.read_text())
        validate_connection_daily_manifest(conn_daily_manifest, conn_rounds)
        print(json.dumps({"ok": True}, indent=2))
        return 0

    if args.command == "connection-daily-manifest-diagnostics":
        from networked_players_graph_core.connection_daily_manifest import schedule_diagnostics

        conn_daily_manifest = json.loads(args.manifest.read_text())
        conn_rounds = json.loads(args.rounds.read_text())
        print(json.dumps(schedule_diagnostics(conn_daily_manifest, conn_rounds), indent=2))
        return 0

    if args.command == "connection-daily-manifest-status":
        from networked_players_graph_core.connection_daily_manifest import schedule_expiry_status

        conn_daily_manifest = json.loads(args.manifest.read_text())
        as_of = args.as_of or datetime.now(UTC).date().isoformat()
        status = schedule_expiry_status(
            conn_daily_manifest, as_of=as_of, warn_within_days=args.warn_within_days
        )
        print(json.dumps(status, indent=2))
        return 1 if status["already_expired"] else 0

    if args.command == "rank-album-candidates":
        from networked_players_graph_core.analysis import rank_album_candidates

        from .discogs.release_format_policy import load_master_exclusions

        candidates = rank_album_candidates(
            args.dataset,
            limit=args.limit,
            memory_limit=args.memory_limit,
            threads=args.threads,
            release_format_policy=args.release_format_policy,
            masters_root=args.masters_root,
            master_exclusions=load_master_exclusions(args.studio_album_exclusions),
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(candidates, indent=2) + "\n")
        summary = {"output": str(args.output), "candidate_count": len(candidates)}
        print(json.dumps(summary, indent=2))
        return 0

    if args.command == "build-album-catalog":
        from networked_players_graph_core.analysis import (
            assemble_album_catalog,
            validate_album_catalog,
        )
        from networked_players_graph_core.graph import CreditGraph

        from .discogs.release_format_policy import load_master_exclusions

        editorial_albums = json.loads(args.editorial_albums.read_text())["albums"]
        candidates = json.loads(args.candidates.read_text())
        allowed_release_ids = None
        if args.release_format_policy is not None:
            policy_payload = json.loads(args.release_format_policy.read_text())
            allowed_release_ids = frozenset(policy_payload["allowed_release_ids"])
        master_exclusions = load_master_exclusions(args.studio_album_exclusions)

        onehop_manifest = json.loads((args.onehop_root / "manifest.json").read_text())
        snapshot_date = str(
            onehop_manifest.get("snapshot_date")
            or onehop_manifest["expansion"]["source_snapshot_date"]
        )

        with CreditGraph.open(
            args.onehop_root,
            memory_limit=args.memory_limit,
            threads=args.threads,
            build_edges=False,
        ) as graph:
            if args.masters_root is not None:
                graph.attach_masters(args.masters_root)
            catalog = assemble_album_catalog(
                graph,
                editorial_albums,
                candidates,
                target_count=args.target_count,
                allowed_release_ids=allowed_release_ids,
                master_exclusions=master_exclusions,
                snapshot_date=snapshot_date,
                generated_by=f"networked-players-catalog build-album-catalog {__version__}",
            )

        validate_album_catalog(catalog)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(catalog, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "catalog_version": catalog["catalog_version"],
                    "editorial_count": catalog["editorial_count"],
                    "editorial_missed": len(catalog["editorial_missed"]),
                    "candidate_count_added": catalog["candidate_count_added"],
                    "total_albums": len(catalog["albums"]),
                },
                indent=2,
            )
        )
        return 0

    if args.command == "validate-album-catalog":
        from networked_players_graph_core.analysis import validate_album_catalog

        catalog = json.loads(args.input.read_text())
        validate_album_catalog(catalog)
        print(json.dumps({"ok": True}, indent=2))
        return 0

    if args.command == "build-public-album-catalog":
        from networked_players_graph_core.analysis import (
            assemble_album_catalog,
            validate_album_catalog,
        )
        from networked_players_graph_core.graph import CreditGraph

        from .discogs.release_format_policy import load_master_exclusions

        onehop_manifest_path = args.onehop_root / "manifest.json"
        if not onehop_manifest_path.is_file():
            raise ValueError(
                f"--onehop-root manifest is required and must exist: {onehop_manifest_path} "
                "not found."
            )
        onehop_manifest = json.loads(onehop_manifest_path.read_text())
        snapshot_date = str(
            onehop_manifest.get("snapshot_date")
            or (onehop_manifest.get("expansion") or {}).get("source_snapshot_date")
            or ""
        )
        if not snapshot_date:
            raise ValueError(
                f"--onehop-root manifest {onehop_manifest_path} has no valid, non-empty "
                "snapshot_date (checked snapshot_date and expansion.source_snapshot_date) -- "
                "unknown snapshot metadata is refused just like a mismatched one."
            )

        if not args.release_format_policy.is_file():
            raise ValueError(
                f"--release-format-policy is required and must exist: {args.release_format_policy} "
                "not found. The public catalog command never falls back to an ungated build."
            )
        policy_payload = json.loads(args.release_format_policy.read_text())
        if policy_payload.get("kind") != "release-format-scoring-index":
            raise ValueError(
                f"--release-format-policy {args.release_format_policy} has kind "
                f"{policy_payload.get('kind')!r}, expected 'release-format-scoring-index' -- "
                "malformed or wrong-artifact input refused"
            )
        allowed_release_ids = policy_payload.get("allowed_release_ids")
        if not allowed_release_ids:
            raise ValueError(
                f"--release-format-policy {args.release_format_policy} has no "
                "allowed_release_ids -- malformed or empty policy, refusing to build an "
                "effectively-ungated catalog"
            )
        policy_snapshot = str(policy_payload.get("snapshot_date") or "")
        if not policy_snapshot:
            raise ValueError(
                f"--release-format-policy {args.release_format_policy} has no valid, "
                "non-empty snapshot_date -- unknown snapshot metadata is refused just like a "
                "mismatched one."
            )
        if policy_snapshot != snapshot_date:
            raise ValueError(
                f"--release-format-policy snapshot_date {policy_snapshot!r} does not match "
                f"--onehop-root snapshot_date {snapshot_date!r} -- mismatched-snapshot inputs "
                "refused"
            )

        if not args.masters_root.is_dir():
            raise ValueError(
                f"--masters-root is required and must exist: {args.masters_root} not found. "
                "The public catalog command never builds without parsed masters (original "
                "years, genre/style non-studio exclusion)."
            )
        masters_manifest_path = args.masters_root / "manifest.json"
        if not masters_manifest_path.is_file():
            raise ValueError(
                f"--masters-root manifest is required and must exist: {masters_manifest_path} "
                "not found -- a masters directory with unknown snapshot metadata is refused "
                "just like a mismatched one."
            )
        masters_manifest = json.loads(masters_manifest_path.read_text())
        masters_snapshot = str(masters_manifest.get("snapshot_date") or "")
        if not masters_snapshot:
            raise ValueError(
                f"--masters-root manifest {masters_manifest_path} has no valid, non-empty "
                "snapshot_date -- unknown snapshot metadata is refused just like a mismatched "
                "one."
            )
        if masters_snapshot != snapshot_date:
            raise ValueError(
                f"--masters-root snapshot_date {masters_snapshot!r} does not match "
                f"--onehop-root snapshot_date {snapshot_date!r} -- mismatched-snapshot "
                "inputs refused"
            )

        if not args.studio_album_exclusions.is_file():
            raise ValueError(
                f"--studio-album-exclusions is required and must exist: "
                f"{args.studio_album_exclusions} not found. The public catalog command never "
                "builds without the curated non-studio-master deny-list."
            )
        exclusions_payload = json.loads(args.studio_album_exclusions.read_text())
        if exclusions_payload.get("policy") != "studio-album-v1":
            raise ValueError(
                f"--studio-album-exclusions {args.studio_album_exclusions} has policy "
                f"{exclusions_payload.get('policy')!r}, expected 'studio-album-v1' -- "
                "malformed or wrong-artifact input refused"
            )
        exclusions_snapshot = str(exclusions_payload.get("snapshot_date") or "")
        if not exclusions_snapshot:
            raise ValueError(
                f"--studio-album-exclusions {args.studio_album_exclusions} has no valid, "
                "non-empty snapshot_date -- unknown snapshot metadata is refused just like a "
                "mismatched one."
            )
        if exclusions_snapshot != snapshot_date:
            raise ValueError(
                f"--studio-album-exclusions snapshot_date {exclusions_snapshot!r} does not "
                f"match --onehop-root snapshot_date {snapshot_date!r} -- mismatched-snapshot "
                "inputs refused"
            )
        exclusions_list = exclusions_payload.get("exclusions")
        if not isinstance(exclusions_list, list):
            raise ValueError(
                f"--studio-album-exclusions {args.studio_album_exclusions} has a missing or "
                "non-array 'exclusions' field -- malformed exclusions structure refused (an "
                "empty array is valid; a missing/wrong-typed field is not)."
            )
        for exclusion_index, item in enumerate(exclusions_list):
            if not isinstance(item, dict) or not isinstance(item.get("master_id"), int):
                raise ValueError(
                    f"--studio-album-exclusions {args.studio_album_exclusions} "
                    f"exclusions[{exclusion_index}] is malformed: every entry must be an "
                    "object with an integer master_id."
                )
        master_exclusions = load_master_exclusions(args.studio_album_exclusions)

        editorial_albums = json.loads(args.editorial_albums.read_text())["albums"]
        candidates = json.loads(args.candidates.read_text())

        with CreditGraph.open(
            args.onehop_root,
            memory_limit=args.memory_limit,
            threads=args.threads,
            build_edges=False,
        ) as graph:
            graph.attach_masters(args.masters_root)
            catalog = assemble_album_catalog(
                graph,
                editorial_albums,
                candidates,
                target_count=args.target_count,
                allowed_release_ids=frozenset(allowed_release_ids),
                master_exclusions=master_exclusions,
                snapshot_date=snapshot_date,
                generated_by=(
                    f"networked-players-catalog build-public-album-catalog {__version__}"
                ),
            )

        validate_album_catalog(catalog)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(catalog, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "catalog_version": catalog["catalog_version"],
                    "editorial_count": catalog["editorial_count"],
                    "editorial_missed": len(catalog["editorial_missed"]),
                    "candidate_count_added": catalog["candidate_count_added"],
                    "total_albums": len(catalog["albums"]),
                },
                indent=2,
            )
        )
        return 0

    if args.command == "build-album-catalog-audit":
        from networked_players_graph_core.catalog_audit import build_album_catalog_audit
        from networked_players_graph_core.graph import CreditGraph

        from .discogs.release_format_policy import load_master_exclusions

        catalog = json.loads(args.catalog.read_text())
        policy_payload = json.loads(args.release_format_policy.read_text())
        allowed_release_ids = frozenset(policy_payload["allowed_release_ids"])
        master_exclusions = load_master_exclusions(args.studio_album_exclusions)

        with CreditGraph.open(
            args.onehop_root,
            memory_limit=args.memory_limit,
            threads=args.threads,
            build_edges=False,
        ) as graph:
            graph.attach_masters(args.masters_root)
            audit = build_album_catalog_audit(
                graph,
                catalog,
                allowed_release_ids=allowed_release_ids,
                master_exclusions=master_exclusions,
            )

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(audit, indent=2) + "\n")
        flags = sum(1 for row in audit["albums"] if row["automated_flags"])
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "catalog_version": audit["catalog_version"],
                    "album_count": len(audit["albums"]),
                    "rows_with_automated_flags": flags,
                },
                indent=2,
            )
        )
        return 0

    if args.command == "validate-album-catalog-audit":
        from networked_players_graph_core.catalog_audit import validate_album_catalog_audit

        catalog = json.loads(args.catalog.read_text())
        audit = json.loads(args.audit.read_text())
        validate_album_catalog_audit(catalog, audit)
        print(json.dumps({"ok": True}, indent=2))
        return 0

    if args.command == "build-album-art-registry":
        from networked_players_contracts.album_art import album_art_failures

        from .discogs.album_art import build_album_art_registry
        from .discogs.api_client import ApiClient, ReleaseCache, load_token

        art_catalog = json.loads(args.catalog.read_text())
        art_client = ApiClient(token=load_token(), request_delay_seconds=args.request_delay)
        art_cache = ReleaseCache(args.cache_dir)
        registry = build_album_art_registry(
            art_catalog,
            client=art_client,
            cache=art_cache,
            generated_at=args.generated_at,
            source=(
                "Discogs API /releases/{id} images, hotlinked from i.discogs.com "
                "(no image bytes stored). See docs/DATA_AND_RIGHTS.md."
            ),
            license_note=(
                "Cover art is presentational only, never evidence. Hotlinked from Discogs' "
                "own CDN; the repository never downloads, stores, or rehosts image bytes."
            ),
        )
        failures = album_art_failures(registry, art_catalog)
        if failures:
            raise ValueError(
                "refusing to write an invalid album-art registry: " + "; ".join(failures)
            )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(registry, indent=2) + "\n")
        total = len(art_catalog["albums"])
        enriched = len(registry["albums"])
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "catalog_version": registry["catalog_version"],
                    "art_version": registry["art_version"],
                    "albums_total": total,
                    "albums_with_art": enriched,
                    "coverage_pct": round(100.0 * enriched / total, 1) if total else 0.0,
                },
                indent=2,
            )
        )
        return 0

    if args.command == "validate-album-art-registry":
        from networked_players_contracts.album_art import album_art_failures

        registry = json.loads(args.registry.read_text())
        art_catalog = json.loads(args.catalog.read_text())
        failures = album_art_failures(registry, art_catalog)
        if failures:
            raise ValueError("; ".join(failures))
        print(json.dumps({"ok": True, "albums_with_art": len(registry["albums"])}, indent=2))
        return 0

    if args.command == "fetch-dataset":
        import sys

        from .discogs.dataset_fetch import fetch_dataset, verify_dataset

        if args.verify_only:
            fetch_result = verify_dataset(args.dest)
        else:
            if not args.base_url:
                print("--base-url is required unless --verify-only is set", file=sys.stderr)
                return 2
            fetch_result = fetch_dataset(
                args.base_url,
                args.dest,
                max_total_bytes=args.max_total_bytes,
                headroom_bytes=args.headroom_bytes,
                timeout_seconds=args.timeout,
                overwrite=args.overwrite,
            )
        print(json.dumps(fetch_result, indent=2))
        return 0

    if args.command == "verify-dataset":
        from .discogs.dataset_fetch import verify_dataset

        print(json.dumps(verify_dataset(args.dest), indent=2))
        return 0

    if args.command == "export-graph-snapshot":
        from networked_players_graph_core.snapshot import export_graph_snapshot

        snapshot_manifest = export_graph_snapshot(
            args.dataset,
            args.output_root,
            memory_limit=args.memory_limit,
            threads=args.threads,
            max_artists_per_release=args.max_artists_per_release,
            temp_dir=args.temp_dir,
            overwrite=args.overwrite,
        )
        print(json.dumps(snapshot_manifest, indent=2, sort_keys=True))
        return 0

    if args.command == "import-cohort-source":
        from .cohort_source.extract import extract_candidates_from_file
        from .cohort_source.source import build_cohort_source_meta

        source = build_cohort_source_meta(
            source_url=args.source_url,
            page_title=args.source_title,
            saved_at=args.saved_at,
            operator_note=args.operator_note,
            raw_html_path=args.input,
        )
        extracted = extract_candidates_from_file(args.input, source=source)
        extracted.write(args.output)
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "candidate_count": len(extracted.candidates),
                    "low_confidence_count": sum(
                        c.confidence == "low" for c in extracted.candidates
                    ),
                    "missing_link_count": sum(
                        c.master_id is None and c.release_id is None for c in extracted.candidates
                    ),
                },
                indent=2,
            )
        )
        return 0

    if args.command == "resolve-cohort":
        from networked_players_graph_core.cohort_resolve import (
            build_resolved_cohort,
            write_resolved_cohort,
        )
        from networked_players_graph_core.graph import CreditGraph

        extracted = json.loads(args.extracted.read_text())
        dataset_manifest = json.loads((args.dataset / "manifest.json").read_text())

        with CreditGraph.open(
            args.dataset,
            memory_limit=args.memory_limit,
            threads=args.threads,
            max_artists_per_release=args.max_artists_per_release,
            temp_dir=args.temp_dir,
        ) as graph:
            resolved_artifact = build_resolved_cohort(
                graph,
                extracted,
                dataset_snapshot_date=str(dataset_manifest["snapshot_date"]),
                max_workers=args.max_workers,
            )

        write_resolved_cohort(resolved_artifact, args.output)
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "resolved_count": len(resolved_artifact["resolved"]),
                    "unresolved_count": len(resolved_artifact["unresolved"]),
                },
                indent=2,
            )
        )
        return 0

    if args.command == "score-cohort-connectivity":
        import sys

        from networked_players_graph_core.cohort_scoring import score_cohort_to_directory

        from .cohort_preflight import memory_limit_preflight_failure

        if not args.skip_preflight:
            preflight_failure = memory_limit_preflight_failure(args.memory_limit)
            if preflight_failure is not None:
                print(preflight_failure, file=sys.stderr)
                return 1

        summary = score_cohort_to_directory(
            resolved_path=args.resolved,
            dataset_path=args.dataset,
            output_dir=args.output_dir,
            memory_limit=args.memory_limit,
            threads=args.threads,
            max_artists_per_release=args.max_artists_per_release,
            temp_dir=args.temp_dir,
            max_hops=args.max_hops,
            max_pairs=args.max_pairs,
            max_frontier_expansion=args.max_frontier_expansion,
            pair_timeout_seconds=args.pair_timeout_seconds,
            max_workers=args.max_workers,
            max_reach_rows=args.max_reach_rows,
            release_format_policy=args.release_format_policy,
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0

    if args.command == "promote-playable-cohort":
        import sys

        from networked_players_graph_core.cohort_promote import (
            promote_playable_cohort,
            write_playable_cohort,
        )

        resolved = json.loads(args.resolved.read_text())
        connectivity = json.loads(args.connectivity.read_text())
        selection = json.loads(args.selection.read_text())

        playable_artifact = promote_playable_cohort(
            resolved, connectivity, selection, cohort_id=args.cohort_id
        )
        write_playable_cohort(playable_artifact, args.output)
        print(
            f"Wrote {args.output}. Before committing, walk the prepublish checklist in "
            "docs/PUBLIC_PRIVATE_BOUNDARY.md -- validate_playable_cohort() checks structure "
            "and known leak patterns, not editorial judgment.",
            file=sys.stderr,
        )
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "album_count": len(playable_artifact["albums"]),
                    "pair_count": len(playable_artifact["pairs"]),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "validate-playable-cohort":
        from networked_players_graph_core.cohort_promote import validate_playable_cohort

        playable_artifact = json.loads(args.input.read_text())
        validate_playable_cohort(playable_artifact)
        print(json.dumps({"ok": True}, indent=2))
        return 0

    if args.command == "validate-connectivity":
        from networked_players_graph_core.cohort_connectivity import validate_connectivity

        connectivity_artifact = json.loads(args.input.read_text())
        validate_connectivity(connectivity_artifact)
        print(json.dumps({"ok": True}, indent=2))
        return 0

    if args.command == "draft-cohort-review":
        from networked_players_graph_core.cohort_promote import draft_selection_template

        connectivity = json.loads(args.connectivity.read_text())
        template = draft_selection_template(connectivity)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(template, indent=2, sort_keys=True) + "\n")

        clean_count = sum(1 for c in template["candidate_pairs"] if not c["warnings"])
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "candidate_count": len(template["candidate_pairs"]),
                    "clean_count": clean_count,
                    "flagged_count": len(template["candidate_pairs"]) - clean_count,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "draft-cohort-editorial-review":
        from .cohort_editorial import build_editorial_packet, write_editorial_packet

        resolved = json.loads(args.resolved.read_text())
        connectivity = json.loads(args.connectivity.read_text())
        if args.enrich_images:
            from .discogs.api_client import ApiClient, ReleaseCache, fetch_releases, load_token

            release_ids = sorted(
                {int(album["release_id"]) for album in resolved.get("resolved", [])}
            )
            fetch_releases(
                release_ids,
                client=ApiClient(token=load_token(), request_delay_seconds=args.request_delay),
                cache=ReleaseCache(args.api_cache_dir),
            )
        from networked_players_graph_core.graph import CreditGraph

        from .cohort_editorial import EvidenceLookup

        evidence_graph: CreditGraph | None = None
        lookup: EvidenceLookup | None = None
        if args.dataset is not None:
            # `build_edges=False`: explaining hops that were already found needs
            # evidence rows, not traversal, and skips the ~2.5 minute
            # credit_edges materialization.
            evidence_graph = CreditGraph.open(args.dataset, build_edges=False)
            opened = evidence_graph

            def lookup_evidence(
                release_id: int, artist_ids: set[int]
            ) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
                return opened.release(release_id), opened.credit_rows(release_id, artist_ids)

            lookup = lookup_evidence
        try:
            packet = build_editorial_packet(
                resolved,
                connectivity,
                args.api_cache_dir,
                evidence_lookup=lookup,
            )
        finally:
            if evidence_graph is not None:
                evidence_graph.close()
        write_editorial_packet(packet, args.output_json, args.output_markdown)
        print(
            json.dumps(
                {
                    "output_json": str(args.output_json),
                    "output_markdown": str(args.output_markdown),
                    "suggested_count": len(packet["suggested_pairs"]),
                    "review_required_count": packet["review_required_count"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "cohort-pipeline-status":
        from .cohort_status import build_status_report, format_status_report

        report = build_status_report(
            source_id=args.source_id,
            analysis_dir=args.analysis_dir,
            review_dir=args.review_dir,
            promoted_artifact=args.promoted_artifact,
            web_manifest=args.web_manifest,
            web_import_map=args.web_import_map,
            jobs_dir=args.jobs_dir,
        )
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(format_status_report(report))
        return 0

    if args.command == "cohort-pipeline-preflight":
        from .cohort_preflight import build_preflight_report, format_preflight_report

        report = build_preflight_report(
            source_id=args.source_id,
            source_html=args.source_html,
            parsed_dataset=args.parsed_dataset,
            onehop_dataset=args.onehop_dataset,
            source_url=args.source_url,
            source_title=args.source_title,
        )
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(format_preflight_report(report))
        return 0 if report["ready"] else 1

    raise AssertionError(f"unhandled command: {args.command}")
