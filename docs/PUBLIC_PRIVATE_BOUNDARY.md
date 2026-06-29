# Public and private boundaries

Networked Players follows a public-by-default development philosophy without publishing the identity, access path, or personal data of the running environment.

## Public

- source code and reusable configuration;
- logical architecture and actual hardware models;
- synthetic inventories and fixtures;
- algorithms, schemas, tests, benchmarks, and aggregate findings;
- generic recovery principles and failure behavior;
- derived public challenges with evidence and provenance;
- documented tradeoffs and architecture decisions.

## Private and local

- credentials, tokens, keys, cookies, and vault contents;
- real addresses, hostnames, MAC addresses, serial numbers, and reservations;
- tunnel identifiers, firewall mappings, remote-access details, and join tokens;
- production inventories and machine-specific variables;
- private collection membership, exports, and account-linked responses;
- database dumps, production snapshots that are not cleared for publication, and raw logs;
- backup destinations, restore credentials, and sensitive incident notes.

## Practical pattern

Public files use placeholders such as `worker-01.example.internal`. A local ignored directory or external secret store supplies real values. Public code should fail clearly when required local configuration is absent; it should never include a convenient insecure default.

## Before publishing an artifact

1. Confirm source rights and required attribution.
2. Confirm no personal collection membership can be reconstructed.
3. Inspect files and metadata for addresses, usernames, paths, tokens, and account identifiers.
4. Verify that example configuration cannot reach the real environment.
5. Record provenance, schema, and snapshot versions.
