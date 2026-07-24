"""Stage (and later remove) an ad hoc, operator-supplied artifact onto every
targeted Pi worker before a check job that needs it can run.

Only `enqueue_cohort_check.py` needs this today: the other five
`enqueue_*_check.py` scripts check a fixed, known-in-advance artifact that a
`deploy-*-check-job.yml` playbook already copies to every worker at deploy
time. Cohort checks take a per-invocation `--artifact <path>` with no such
fixed location -- nothing ever put that file on a worker's filesystem before
this module existed (see infra/ansible/playbooks/stage-artifact.yml's header
comment for the confirmed bug this closes).

Staging is content-addressed (`cohort-input-<sha256>.json`) so the remote
filename never depends on the operator's local path, and verified
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
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ANSIBLE_DIR = REPO_ROOT / "infra" / "ansible"


def validate_local_artifact(path: Path) -> None:
    """Aborts loudly if `path` isn't a regular, valid-JSON file -- checked
    before anything is staged, not discovered later as an opaque Ansible
    failure."""
    if not path.exists():
        print(f"ABORT: no artifact at {path}.", file=sys.stderr)
        raise SystemExit(1)
    if not path.is_file():
        print(f"ABORT: {path} is not a regular file.", file=sys.stderr)
        raise SystemExit(1)
    try:
        json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        print(f"ABORT: {path} is not valid JSON: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def local_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def remote_filename_for(sha256: str) -> str:
    return f"cohort-input-{sha256}.json"


def stage_artifact(path: Path, hosts: list[str]) -> str:
    """Computes the artifact's sha256, copies it to every host's
    `rq_jobs_dir` under a content-addressed filename, and verifies each
    host's copy checksums the same before returning. Raises (via
    `subprocess.run(..., check=True)`) if any host's copy or checksum
    verification fails -- callers must not enqueue a check job before this
    returns successfully. Returns the remote filename (identical across
    every host)."""
    sha256 = local_sha256(path)
    remote_filename = remote_filename_for(sha256)
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
    return remote_filename


def unstage_artifact(remote_filename: str, hosts: list[str]) -> None:
    """Best-effort removal from every host -- logs a warning rather than
    raising, since cleanup must never override the check's own already-
    recorded result."""
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
