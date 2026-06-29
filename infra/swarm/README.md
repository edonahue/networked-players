# Docker Swarm

Docker Swarm is the current orchestration direction because the first cluster needs a small control plane and a clear distinction between managers, workers, services, and tasks.

The first proof should deploy one harmless multi-architecture service, verify placement on each worker, remove and rejoin a worker, and document single-manager recovery. Stateful services remain pinned to the coordination host; Swarm does not make local storage distributed.

No production stack or join token belongs in this repository.
