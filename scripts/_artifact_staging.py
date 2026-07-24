"""Stage (and later remove) an ad hoc, operator-supplied artifact onto every
targeted Pi worker before a check job that needs it can run.

Only `enqueue_cohort_check.py` needs this today: the other five
`enqueue_*_check.py` scripts check a fixed, known-in-advance artifact that a
`deploy-*-check-job.yml` playbook already copies to every worker at deploy
time. Cohort checks take a per-invocation `--artifact <path>` with no such
fixed location -- nothing ever put that file on a worker's filesystem before
this module existed (see infra/ansible/playbooks/stage-artifact.yml's header
comment for the confirmed bug this closes).

Staging is content-addressed **and** per-invocation
(`cohort-input-<sha256>-<run_id>.json`): the sha256 keeps the staged file
identifiable, the run_id (a fresh `uuid.uuid4().hex` per call, filename-safe
by construction) keeps two concurrent stagings of byte-identical bytes from
colliding on the same remote name -- otherwise one invocation's cleanup
could remove another's still-in-flight input. Verified
(`infra/ansible/playbooks/stage-artifact.yml` checksums the copy on every
target before returning success -- any one worker's mismatch aborts the
whole run). Cleanup (`unstage_artifact`) is best-effort by design: it must
never mask whatever the check itself already reported.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ANSIBLE_DIR = REPO_ROOT / "infra" / "ansible"

# Pi-safe upper bound for a staged cohort artifact. This validator is for
# bounded, human-reviewed cohorts (playable-cohort-v1.json is the reviewed,
# promoted SUBSET of connectivity.json -- structurally smaller by
# construction), not dataset-scale input. The only real committed public
# fixture (apps/web/public/data/cohorts/synthetic-example.playable-v1.json)
# is 1,853 bytes; 8 MiB is ~4,500x that. At a conservative 3-5x JSON->Python
# parse-expansion factor, 8 MiB raw JSON tops out around 30-40 MiB parsed --
# comfortably under the 512 MiB burst-worker MemoryMax
# (infra/ansible/playbooks/run-rq-burst-worker.yml, ADR 0021's Pi-sized
# default) on a Pi 3B treated as a constrained 1 GiB ARM64 node (AGENTS.md).
# Each targeted worker gets its own independent copy under its own 512 MiB
# cap, so worker count doesn't change this math. No override flag: nothing
# in this repository's real fixtures or documented cohort sizes justifies
# one yet.
MAX_COHORT_ARTIFACT_BYTES = 8 * 1024 * 1024


def validate_local_artifact(path: Path) -> None:
    """Aborts loudly if `path` isn't a regular, Pi-safely-sized, valid-JSON
    file -- checked before anything is staged, not discovered later as an
    opaque Ansible failure or a burst-worker OOM. Size is checked via
    `stat()` (before any read), so an oversized file is never even fully
    read locally, let alone copied to the fleet."""
    if not path.exists():
        print(f"ABORT: no artifact at {path}.", file=sys.stderr)
        raise SystemExit(1)
    if not path.is_file():
        print(f"ABORT: {path} is not a regular file.", file=sys.stderr)
        raise SystemExit(1)
    size = path.stat().st_size
    if size > MAX_COHORT_ARTIFACT_BYTES:
        print(
            f"ABORT: {path} is {size} bytes, over the {MAX_COHORT_ARTIFACT_BYTES}-byte "
            "Pi-safe limit for a cohort artifact. This validator is for bounded, "
            "human-reviewed cohorts, not dataset-scale input.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    try:
        json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        print(f"ABORT: {path} is not valid JSON: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def local_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def new_run_id() -> str:
    """A fresh, filename-safe, per-invocation token -- no hostname, path,
    timestamp, or inventory identifier, just enough entropy that two
    concurrent invocations staging identical bytes never share a remote
    filename."""
    return uuid.uuid4().hex


def remote_filename_for(sha256: str, run_id: str) -> str:
    return f"cohort-input-{sha256}-{run_id}.json"


def stage_artifact(path: Path, hosts: list[str], *, remote_filename: str, sha256: str) -> None:
    """Copies `path` to every host's `rq_jobs_dir` under `remote_filename`
    and verifies each host's copy checksums to `sha256` before returning.
    Raises (via `subprocess.run(..., check=True)`) if any host's copy or
    checksum verification fails -- callers must not enqueue a check job
    before this returns successfully. `remote_filename`/`sha256` are
    supplied by the caller (not computed here) so they're known -- and a
    cleanup can be attempted against them -- even if this call itself
    raises partway through."""
    cmd = [
        str(ANSIBLE_DIR / "run-stage-artifact-local.sh"),
        "--limit",
        ",".join(hosts),
        "-e",
        "stage_action=stage",
        "-e",
        f"local_artifact_path={path.resolve()}",
        "-e",
        f"remote_filename={remote_filename}",
        "-e",
        f"expected_sha256={sha256}",
    ]
    subprocess.run(cmd, check=True)


def unstage_artifact(remote_filename: str, hosts: list[str]) -> None:
    """Best-effort removal from every host -- logs a warning rather than
    raising, since cleanup must never override the check's own already-
    recorded result. Safe to call even if staging never reached any worker
    (Ansible's `file: state: absent` on an absent path is a harmless
    no-op)."""
    cmd = [
        str(ANSIBLE_DIR / "run-stage-artifact-local.sh"),
        "--limit",
        ",".join(hosts),
        "-e",
        "stage_action=unstage",
        "-e",
        f"remote_filename={remote_filename}",
    ]
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        print(
            f"WARNING: failed to remove staged artifact {remote_filename!r} from "
            f"{hosts}: {exc}. Remove it manually if this persists.",
            file=sys.stderr,
        )
