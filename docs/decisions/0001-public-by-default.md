# ADR 0001: Develop in public by default

- **Status:** Accepted
- **Date:** 2026-06-28

## Context

The project is intended to be a learning artifact, portfolio project, and reusable example. Hiding all infrastructure would reduce that value, while exposing deployment identity or personal collection data would create unnecessary risk.

## Decision

Keep the repository public and publish product thinking, source code, hardware models, generic infrastructure, schemas, tests, benchmarks, and safe examples. Keep secrets, deployment identity, personal collection membership, real inventories, backups, and sensitive runtime records outside Git.

## Consequences

The project gains transparency and educational value. Every contributor must maintain a deliberate boundary, and accidental commits must be treated as disclosures rather than solved by ordinary deletion.

## Validation

Review committed files and history for restricted categories before releases and infrastructure changes.

## Revisit trigger

Reconsider repository separation if operational material cannot remain safely generic or if private data development repeatedly approaches the public boundary.
