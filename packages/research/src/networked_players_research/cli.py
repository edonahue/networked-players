"""CLI for the Networked Players research platform (Phase 3). Granular
subcommands (`research-resolve-seed`, `research-build-corpus`,
`research-analyze`, `research-report`) plus one composed convenience
command (`research-run`) -- the same "granular commands plus one composed
command" shape `networked-players-catalog`'s CLI already uses elsewhere
(e.g. `build-album-catalog` over `rank_album_candidates`/
`assemble_album_catalog`).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from .analyses import ANALYSIS_REGISTRY
from .corpus import (
    AmbiguousSeedError,
    NoSeedMatchError,
    TopicCorpusError,
    build_topic_corpus,
    resolve_artist_seed,
)
from .report import (
    ResearchReportError,
    render_markdown_report,
    write_findings,
    write_promotion_candidates,
)
from .request import ResearchRequest, ResearchRequestError, load_request
from .runs import RESEARCH_ROOT, corpus_root, new_run_id, new_run_paths, write_run_manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="networked-players-research")
    subparsers = parser.add_subparsers(dest="command", required=True)

    resolve = subparsers.add_parser(
        "research-resolve-seed", help="resolve a seed artist name to a real artist_id"
    )
    resolve.add_argument("--dataset", type=Path, required=True, help="parsed snapshot root")
    resolve.add_argument("--name", required=True)

    build_corpus = subparsers.add_parser(
        "research-build-corpus", help="resolve seeds and build a bounded topic corpus"
    )
    build_corpus.add_argument("--config", type=Path, required=True, help="request.json path")
    build_corpus.add_argument("--dataset", type=Path, required=True, help="parsed snapshot root")
    build_corpus.add_argument("--research-root", type=Path, default=RESEARCH_ROOT)
    build_corpus.add_argument("--overwrite", action="store_true")

    analyze = subparsers.add_parser(
        "research-analyze", help="run configured analyses against a built corpus"
    )
    analyze.add_argument("--config", type=Path, required=True)
    analyze.add_argument("--research-root", type=Path, default=RESEARCH_ROOT)
    analyze.add_argument("--run-id")

    report = subparsers.add_parser(
        "research-report", help="render a run's analysis outputs and findings into a report"
    )
    report.add_argument("--research-root", type=Path, default=RESEARCH_ROOT)
    report.add_argument("--config", type=Path, required=True)
    report.add_argument("--run-id", required=True)

    run = subparsers.add_parser(
        "research-run", help="composed: resolve seeds, build corpus, analyze, report"
    )
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--dataset", type=Path, required=True)
    run.add_argument("--research-root", type=Path, default=RESEARCH_ROOT)
    run.add_argument("--overwrite-corpus", action="store_true")

    graph_benchmark = subparsers.add_parser(
        "research-graph-benchmark",
        help=(
            "compare NetworkX/igraph/rustworkx at topic-corpus scale "
            "(docs/RESEARCH_GRAPH_BENCHMARK_METHOD.md); requires the "
            "'graph' extra (uv sync --package networked-players-research --extra graph)"
        ),
    )
    graph_benchmark.add_argument(
        "--corpus-snapshot",
        type=Path,
        required=True,
        help="a built topic corpus's snapshot=<date>/ dir",
    )
    graph_benchmark.add_argument(
        "--output", type=Path, default=None, help="optional JSON report path (local-only)"
    )

    return parser


def _open_credits_view(dataset_root: Path) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(database=":memory:")
    credits_glob = str(dataset_root / "table=credits" / "*.parquet")
    connection.execute(
        "CREATE VIEW credits AS SELECT * FROM "
        f"read_parquet('{credits_glob}', hive_partitioning=false)"
    )
    return connection


def _resolve_seeds(dataset_root: Path, names: list[str]) -> list[int]:
    connection = _open_credits_view(dataset_root)
    try:
        artist_ids = []
        for name in names:
            resolution = resolve_artist_seed(connection, name)
            print(
                f"resolved {name!r} -> artist_id={resolution.artist_id} "
                f"({resolution.matched_credits} credits)",
                file=sys.stderr,
            )
            artist_ids.append(resolution.artist_id)
        return artist_ids
    finally:
        connection.close()


def _build_corpus(
    config_path: Path, dataset_root: Path, research_root: Path, *, overwrite: bool
) -> dict[str, Any]:
    request = load_request(config_path)
    seed_artist_ids = _resolve_seeds(dataset_root, list(request.seed_artist_names))
    output_root = research_root / request.topic_slug() / "corpus"
    manifest = build_topic_corpus(
        seed_artist_ids,
        dataset_root,
        output_root,
        topic=request.topic,
        hop_tier=request.hop_tier,
        overwrite=overwrite,
    )
    return manifest


def _latest_corpus_snapshot(research_root: Path, topic_slug: str) -> Path:
    root = corpus_root(topic_slug, research_root=research_root)
    snapshots = sorted(root.glob("snapshot=*"))
    if not snapshots:
        raise TopicCorpusError(f"no corpus built for topic {topic_slug!r} under {root}")
    return snapshots[-1]


def _run_analyses(request: ResearchRequest, snapshot_root: Path) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for name in request.analyses:
        analysis_fn = ANALYSIS_REGISTRY.get(name)
        if analysis_fn is None:
            print(f"skipping {name!r}: not yet implemented (see Slice D)", file=sys.stderr)
            continue
        results[name] = analysis_fn(snapshot_root)
    return results


def _write_analysis_outputs(analysis_dir: Path, results: dict[str, dict[str, Any]]) -> None:
    analysis_dir.mkdir(parents=True, exist_ok=True)
    for name, result in results.items():
        (analysis_dir / f"{name}.json").write_text(
            json.dumps(result, indent=2, sort_keys=True, default=str) + "\n"
        )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "research-resolve-seed":
            connection = _open_credits_view(args.dataset)
            try:
                resolution = resolve_artist_seed(connection, args.name)
            finally:
                connection.close()
            print(
                json.dumps(
                    {
                        "artist_id": resolution.artist_id,
                        "name": resolution.name,
                        "matched_credits": resolution.matched_credits,
                    },
                    indent=2,
                )
            )
            return 0

        if args.command == "research-build-corpus":
            manifest = _build_corpus(
                args.config, args.dataset, args.research_root, overwrite=args.overwrite
            )
            print(json.dumps(manifest, indent=2, sort_keys=True))
            return 0

        if args.command == "research-analyze":
            request = load_request(args.config)
            snapshot_root = _latest_corpus_snapshot(args.research_root, request.topic_slug())
            results = _run_analyses(request, snapshot_root)
            run_paths = new_run_paths(
                request.topic_slug(), args.run_id, research_root=args.research_root
            )
            run_paths.ensure_dirs()
            _write_analysis_outputs(run_paths.analysis_dir, results)
            print(json.dumps({"run_root": str(run_paths.root), "analyses_run": sorted(results)}))
            return 0

        if args.command == "research-report":
            request = load_request(args.config)
            run_paths = new_run_paths(
                request.topic_slug(), args.run_id, research_root=args.research_root
            )
            results = {
                path.stem: json.loads(path.read_text())
                for path in sorted(run_paths.analysis_dir.glob("*.json"))
            }
            findings = write_findings(run_paths.findings_path, results)
            write_promotion_candidates(run_paths.promotion_candidates_path)
            report_text = render_markdown_report(
                topic=request.topic,
                run_id=args.run_id,
                questions=list(request.questions),
                analysis_results=results,
                findings=findings,
            )
            (run_paths.report_dir / "index.md").write_text(report_text)
            print(
                json.dumps({"run_root": str(run_paths.root), "findings": len(findings["findings"])})
            )
            return 0

        if args.command == "research-run":
            started_at = datetime.now(UTC).isoformat()
            request = load_request(args.config)
            corpus_manifest = _build_corpus(
                args.config, args.dataset, args.research_root, overwrite=args.overwrite_corpus
            )
            snapshot_root = _latest_corpus_snapshot(args.research_root, request.topic_slug())
            results = _run_analyses(request, snapshot_root)

            run_id = new_run_id()
            run_paths = new_run_paths(
                request.topic_slug(), run_id, research_root=args.research_root
            )
            run_paths.ensure_dirs()
            request_payload = json.loads(args.config.read_text())
            run_paths.request_path.write_text(
                json.dumps(request_payload, indent=2, sort_keys=True) + "\n"
            )
            _write_analysis_outputs(run_paths.analysis_dir, results)

            findings = write_findings(run_paths.findings_path, results)
            write_promotion_candidates(run_paths.promotion_candidates_path)
            report_text = render_markdown_report(
                topic=request.topic,
                run_id=run_id,
                questions=list(request.questions),
                analysis_results=results,
                findings=findings,
            )
            (run_paths.report_dir / "index.md").write_text(report_text)

            finished_at = datetime.now(UTC).isoformat()
            write_run_manifest(
                run_paths,
                topic=request.topic,
                run_id=run_id,
                corpus_version=str(corpus_manifest["topic"]["corpus_version"]),
                analyses=sorted(results),
                started_at=started_at,
                finished_at=finished_at,
            )
            print(json.dumps({"run_id": run_id, "run_root": str(run_paths.root)}, indent=2))
            return 0

        if args.command == "research-graph-benchmark":
            from .graph_bench import run_benchmark

            report = run_benchmark(args.corpus_snapshot)
            if args.output is not None:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0

        raise AssertionError(f"unhandled command: {args.command}")
    except (
        ResearchRequestError,
        TopicCorpusError,
        AmbiguousSeedError,
        NoSeedMatchError,
        ResearchReportError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
