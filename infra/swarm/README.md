# Docker Swarm

Docker Swarm is the current orchestration direction because the first cluster needs a small control plane and a clear distinction between managers, workers, services, and tasks.

The first proof should deploy one harmless multi-architecture service, verify placement on each worker, remove and rejoin a worker, and document single-manager recovery. Stateful services remain pinned to the coordination host; Swarm does not make local storage distributed.

No production stack or join token belongs in this repository.

## Coordination-host services (dev loop)

`docker-compose.coordination.yml` runs Postgres and Redis on the coordination host
for local development. It is intentionally **not** a Swarm stack — stateful services
stay pinned here. Credentials come from a git-ignored `.env`:

```bash
cd infra/swarm
cp .env.example .env      # then edit; never commit .env
docker compose -f docker-compose.coordination.yml up -d
docker compose -f docker-compose.coordination.yml ps
```

Or run `./deploy-coordination.sh`, which generates `.env` automatically with a
random password (idempotent, safe to re-run).

Both services bind to loopback only.

## Portainer (Swarm visibility)

`docker-compose.portainer.yml` runs Portainer CE, a web UI for inspecting Swarm nodes,
services, and containers. Like the coordination-host services above, it is intentionally
**not** a Swarm stack — Swarm's `--publish` always binds `0.0.0.0`, which is unacceptable
for an unauthenticated-until-first-login admin UI with full `docker.sock` access. See
`docs/decisions/0008-portainer-swarm-visibility.md` and
`docs/decisions/0009-portainer-tailscale-access.md` for the reasoning.

```bash
./scripts/install-tailscale.sh    # one-time; joins this host to your tailnet
cd infra/swarm
./deploy-portainer.sh             # auto-binds to the Tailscale IP if connected,
                                   # else falls back to loopback-only
```

The script prints exactly which URL to use. Never bind this to a LAN interface or
`0.0.0.0` directly — only loopback (SSH tunnel) or Tailscale (tailnet-only).

## Swarm init / join runbook

Initialize the manager on the coordination host and join the workers. Real tokens and
addresses stay out of Git — capture them locally only.

```bash
# On the coordination host (manager):
docker swarm init --advertise-addr <coordinator-ip>
docker swarm join-token worker        # prints the join command + token (keep local)

# On each Raspberry Pi worker:
docker swarm join --token <worker-token> <coordinator-ip>:2377

# Back on the manager — verify, then deploy a harmless multi-arch smoke service:
docker node ls
docker service create --name hello --mode global --replicas 1 traefik/whoami
docker service ps hello                # confirm placement on each worker
docker service rm hello

# Recovery drill: drain/remove a worker, then rejoin it with the token above.
docker node update --availability drain <worker>
```

Pin stateful services to the manager with a placement constraint
(`--constraint 'node.role==manager'`); never schedule Postgres/Redis onto a Pi worker.
