# ADR 0003: Begin as one monorepo

- **Status:** Accepted
- **Date:** 2026-06-28

## Context

The product, schemas, graph logic, worker jobs, application, and infrastructure will evolve together during the first vertical slice. Splitting them now would add coordination and versioning overhead before stable boundaries exist.

## Decision

Keep the planned web app, API, reusable packages, public data contracts, tests, and generic infrastructure in one repository. Private runtime identity and personal data remain local rather than moving to a second Git repository by default.

## Consequences

Cross-cutting changes and documentation stay easy to review. The repository needs clear directories and dependency discipline to avoid becoming an undifferentiated collection.

## Validation

The first vertical slice should be understandable from one commit history without requiring synchronized changes across repositories.

## Revisit trigger

Split a component when it has a distinct release cadence, security boundary, ownership model, or independent reuse case that the monorepo makes harder.
