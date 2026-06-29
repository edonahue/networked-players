# Security policy

## Reporting

Do not open a public issue for a vulnerability that exposes credentials, personal data, a reachable service, or details that materially increase attack surface. Contact the repository owner privately through the contact information on [erichdonahue.com](https://erichdonahue.com/).

## Repository safety boundary

This public repository may describe architecture, hardware classes, algorithms, and reproducible examples. It must not contain:

- secrets, tokens, keys, cookies, or credentials;
- real hostnames, addresses, MAC addresses, serial numbers, or network reservations;
- tunnel identifiers, firewall mappings, or remote-access configuration;
- production inventory files or privileged commands tied to a reachable host;
- personal collection exports or user-associated catalog data;
- production database dumps, logs, backup destinations, or incident records.

If sensitive material is committed, treat it as exposed even after deletion. Rotate affected credentials first, then remove the material from current and historical Git data as appropriate.

## Future live services

No home-hosted endpoint should be exposed merely because its source is public. A future live API requires bounded requests, input validation, rate limiting, caching, observability, safe failure behavior, and an explicit exposure review.
