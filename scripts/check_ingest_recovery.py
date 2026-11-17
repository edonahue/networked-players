#!/usr/bin/env python3
"""Check for a partially-completed (interrupted or still-running) Discogs
ingest staging directory, and report exactly how much real, VALID output
survives -- and whether `parse-releases --resume` can safely continue it.

Since Atlas I4, packages/catalog's parse-releases writes every part file
atomically (temp name + fsync + rename, so a final part name is always
complete) and keeps a durable `progress.json` in the staging directory
(parts with size/sha256/rows, the release ordinal reached, the last
release_id and a running digest of all persisted release ids). When that
record is present this script verifies every recorded part's size and
sha256 against it and reports `resume_safe` plus a recommendation:

  resume_safe true  -> re-run the same parse-releases command with --resume
                       (identical parameters; unrecorded/temp files are
                       deleted by the resume itself, with a logged line).
  resume_safe false -> a recorded part is missing/altered or the record is
                       corrupt; resume would refuse. Delete the staging
                       directory and re-run without --resume.

Resume is re-read-and-skip: it saves the transform/write cost of the
completed portion, not the decompress/parse cost of skipping it. This
script cannot check the INPUT identity (that needs the dump); --resume
itself verifies it and refuses a different input.

A staging directory with NO progress.json (written by a pre-I4 build) is
reported with the legacy DuckDB-based part validation and is not resumable.

Read-only: never modifies or deletes anything. Safe to run against a
STILL-RUNNING ingest too -- useful for exactly that: distinguishing "done
so far, confirmed valid" from "currently being written, don't trust yet."

Output is a single JSON object on stdout. Exit codes: 0 nothing to look at,
1 interrupted_or_in_progress, 2 ambiguous (multiple staging dirs).

Usage: python3 scripts/check_ingest_recovery.py <snapshot> \
         [--processed-dir local/processed/discogs] [--chunk-releases 5000]
"""

from __future__ import annotations

import argparse
import hashlib
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_progress_record(snapshot: str, staging_root: Path) -> dict[str, object] | None:
    """Verify a staging dir against its progress.json; None if there is no record."""
    record_path = staging_root / "progress.json"
    if not record_path.is_file():
        return None
    result: dict[str, object] = {
        "snapshot": snapshot,
        "status": "interrupted_or_in_progress",
        "staging_root": str(staging_root),
        "progress_record": True,
    }
    try:
        record = json.loads(record_path.read_text())
        files = list(record["files"])
        state = record["state"]
        persisted = int(record["releases_persisted"])
        parts = int(record["parts_completed"])
    except (OSError, ValueError, KeyError, TypeError):
        result.update(
            resume_safe=False,
            recommendation="progress.json is corrupt: delete the staging dir, "
            "re-run without --resume",
        )
        return result
    problems: list[str] = []
    recorded = set()
    for item in files:
        recorded.add(item["path"])
        path = staging_root / item["path"]
        if not path.is_file():
            problems.append(f"missing: {item['path']}")
        elif path.stat().st_size != item["size_bytes"] or _sha256(path) != item["sha256"]:
            problems.append(f"altered: {item['path']}")
    unrecorded = sorted(
        p.relative_to(staging_root).as_posix()
        for p in staging_root.rglob("*")
        if p.is_file()
        and p.relative_to(staging_root).as_posix() not in recorded
        and p.name not in ("progress.json", ".progress.json.tmp")
    )
    result.update(
        state=state,
        parts_completed=parts,
        releases_persisted=persisted,
        last_release_id=record["last_release_id"],
        recorded_parts_ok=not problems,
        recorded_part_problems=problems,
        unrecorded_files_resume_will_delete=unrecorded,
        resume_safe=not problems,
        recommendation=(
            "re-run the same parse-releases command with --resume (identical parameters)"
            if not problems
            else "a recorded part is missing/altered: delete the staging dir and re-run "
            "without --resume"
        ),
    )
    return result


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

    with_record = _check_progress_record(snapshot, staging_root)
    if with_record is not None:
        return with_record

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
