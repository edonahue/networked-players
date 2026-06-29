# ADR 0004: Reserve a canonical product domain

- **Status:** Accepted
- **Date:** 2026-06-29

## Context

Networked Players has a public repository and a separate study companion, but the eventual game needs a clear product identity that is not tied to either GitHub or the lab route.

## Decision

Use `networked-players.com`, which is registered by the project owner, as the intended canonical home for the future public website and game. Keep GitHub as the source and project history, and keep the Music-Credit Graph Study Lab as the learning companion.

No placeholder deployment is required. DNS, hosting, redirects, and launch behavior will be chosen when there is a useful public artifact to serve.

## Consequences

The project can design stable URLs and branding around one owned domain without pretending the product is already deployed. The hyphenated domain should be written consistently in documentation and public materials.

## Validation

Before launch, verify domain control, HTTPS, canonical metadata, redirects, and graceful static hosting independently of the home lab.

## Revisit trigger

Reconsider only if the product name changes, a materially better canonical domain is acquired, or a legal review requires different branding.
