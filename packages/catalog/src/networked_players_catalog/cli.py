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
            "build a real, performer-only universe.v1/rounds.v1 artifact pair "
            "from a one-hop dataset"
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

    build_daily = subparsers.add_parser(
        "build-daily-manifest",
        help="build a frozen date->round_id schedule for Connection of the Day",
    )
    build_daily.add_argument("--rounds", type=Path, required=True)
    build_daily.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    build_daily.add_argument("--days", type=int, default=365)
    build_daily.add_argument("--output", type=Path, required=True)

    extend_daily = subparsers.add_parser(
        "extend-daily-manifest",
        help="append new dates to an existing daily manifest without touching history",
    )
    extend_daily.add_argument("--manifest", type=Path, required=True)
    extend_daily.add_argument("--rounds", type=Path, required=True)
    extend_daily.add_argument("--days", type=int, default=365)
    extend_daily.add_argument("--output", type=Path, required=True)

    validate_daily = subparsers.add_parser(
        "validate-daily-manifest", help="validate a daily-manifest.v1 artifact against its contract"
    )
    validate_daily.add_argument("--manifest", type=Path, required=True)
    validate_daily.add_argument("--rounds", type=Path, required=True)

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

    build_album_catalog = subparsers.add_parser(
        "build-album-catalog",
        help=(
            "combine the editorial album list with rank-album-candidates output into a "
            "generated, non-committed --albums input for build-challenge-from-dump (ADR 0037)"
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
        albums = json.loads(args.albums.read_text())["albums"]
        # An ID-resolved album (e.g. build-album-catalog's output) carries
        # artist_id directly; re-matching it by name string would reopen the
        # exact collision risk resolving it once already closed.
        albums_are_resolved = bool(albums) and "artist_id" in albums[0]

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
                missed: list[dict[str, str]] = []
            else:
                matched, missed = match_albums(
                    graph, albums, allowed_release_ids=allowed_release_ids
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

    if args.command == "rank-album-candidates":
        from networked_players_graph_core.analysis import rank_album_candidates

        candidates = rank_album_candidates(
            args.dataset,
            limit=args.limit,
            memory_limit=args.memory_limit,
            threads=args.threads,
            release_format_policy=args.release_format_policy,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(candidates, indent=2) + "\n")
        summary = {"output": str(args.output), "candidate_count": len(candidates)}
        print(json.dumps(summary, indent=2))
        return 0

    if args.command == "build-album-catalog":
        from networked_players_graph_core.analysis import assemble_album_catalog
        from networked_players_graph_core.graph import CreditGraph

        editorial_albums = json.loads(args.editorial_albums.read_text())["albums"]
        candidates = json.loads(args.candidates.read_text())
        allowed_release_ids = None
        if args.release_format_policy is not None:
            policy_payload = json.loads(args.release_format_policy.read_text())
            allowed_release_ids = frozenset(policy_payload["allowed_release_ids"])

        with CreditGraph.open(
            args.onehop_root,
            memory_limit=args.memory_limit,
            threads=args.threads,
            build_edges=False,
        ) as graph:
            catalog = assemble_album_catalog(
                graph,
                editorial_albums,
                candidates,
                target_count=args.target_count,
                allowed_release_ids=allowed_release_ids,
            )

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(catalog, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "editorial_count": catalog["editorial_count"],
                    "editorial_missed": len(catalog["editorial_missed"]),
                    "candidate_count_added": catalog["candidate_count_added"],
                    "total_albums": len(catalog["albums"]),
                },
                indent=2,
            )
        )
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
