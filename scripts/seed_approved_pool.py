"""Seed or re-check `data/albums/approved-pool-v1.json` from the published catalog.

    uv run python scripts/seed_approved_pool.py          # print the seed to stdout
    uv run python scripts/seed_approved_pool.py --write  # write data/albums/approved-pool-v1.json
    uv run python scripts/seed_approved_pool.py --check  # exit 1 if the file differs from the seed

The seed is for the INITIAL pool only (every album published when the pool was
introduced). After that the pool is extended by owner-approved entries, never
regenerated from the catalog -- the pool is the authority, the catalog follows it.
Reads only committed public files.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from networked_players_contracts.approved_pool import seed_approved_pool_from_catalog

NOTE = (
    "Cumulative list of every album approved for publication (ADR 0072 section 2). "
    "Public labels only: master_id, the round that added it, and ADR 0069's selection_source. "
    "The published catalog must contain exactly these albums."
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog", type=Path, default=Path("apps/web/public/data/catalog/albums.v1.json")
    )
    parser.add_argument("--pool", type=Path, default=Path("data/albums/approved-pool-v1.json"))
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    args = parser.parse_args()

    seed = json.dumps(
        seed_approved_pool_from_catalog(json.loads(args.catalog.read_text()), note=NOTE),
        indent=2,
    )
    seed += "\n"
    if args.write:
        args.pool.write_text(seed)
        print(f"wrote {args.pool}")
        return 0
    if args.check:
        if args.pool.read_text() != seed:
            print(f"{args.pool} differs from the catalog-derived seed", file=sys.stderr)
            return 1
        return 0
    print(seed, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
