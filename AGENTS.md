# Agent guidance

This repository is intentionally scaffold-first. Automated contributors must preserve the distinction between a planned component and a working component.

## Required behavior

- Read `README.md`, `docs/PRODUCT.md`, `docs/ARCHITECTURE.md`, and `docs/PUBLIC_PRIVATE_BOUNDARY.md` before proposing architecture changes.
- Do not claim that an application, service, deployment, benchmark, or dataset exists until the repository contains evidence for it.
- Keep examples synthetic and reproducible.
- Never add real secrets, addresses, hostnames, collection exports, runtime inventories, backup locations, or deployment identities.
- Prefer small vertical slices over broad placeholder frameworks.
- Add an architecture decision record when changing a settled direction.
- Preserve static-first failure behavior: a home-hosted service must not become a requirement for the core public experience.
- Treat the Raspberry Pi 3B workers as constrained 1 GB ARM64 nodes; bound memory, payload size, concurrency, and job duration.
- Keep personal collection membership local even when the import mechanism is public.

## Working conventions

- Put user-facing applications in `apps/`.
- Put reusable domain logic in `packages/`.
- Put public schemas and synthetic fixtures in `data/`.
- Put infrastructure examples in `infra/`; real inventories remain local and ignored.
- Put cross-cutting decisions and design documentation in `docs/`.
- Do not introduce a monorepo tool, framework, database, queue, or graph engine until the first implementation need is clear.

## Validation expectations

When implementation begins, each change should identify the smallest relevant checks. Prefer deterministic fixtures and explicit resource limits. Benchmarks must record hardware, dataset version, method, and result rather than reporting unsupported impressions.
