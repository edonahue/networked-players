#!/usr/bin/env python3
"""Check for a partially-completed (interrupted or still-running) Discogs
ingest staging directory, and report exactly how much real, VALID output
survives.

packages/catalog's write_release_dataset() (parquet.py) writes each part
file DIRECTLY to its final filename -- no atomic temp-file-then-rename --
and keeps at most one background write in flight at a time. A hard kill
(SIGKILL, power loss, OOM-kill, Ctrl-C -- none of which trigger
write_release_dataset()'s own `except Exception: shutil.rmtree(...)`
cleanup, since none of those raise a catchable Exception) can leave the
LAST part(s) truncated or corrupt on disk, even though every earlier part
is safe (each earlier part's write already fully completed and closed
before the next one started -- writes are sequential, never concurrent). A
clean application-level crash (an ordinary Python exception during
parsing) already self-cleans via that same except-block, so there's
nothing to recover in that case -- this script is specifically for the
OTHER case.

Read-only: never modifies or deletes anything. Safe to run against a
STILL-RUNNING ingest too -- useful for exactly that: distinguishing "done
so far, confirmed valid" from "currently being written, don't trust yet."

Output is a single JSON object on stdout, deliberately shaped to be
directly consumable by a future `parse-releases --resume` flag (not built
yet -- this is a planned follow-up, see the ADR this script's own
introduction should reference): resume_part_number and
resume_release_count_estimate tell you exactly where a real resume would
restart, and corrupt_parts tells you exactly what a resume implementation
would need to discard and redo.

Usage: python3 scripts/check_ingest_recovery.py <snapshot> \
         [--processed-dir local/processed/discogs] [--chunk-releases 5000]
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

DEFAULT_CHUNK_RELEASES = 5000  # matches packages/catalog's parquet.py default


def _is_valid_parquet(path: Path) -> tuple[bool, int | None]:
    """Returns (is_valid, row_count).

    Uses the duckdb CLI (already a documented project dependency,
    scripts/install-duckdb-cli.sh) rather than adding pyarrow to this
    script's own dependency footprint -- a truncated/corrupt parquet file
    makes DuckDB raise (non-zero exit), a valid one returns a real row
    count.
    """
    result = subprocess.run(
        ["duckdb", "-csv", "-noheader", "-c", f"SELECT count(*) FROM '{path}'"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, None
    try:
        return True, int(result.stdout.strip())
    except ValueError:
        return False, None


def check_recovery(snapshot: str, processed_dir: Path, chunk_releases: int) -> dict[str, object]:
    final_root = processed_dir / f"snapshot={snapshot}"
    if final_root.exists():
        return {"snapshot": snapshot, "status": "complete", "final_root": str(final_root)}

    staging_candidates = sorted(processed_dir.glob(f".snapshot={snapshot}.tmp-*"))
    if not staging_candidates:
        return {"snapshot": snapshot, "status": "not_started"}
    if len(staging_candidates) > 1:
        # Shouldn't happen in normal operation (write_release_dataset()
        # names each attempt with a fresh uuid4), but report rather than
        # silently guess which one matters if it ever does.
        return {
            "snapshot": snapshot,
            "status": "ambiguous_multiple_staging_dirs",
            "staging_roots": [str(p) for p in staging_candidates],
        }
    staging_root = staging_candidates[0]

    releases_dir = staging_root / "table=releases"
    if not releases_dir.is_dir():
        return {
            "snapshot": snapshot,
            "status": "staging_exists_but_empty",
            "staging_root": str(staging_root),
        }

    part_files = sorted(releases_dir.glob("part-*.parquet"))
    valid_parts: list[str] = []
    corrupt_parts: list[str] = []
    total_rows = 0
    for part_file in part_files:
        is_valid, row_count = _is_valid_parquet(part_file)
        if is_valid:
            valid_parts.append(part_file.name)
            total_rows += row_count or 0
        else:
            corrupt_parts.append(part_file.name)

    # A torn write can only ever be the highest-numbered part(s) -- earlier
    # parts are, by construction, already fully written and closed before
    # the next one starts (writes are sequential, never concurrent).
    # Flagging a corrupt part found BEFORE the end of the valid range means
    # something more unusual happened (e.g. disk corruption) than a simple
    # interrupted tail.
    latest_valid = max(valid_parts, default="")
    unexpected_gap = any(cp < latest_valid for cp in corrupt_parts)

    return {
        "snapshot": snapshot,
        "status": "interrupted_or_in_progress",
        "staging_root": str(staging_root),
        "chunk_releases_assumed": chunk_releases,
        "valid_parts": len(valid_parts),
        "corrupt_parts": corrupt_parts,
        "unexpected_gap": unexpected_gap,
        "releases_confirmed_valid": total_rows,
        "resume_part_number": len(valid_parts),
        "resume_release_count_estimate": len(valid_parts) * chunk_releases,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot")
    parser.add_argument("--processed-dir", default="local/processed/discogs")
    parser.add_argument("--chunk-releases", type=int, default=DEFAULT_CHUNK_RELEASES)
    args = parser.parse_args()

    result = check_recovery(args.snapshot, Path(args.processed_dir), args.chunk_releases)
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["status"] == "interrupted_or_in_progress":
        # Non-zero doesn't mean "error" -- it means "there's something to
        # look at," distinguishing that from "nothing interesting" so this
        # is scriptable (e.g. a pre-flight check before blindly rerunning).
        raise SystemExit(1)
    if result["status"] == "ambiguous_multiple_staging_dirs":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
