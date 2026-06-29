# ADR 0004: Use a canonical game-hosting domain

- **Status:** Accepted
- **Date:** 2026-06-29

## Context

Networked Players has a public repository and a separate study companion, but the eventual game needs a clear production home that is not tied to either GitHub or the lab route.

## Decision

Use `networked-players.com`, which is registered by the project owner, as the eventual production host for the public game. Keep GitHub as the source and project history, and keep the Music-Credit Graph Study Lab as the learning companion.

No placeholder deployment is required. DNS and hosting will be configured when there is a useful public game artifact to serve, but the intended end state is a real player-facing experience at the domain rather than a permanent redirect to GitHub or the lab.

## Consequences

The project can design stable URLs, deployment workflows, canonical metadata, and branding around one owned game host without pretending the product is already deployed. The hyphenated domain should be written consistently in documentation and public materials.

## Validation

Before launch, verify domain control, HTTPS, canonical metadata, static asset delivery, redirects, and graceful hosting independently of the home lab.

## Revisit trigger

Reconsider only if the product name changes, a materially better canonical domain is acquired, or a legal review requires different branding.
