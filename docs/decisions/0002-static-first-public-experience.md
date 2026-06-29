# ADR 0002: Make the public experience static first

- **Status:** Accepted
- **Date:** 2026-06-28

## Context

A future API may run from a home lab with limited availability, changing addresses, maintenance windows, and constrained hardware. The game should remain useful without making the home environment a public reliability dependency.

## Decision

Publish static challenges, evidence paths, and findings before exposing bounded live search. Any later API is additive and the interface must degrade gracefully when it is unavailable.

## Consequences

The first release cannot explore arbitrary artist pairs, but it is easier to cache, test, share, host, and secure. Publication requires versioned challenge artifacts and clear distinction between static and live capabilities.

## Validation

Disable all home-hosted services and confirm that the public challenge, evidence display, and explanatory content remain usable.

## Revisit trigger

Reconsider the hosting split if live exploration becomes the dominant validated use case and a low-cost service materially improves safety or reliability.
