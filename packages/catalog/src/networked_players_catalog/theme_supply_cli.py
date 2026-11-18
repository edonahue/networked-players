"""CLI for the theme-seed supply stage and the post-approval one-hop re-widen seed
(Campaign Atlas SS). The logic lives in `networked_players_graph_core.theme_supply`;
this module is argument wiring plus the output-path guards.

Commands:

- `validate-round-seed-spec`: shape-check a round seed spec (dependency-free contract).
- `build-theme-candidates`: supply candidate masters for a round's themes from the FULL
  parsed corpus. Output is private and refused unless it is git-ignored.
- `build-rewiden-seed`: turn the approved pool into the editorial-seed-shaped file
  `expand-one-hop --additional-seed` needs, so the one-hop corpus is re-widened only
  for approved albums.

Every input is required: there are no silent defaults.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any


class ThemeSupplyError(ValueError):
    """Bad input or a refused output path."""


def require_private_ignored_output(output: Path, *, command: str) -> None:
    """Refuse an output that could be committed or published: it must resolve under a
    real `local/` or `data/private/` directory, outside `apps/web/public/`, and, when
    inside a Git work tree, Git itself must report it ignored."""
    from .review_packet import ReviewPacketError, require_review_output

    resolved = output.resolve()
    if "local" not in resolved.parts and not any(
        resolved.parts[i : i + 2] == ("data", "private") for i in range(len(resolved.parts))
    ):
        raise ThemeSupplyError(
            f"{command} refuses to write outside local/ or data/private/: {str(output)!r} "
            "-- candidate lists are private, pre-decision data"
        )
    try:
        require_review_output(output)
    except ReviewPacketError as error:
        raise ThemeSupplyError(f"{command}: {error}") from error


def _read_json(path: Path, what: str) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ThemeSupplyError(f"cannot read {what} {path}: {error}") from error


def load_valid_round_seed_spec(path: Path) -> dict[str, Any]:
    from networked_players_contracts.round_seed_spec import round_seed_spec_failures

    spec = _read_json(path, "round seed spec")
    failures = round_seed_spec_failures(spec)
    if failures:
        raise ThemeSupplyError(
            f"round seed spec {path} is invalid:\n" + "\n".join(f"  - {f}" for f in failures)
        )
    assert isinstance(spec, dict)
    return spec


def register_theme_supply_parsers(subparsers: Any) -> None:
    validate = subparsers.add_parser(
        "validate-round-seed-spec",
        help="validate a committed round seed spec (data/rounds/round-<n>-seed-spec-v1.json)",
    )
    validate.add_argument("--spec", type=Path, required=True)

    theme = subparsers.add_parser(
        "build-theme-candidates",
        help=(
            "theme-seed candidate SUPPLY from the FULL parsed corpus (Campaign Atlas SS, "
            "ADR 0072 section 7): seed artists' masters plus masters sharing performers with "
            "the seed masters, bounded by decade, tags and a per-theme cap, then master-level "
            "studio-album eligibility. Local-only output; naming a theme approves no album"
        ),
    )
    theme.add_argument("--seed-spec", type=Path, required=True)
    theme.add_argument(
        "--dataset", type=Path, required=True, help="FULL parsed snapshot root (not one-hop)"
    )
    theme.add_argument("--masters-root", type=Path, required=True)
    theme.add_argument(
        "--release-format-policy",
        type=Path,
        required=True,
        help="release-format scoring index (the one-hop one is fine; it has no entries for "
        "masters outside the one-hop corpus -- see --classify-pool-releases)",
    )
    theme.add_argument(
        "--classify-pool-releases",
        action="store_true",
        help=(
            "ALSO classify, from --dataset, only the releases under the capped theme pool's "
            "masters (bounded; same rules) and use the explicit UNION with "
            "--release-format-policy. Required for themes outside the one-hop corpus"
        ),
    )
    theme.add_argument("--studio-album-exclusions", type=Path, required=True)
    theme.add_argument(
        "--already-published-catalog",
        type=Path,
        required=True,
        help="apps/web/public/data/catalog/albums.v1.json: published masters are dropped",
    )
    theme.add_argument("--output", type=Path, required=True, help="private, git-ignored path")
    theme.add_argument("--memory-limit", default="3GB")
    theme.add_argument("--threads", type=int, default=2)
    theme.add_argument("--quiet", action="store_true")

    rewiden = subparsers.add_parser(
        "build-rewiden-seed",
        help=(
            "post-approval re-widen seed (Campaign Atlas SS): the committed editorial seed "
            "plus one entry per approved-pool master, in the shape expand-one-hop "
            "--additional-seed reads. Run expand-one-hop with it to re-widen the one-hop "
            "corpus only for approved albums"
        ),
    )
    rewiden.add_argument("--approved-pool", type=Path, required=True)
    rewiden.add_argument(
        "--editorial-seed",
        type=Path,
        required=True,
        help="data/albums/editorial-seed-v1.json: carried forward so the corpus never shrinks",
    )
    rewiden.add_argument("--dataset", type=Path, required=True, help="FULL parsed snapshot root")
    rewiden.add_argument("--masters-root", type=Path, required=True)
    rewiden.add_argument("--generated-at", required=True, help="explicit ISO datetime with offset")
    rewiden.add_argument("--output", type=Path, required=True, help="private, git-ignored path")
    rewiden.add_argument("--memory-limit", default="3GB")
    rewiden.add_argument("--threads", type=int, default=2)


def run_theme_supply_command(args: argparse.Namespace) -> int:
    try:
        if args.command == "validate-round-seed-spec":
            spec = load_valid_round_seed_spec(args.spec)
            from networked_players_contracts.round_seed_spec import lane_quotas

            print(
                json.dumps(
                    {"ok": True, "round": spec["round"], "lane_quotas": lane_quotas(spec)},
                    indent=2,
                )
            )
            return 0
        if args.command == "build-theme-candidates":
            return _build_theme_candidates(args)
        return _build_rewiden_seed(args)
    except ThemeSupplyError as error:
        print(f"{args.command}: {error}", file=sys.stderr)
        return 1


def _build_theme_candidates(args: argparse.Namespace) -> int:
    from networked_players_graph_core.graph import CreditGraph
    from networked_players_graph_core.theme_supply import derive_theme_candidates

    from .discogs.release_format_policy import load_master_exclusions

    require_private_ignored_output(args.output, command="build-theme-candidates")
    spec = load_valid_round_seed_spec(args.seed_spec)
    catalog = _read_json(args.already_published_catalog, "published catalog")
    published = frozenset(
        int(a["master_id"]) for a in catalog.get("albums", []) if a.get("master_id") is not None
    )
    allowed = frozenset(_read_json(args.release_format_policy, "policy")["allowed_release_ids"])
    classify = None
    if args.classify_pool_releases:
        from .discogs.release_format_policy import (
            build_release_format_policy,
            build_release_format_scoring_index,
            merge_release_format_scoring_indexes,
        )

        base_index = _read_json(args.release_format_policy, "policy")

        def classify(release_ids: Sequence[int]) -> frozenset[int]:
            policy = build_release_format_policy(
                args.dataset,
                release_ids=release_ids,
                memory_limit=args.memory_limit,
                threads=args.threads,
            )
            bounded = build_release_format_scoring_index(policy)
            try:
                merged = merge_release_format_scoring_indexes(base_index, bounded)
            except ValueError as error:
                raise ThemeSupplyError(
                    f"cannot union with --release-format-policy: {error}"
                ) from error
            return frozenset(int(r) for r in merged["allowed_release_ids"])

    with CreditGraph.open(
        args.dataset, memory_limit=args.memory_limit, threads=args.threads, build_edges=False
    ) as graph:
        graph.attach_masters(args.masters_root)
        rows, summaries = derive_theme_candidates(
            graph,
            args.dataset,
            args.masters_root,
            spec,
            allowed_release_ids=allowed,
            classify_pool_releases=classify,
            master_exclusions=load_master_exclusions(args.studio_album_exclusions),
            already_published_master_ids=published,
            memory_limit=args.memory_limit,
            threads=args.threads,
            quiet=args.quiet,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(rows, indent=2) + "\n")
    eligible = sum(1 for row in rows if row["eligibility"] == "eligible")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "round": spec["round"],
                "candidate_count": len(rows),
                "eligible_count": eligible,
                "themes": summaries,
            },
            indent=2,
        )
    )
    return 0


def _build_rewiden_seed(args: argparse.Namespace) -> int:
    from datetime import datetime

    from networked_players_contracts.approved_pool import approved_pool_failures
    from networked_players_graph_core.editorial_seed import editorial_seed_failures
    from networked_players_graph_core.theme_supply import build_rewiden_seed

    require_private_ignored_output(args.output, command="build-rewiden-seed")
    try:
        if datetime.fromisoformat(args.generated_at).tzinfo is None:
            raise ValueError
    except ValueError as error:
        raise ThemeSupplyError(
            "--generated-at must be an ISO datetime with a UTC offset"
        ) from error
    pool = _read_json(args.approved_pool, "approved pool")
    pool_failures = approved_pool_failures(pool)
    if pool_failures:
        raise ThemeSupplyError(f"approved pool {args.approved_pool} is malformed: {pool_failures}")
    base = _read_json(args.editorial_seed, "editorial seed")
    base_failures = editorial_seed_failures(base)
    if base_failures:
        raise ThemeSupplyError(
            f"editorial seed {args.editorial_seed} is malformed: {base_failures}"
        )
    manifest = _read_json(args.dataset / "manifest.json", "full corpus manifest")
    payload, unresolved = build_rewiden_seed(
        args.dataset,
        args.masters_root,
        approved_master_ids=[int(a["master_id"]) for a in pool["albums"]],
        base_editorial_seed=base,
        snapshot_date=str(manifest["snapshot_date"]),
        generated_at=args.generated_at,
        generated_by="networked-players-catalog build-rewiden-seed",
        note="Approved-pool re-widen seed: public album identities only.",
        memory_limit=args.memory_limit,
        threads=args.threads,
    )
    if unresolved:
        raise ThemeSupplyError(
            f"{len(unresolved)} approved masters cannot be seeded (no main release or no billed "
            f"playable artist in the full corpus): {unresolved}. Nothing was written; fix the "
            "pool or the corpus, never re-widen without them"
        )
    seed_failures = editorial_seed_failures(payload)
    if seed_failures:
        raise ThemeSupplyError(f"generated seed failed its own contract: {seed_failures}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "album_count": len(payload["albums"]),
                "approved_count": len(pool["albums"]),
                "snapshot_date": payload["snapshot_date"],
            },
            indent=2,
        )
    )
    return 0


def git_check_ignored(path: Path) -> bool:
    """True when Git reports `path` ignored (used by tests and the runner precheck)."""
    return (
        subprocess.run(
            ["git", "check-ignore", "-q", "--", str(path)], capture_output=True, check=False
        ).returncode
        == 0
    )
