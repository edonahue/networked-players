#!/usr/bin/env python3
"""Refuse-to-start / self-stop gate for a Pi's on-demand Dask worker,
checking THIS HOST'S OWN per-host RQ queue(s) via the same Queue/registry
API scripts/cluster_benchmark_distributed.py's assert_queue_empty() already
uses -- not a new raw-Redis-key scheme. Real RQ queue names for this host
follow the "<prefix>-<hostname>" convention (run-rq-burst-worker.yml), and
RQ itself persistently tracks every queue name it has ever seen in the
"rq:queues" Redis set (confirmed live -- this set survives a queue being
fully drained, unlike the per-queue list key, which RQ deletes once empty).
Enumerating that set and filtering for this host's suffix catches ANY
queue prefix that targets this host, not just the two benchmark-specific
ones, so a future production queue name doesn't silently bypass the gate.

Two subcommands:
  check <jobs_broker_url> <hostname>
    Exit 0 if idle (safe to start a Dask worker), 1 if busy (a real job is
    queued or running), 2 if the jobs broker is unreachable.
  watch <jobs_broker_url> <hostname> <poll_interval_s> <unit_name...>
    Polls `check`'s own logic every poll_interval_s seconds. On the FIRST
    busy observation, runs `systemctl --user stop <unit_name...>` and
    exits. Broker-unreachable while watching is logged and treated as "keep
    polling," not "stop" -- see the fail-open note below, applied to the
    ongoing case.

Deliberately FAIL-OPEN when the jobs broker is unreachable, not
fail-closed: infra/swarm/docker-compose.jobs-broker.yml is explicitly NOT a
standing service (deploy-jobs-broker.sh starts/stops it around a benchmark
run). If it's down, no RQ job can possibly be running anywhere in the fleet
-- refusing to start a Dask worker in that state would gate against a
contention risk that provably cannot exist, purely because the unrelated,
often-intentionally-off broker happens to be down. Fail-closed here would
block ordinary Dask/Jupyter use in the common case (broker off because
nobody's benchmarking) for a risk that isn't real.
"""

from __future__ import annotations

import subprocess
import sys
import time

from redis import Redis
from redis.exceptions import RedisError
from rq import Queue

EXIT_IDLE = 0
EXIT_BUSY = 1
EXIT_BROKER_UNREACHABLE = 2


def _host_queue_names(redis_conn: Redis, hostname: str) -> list[str]:
    """Every queue name RQ has ever seen (rq:queues) that targets this host."""
    raw_names = redis_conn.smembers("rq:queues")
    names = []
    for raw in raw_names:
        name = raw.decode() if isinstance(raw, bytes) else raw
        name = name.removeprefix("rq:queue:")
        if name.endswith(f"-{hostname}"):
            names.append(name)
    return names


def is_busy(jobs_broker_url: str, hostname: str) -> bool:
    """True if a real job is queued or running on any of this host's queues.

    Raises redis.exceptions.RedisError (or a connection error) if the
    broker is unreachable -- callers decide how to handle that themselves,
    since "unreachable" means something different at start-time (fail
    open, allow the start) versus while watching (keep polling, don't
    treat a transient blip as "stop the worker").
    """
    redis_conn = Redis.from_url(jobs_broker_url, socket_connect_timeout=5)
    redis_conn.ping()
    for queue_name in _host_queue_names(redis_conn, hostname):
        queue = Queue(queue_name, connection=redis_conn)
        if len(queue) or queue.started_job_registry.count:
            return True
    return False


def cmd_check(jobs_broker_url: str, hostname: str) -> int:
    try:
        busy = is_busy(jobs_broker_url, hostname)
    except (RedisError, OSError) as exc:
        print(f"dask_gate_check: broker unreachable, failing open: {exc}", file=sys.stderr)
        return EXIT_BROKER_UNREACHABLE
    if busy:
        print(f"dask_gate_check: {hostname} has a real RQ job queued or running", file=sys.stderr)
        return EXIT_BUSY
    return EXIT_IDLE


def cmd_watch(
    jobs_broker_url: str, hostname: str, poll_interval_s: float, unit_names: list[str]
) -> int:
    print(
        f"dask_gate_check: watching {hostname}'s RQ queues every {poll_interval_s}s "
        f"(will stop {unit_names} on the first real job)",
        file=sys.stderr,
    )
    while True:
        try:
            busy = is_busy(jobs_broker_url, hostname)
        except (RedisError, OSError) as exc:
            # Fail open while watching too: a broker blip is not evidence a
            # real job appeared, so keep polling rather than stopping the
            # worker over a transient connection issue.
            print(
                f"dask_gate_check: broker unreachable during watch, retrying: {exc}",
                file=sys.stderr,
            )
            time.sleep(poll_interval_s)
            continue
        if busy:
            print(
                f"dask_gate_check: real RQ job detected on {hostname}, stopping {unit_names}",
                file=sys.stderr,
            )
            subprocess.run(["systemctl", "--user", "stop", *unit_names], check=False)
            return EXIT_IDLE
        time.sleep(poll_interval_s)


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        raise SystemExit(64)
    mode = sys.argv[1]
    if mode == "check":
        jobs_broker_url, hostname = sys.argv[2], sys.argv[3]
        raise SystemExit(cmd_check(jobs_broker_url, hostname))
    if mode == "watch":
        jobs_broker_url, hostname = sys.argv[2], sys.argv[3]
        poll_interval_s = float(sys.argv[4])
        unit_names = sys.argv[5:]
        raise SystemExit(cmd_watch(jobs_broker_url, hostname, poll_interval_s, unit_names))
    print(f"Usage: {sys.argv[0]} {{check|watch}} ...", file=sys.stderr)
    raise SystemExit(64)


if __name__ == "__main__":
    main()
