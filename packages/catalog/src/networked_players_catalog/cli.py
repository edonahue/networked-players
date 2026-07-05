"""Command-line entry point for the initial catalog vertical slice."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
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

    validate = subparsers.add_parser("validate", help="validate a normalized snapshot with DuckDB")
    validate.add_argument("--dataset", type=Path, required=True)

    validate_masters = subparsers.add_parser(
        "validate-masters", help="validate a parsed masters dataset with DuckDB"
    )
    validate_masters.add_argument("--dataset", type=Path, required=True)

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
    build_challenge.add_argument("--max-artists-per-release", type=int, default=50)
    build_challenge.add_argument("--memory-limit", default="1GB")
    build_challenge.add_argument("--threads", type=int, default=2)
    build_challenge.add_argument("--enrich-images", action="store_true")
    build_challenge.add_argument(
        "--cache-dir", type=Path, default=Path("data/private/discogs-api-cache")
    )
    build_challenge.add_argument("--request-delay", type=float, default=1.1)

    validate_challenge = subparsers.add_parser(
        "validate-challenge", help="validate a challenge.v2 artifact against its contract"
    )
    validate_challenge.add_argument("--input", type=Path, required=True)

    rank_albums = subparsers.add_parser(
        "rank-album-candidates",
        help="rank master_ids by release-variant count x credit richness (local-only shortlist)",
    )
    rank_albums.add_argument("--dataset", type=Path, required=True)
    rank_albums.add_argument("--output", type=Path, required=True)
    rank_albums.add_argument("--limit", type=int, default=200)
    rank_albums.add_argument("--memory-limit", default="3GB")
    rank_albums.add_argument("--threads", type=int, default=2)

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
        "--max-frontier-expansion",
        type=int,
        default=300,
        help="release-count proxy threshold above which an artist is excluded from BFS "
        "expansion (still reachable as a target); a real hub in production has been "
        "measured with 500-1900+, this default is a conservative heuristic, not a "
        "precise percentile -- tune per cohort/dataset",
    )
    score_connectivity.add_argument(
        "--pair-timeout-seconds",
        type=float,
        default=30.0,
        help="wall-clock budget for each cohort artist's own BFS expansion; on timeout "
        "every pair needing that artist's search is reported status=skipped rather "
        "than hanging or guessing",
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

    if args.command == "validate":
        from .discogs.validation import validate_dataset

        print(json.dumps(validate_dataset(args.dataset), indent=2, sort_keys=True))
        return 0

    if args.command == "validate-masters":
        from .discogs.validation import validate_master_dataset

        print(json.dumps(validate_master_dataset(args.dataset), indent=2, sort_keys=True))
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

        from networked_players_graph_core.challenge import build_challenge_v2, validate_challenge
        from networked_players_graph_core.graph import CreditGraph

        onehop_manifest_path = args.onehop_root / "manifest.json"
        onehop_manifest = json.loads(onehop_manifest_path.read_text())
        snapshot_date = str(onehop_manifest["expansion"]["source_snapshot_date"])
        albums = json.loads(args.albums.read_text())["albums"]

        with CreditGraph.open(
            args.onehop_root,
            memory_limit=args.memory_limit,
            threads=args.threads,
            max_artists_per_release=args.max_artists_per_release,
        ) as graph:
            if args.masters_root is not None:
                graph.attach_masters(args.masters_root)

            artifact, report = build_challenge_v2(
                graph,
                albums,
                snapshot_date=snapshot_date,
                generated_by=f"networked-players-catalog build-challenge-from-dump {__version__}",
                max_paths=args.max_paths,
                max_hops=args.max_hops,
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

    if args.command == "rank-album-candidates":
        from networked_players_graph_core.analysis import rank_album_candidates

        candidates = rank_album_candidates(
            args.dataset,
            limit=args.limit,
            memory_limit=args.memory_limit,
            threads=args.threads,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(candidates, indent=2) + "\n")
        summary = {"output": str(args.output), "candidate_count": len(candidates)}
        print(json.dumps(summary, indent=2))
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
        from networked_players_graph_core.cohort_connectivity import (
            build_connectivity_cohort,
            summarize_connectivity,
            validate_connectivity,
            write_connectivity_cohort,
        )
        from networked_players_graph_core.graph import CreditGraph

        resolved = json.loads(args.resolved.read_text())
        dataset_manifest = json.loads((args.dataset / "manifest.json").read_text())

        with CreditGraph.open(
            args.dataset,
            memory_limit=args.memory_limit,
            threads=args.threads,
            max_artists_per_release=args.max_artists_per_release,
            temp_dir=args.temp_dir,
        ) as graph:
            connectivity_artifact = build_connectivity_cohort(
                graph,
                resolved,
                dataset_snapshot_date=str(dataset_manifest["snapshot_date"]),
                max_hops=args.max_hops,
                max_pairs=args.max_pairs,
                max_frontier_expansion=args.max_frontier_expansion,
                pair_timeout_seconds=args.pair_timeout_seconds,
            )

        validate_connectivity(connectivity_artifact)
        playable_pairs, report_markdown = summarize_connectivity(connectivity_artifact)

        args.output_dir.mkdir(parents=True, exist_ok=True)
        write_connectivity_cohort(connectivity_artifact, args.output_dir / "connectivity.json")
        (args.output_dir / "playable-pairs.json").write_text(
            json.dumps(playable_pairs, indent=2, sort_keys=True) + "\n"
        )
        (args.output_dir / "review-report.md").write_text(report_markdown)

        by_status = {"found": 0, "no_path": 0, "skipped": 0}
        by_difficulty = {"easy": 0, "medium": 0, "hard": 0, "very_hard": 0}
        flagged_pair_count = 0
        for pair in connectivity_artifact["pairs"]:
            by_status[pair["status"]] += 1
            if pair["status"] == "found":
                by_difficulty[pair["difficulty"]] += 1
            if pair["warnings"]:
                flagged_pair_count += 1

        print(
            json.dumps(
                {
                    "output_dir": str(args.output_dir),
                    "pair_count": len(connectivity_artifact["pairs"]),
                    "by_status": by_status,
                    "by_difficulty": by_difficulty,
                    "flagged_pair_count": flagged_pair_count,
                },
                indent=2,
                sort_keys=True,
            )
        )
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

    raise AssertionError(f"unhandled command: {args.command}")
