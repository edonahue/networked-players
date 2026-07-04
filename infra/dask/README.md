# Jupyter + Dask: interactive cluster compute

An interactive way to experiment with distributed compute against this
project's stack (pandas/PyArrow/DuckDB), decided after comparing Dask against
Ray and Spark — see
[ADR 0020](../../docs/decisions/0020-dask-jupyter-interactive-cluster-compute.md).

This is a **standing** Swarm stack for the Dask scheduler/worker (coordination
host only), plus a plain Jupyter container — LAN-reachable by default (see
"Security posture" below; opt back out to loopback-only any time). Pi 3B
workers are explicitly excluded for now — see the ADR, and the "Pi 3B
workers" section below.

## Layout

```text
Dockerfile                          shared image for scheduler/worker/Jupyter
requirements.txt                    pinned jupyterlab, dask[distributed], pandas, pyarrow, duckdb
docker-stack.dask.yml               Swarm stack: dask-scheduler + dask-worker (coordination host only)
docker-compose.jupyter.yml          plain compose: Jupyter, loopback-bound, token-gated
docker-compose.dask-worker-remote.yml   for a future non-Swarm build node (ADR 0015); unused right now (ADR 0022)
dask.env.example                    copy to local/dask.env and edit
deploy-dask.sh                      build image + start Jupyter + deploy the stack (or --down)
notebooks/00-dask-cluster-smoke-test.ipynb       synthetic, proves real distributed execution
notebooks/01-duckdb-and-dask-parquet.ipynb       synthetic, DuckDB + Dask side by side
notebooks/02-explore-real-discogs-catalog.ipynb  REAL ingested data, needs SNAPSHOT + a completed ingest
```

## Startup

```bash
cp dask.env.example ../../local/dask.env   # then edit: JUPYTER_TOKEN, DISCOGS_PROCESSED_DIR
./deploy-dask.sh
```

This builds `networked-players-dask:local`, deploys the Dask scheduler/worker
Swarm stack, starts Jupyter, and joins Jupyter onto the stack's overlay
network so `tcp://dask-scheduler:8786` resolves from inside a notebook.
**Swarm stacks ignore any `build:` key** — if you ever add a second node to
`docker-stack.dask.yml`'s placement targets, you must build the image on that
node too; there's no shared registry in this repo.

- Jupyter: auto-detects this host's LAN IP and binds there by default
  (`deploy-dask.sh` prints the exact URL, e.g. `http://<lan-ip>:8888`, also
  reachable via mDNS as `http://coordination-host.local:8888` if avahi is running on
  your network — that's client-side DNS, unrelated to the bind). Set
  `JUPYTER_BIND_IP=127.0.0.1` in `local/dask.env` to opt back out to
  loopback-only + SSH tunnel (`ssh -L 8888:localhost:8888 <coordination-host>`).
  Either way, enter your `JUPYTER_TOKEN` from `local/dask.env`.
- Dask dashboard: `ssh -L 8787:localhost:8787 <coordination-host>`, then open
  `http://localhost:8787` — or reach it directly, since `docker-stack.dask.yml`
  already publishes 8787 via Swarm's `mode: host` on all of this node's
  interfaces (see "Security posture" below).
- `docker service ls | grep dask_` to confirm the scheduler/worker services
  are running.

## Shutdown

```bash
./deploy-dask.sh --down
```

## Resource limits

`docker-stack.dask.yml`'s memory limits (256M scheduler, 512M × 2 workers)
are **starting values, not measured facts** — confirm with `docker stats`
against the coordination host's real headroom and adjust. The host is
documented as x86_64/4 CPUs in `docs/HARDWARE.md`; real RAM/CPU numbers for
this specific host are local-only per
[ADR 0018](../../docs/decisions/0018-benchmark-results-local-only.md).

## Security posture

- **Jupyter** is a sensitive surface (arbitrary code execution). It never
  gets an insecure default token — `JUPYTER_TOKEN` is always required,
  regardless of bind address. By default it now binds to this host's
  auto-detected LAN address (an explicit operator choice, see
  [ADR 0020](../../docs/decisions/0020-dask-jupyter-interactive-cluster-compute.md)'s
  amendment — originally loopback-only, matching the Postgres/Redis/Portainer
  UI pattern elsewhere in this repo). Set `JUPYTER_BIND_IP=127.0.0.1` in
  `local/dask.env` to go back to loopback-only + SSH tunnel. Note the token
  now travels over plain HTTP on the LAN by default, not inside SSH's
  encrypted tunnel — accepted for a private home LAN, not a substitute for a
  real secret if this host is ever reachable beyond it.
- **Dask's scheduler-worker protocol has no built-in authentication.**
  `docker-stack.dask.yml` publishes 8786/8787 via Swarm's `mode: host`,
  which binds all of this node's interfaces (not just the LAN one) — making
  that surface trusted-LAN-only, not defended against a malicious LAN peer.
  Acceptable for a home lab; revisit with TLS certificates if this ever
  needs a stronger boundary (see the ADR's revisit trigger).

## Real data: `DISCOGS_PROCESSED_DIR`

`notebooks/02-explore-real-discogs-catalog.ipynb` reads a real, completed
`scripts/run-ingest.sh` output — not a fixture. Set `DISCOGS_PROCESSED_DIR`
in `local/dask.env` to the **absolute** host path of your processed dataset
(default convention: `<repo-root>/local/processed/discogs`), which gets
mounted read-only at `/data/discogs` into both Jupyter and the local
`dask-worker` containers. Optionally set `SNAPSHOT` too, matching
`scripts/profile-discogs-dataset.sh`'s convention, so the notebook doesn't
need editing. If you haven't run a real ingest yet, notebooks 00 and 01
(synthetic data) still work fine — 02 fails with a clear message instead of
silently substituting fake data.

## On-demand worker participation (`pi_workers` and `x86_workers`)

Both the Pi 3B workers and any `x86_workers` Swarm member (ADR 0022/0023)
can join the standing scheduler above as a manual, on-demand worker via
`infra/ansible/playbooks/run-dask-worker-burst.yml` — a single, bounded,
non-containerized `dask worker` process (a dedicated venv, separate from
`equip-workers.yml`'s/`equip-x86-workers.yml`'s lean RQ venv), never a
standing service, never the whole `workers` group at once:

```bash
./infra/ansible/run-dask-worker-burst-local.sh --limit worker-01.example.internal \
  -e dask_worker_action=start -e dask_scheduler_address=<coordination-host-lan-ip>

# ... use it, then stop it manually:
./infra/ansible/run-dask-worker-burst-local.sh --limit worker-01.example.internal \
  -e dask_worker_action=stop
```

Two gates before starting: `infra/ansible/playbooks/health.yml`'s memory
report (`local/benchmarks/pi-memory-headroom.md`, local-only per ADR 0018)
should show real headroom for that host — checked manually, per ADR 0020;
and the target host must have no active/queued RQ job right now — checked
**automatically** by the playbook itself (`dask_gate_check.py`, ADR 0021),
which also runs an ongoing watchdog that stops the Dask worker the moment a
real RQ job appears later, so this second gate isn't just a point-in-time
check.

Resource limits (`--nthreads`, `--memory-limit`, the `systemd-run` cgroup
ceiling) are group_vars-parameterized per hardware class, not one-size-fits-
all (ADR 0023) — a Pi gets the original 2025-era conservative values, an
`x86_workers` member gets values scaled to its real, much higher measured
headroom. See `infra/ansible/inventories/example/group_vars/x86_workers.yml`
for the exact vars.

**Real-data reads from a remote worker** need the catalog-data HTTP server
([ADR 0024](../../docs/decisions/0024-http-readonly-catalog-data-access.md)):
a remote worker has no bind mount, so a scheduler task that opens
`/data/discogs/...` on it fails (a real, reproduced `FileNotFoundError`).
Start `infra/swarm/deploy-catalog-data.sh` on the coordination host, pass
`-e catalog_data_url=http://<coordination-host-lan-ip>:8791` when starting
the burst worker, and read via manifest-derived URLs
(`networked_players_catalog.discogs.dataset_locator.dataset_file_urls`)
instead of local paths. Access policy: x86 workers may read full-dataset
partitions; Pi 3Bs only the one-hop dataset or bounded partitions.

## Non-Swarm build-node worker (if one exists)

`docker-compose.dask-worker-remote.yml` remains for a hypothetical *future*
build node that is explicitly **not** a Swarm member (the `optional_build_nodes`
role, ADR 0015) — it has no populated hardware right now (the box that role
used to describe is now the `x86_workers` Swarm member covered above, ADR
0022). If such a host exists again later, run directly on it:

```bash
cd infra/dask
docker build -t networked-players-dask:local .
DASK_SCHEDULER_ADDRESS=<coordination-host-lan-ip> \
  DISCOGS_PROCESSED_DIR=<real-path-on-this-host-or-omit> \
  docker compose -f docker-compose.dask-worker-remote.yml up -d
```

**Former known limitation, now resolved by ADR 0024:** a remote worker has
no local copy of the coordination host's `local/processed/discogs`, so a
distributed read that scheduled a *filesystem* partition read onto it used
to fail. The catalog-data HTTP server (`infra/swarm/deploy-catalog-data.sh`)
plus manifest-derived URLs (`dataset_locator.py`) close that gap — see the
"Real-data reads from a remote worker" note above.
