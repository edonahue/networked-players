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

    validate = subparsers.add_parser("validate", help="validate a normalized snapshot with DuckDB")
    validate.add_argument("--dataset", type=Path, required=True)

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

    if args.command == "validate":
        from .discogs.validation import validate_dataset

        print(json.dumps(validate_dataset(args.dataset), indent=2, sort_keys=True))
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

    raise AssertionError(f"unhandled command: {args.command}")
