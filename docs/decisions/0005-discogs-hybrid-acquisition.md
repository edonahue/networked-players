# ADR 0005: Use a hybrid Discogs acquisition strategy

- **Status:** Accepted
- **Date:** 2026-06-29

## Context

Networked Players needs a private collection-derived starting point, durable bulk catalog facts, and a way to handle occasional gaps or recently changed records. Building the graph entirely from account-linked API responses would mix private membership with bulk acquisition, inherit request-rate and freshness constraints, and make reproducible rebuilds harder.

## Decision

Use three deliberately separate inputs:

1. A private local collection export supplies release IDs only as the initial seed.
2. Monthly Discogs XML dumps are the canonical bulk source for rebuildable catalog facts.
3. Centrally controlled API requests may fill explicit gaps, validate selected records, or inspect changes newer than the chosen dump.

Keep API credentials, response cache, and rate-limit state on the coordination host. Do not distribute credentials to Pi workers or client applications. Preserve source/access method on every normalized record and derived artifact.

## Consequences

The initial pipeline can be tested publicly with synthetic data while collection membership remains private. Monthly artifacts are reproducible and can be rolled back. API integration is smaller and easier to audit, but the project must reconcile dump and API provenance and review current terms before publication.

## Validation

The first vertical slice must produce an evidence path from a synthetic or private seed using a versioned dump-derived dataset without an API token.

## Revisit trigger

Revisit if Discogs changes dump availability or rights, if required catalog fields are absent from dumps, or if measured monthly rebuild cost exceeds the planned hardware/storage envelope.
