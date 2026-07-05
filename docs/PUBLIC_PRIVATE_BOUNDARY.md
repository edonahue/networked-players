# Public and private boundaries

Networked Players follows a public-by-default development philosophy without publishing the identity, access path, or personal data of the running environment.

## Public

- source code and reusable configuration;
- logical architecture and actual hardware models;
- synthetic inventories and fixtures;
- algorithms, schemas, tests, and benchmark *methodology* (the probes, playbooks, and scripts that produce a measurement);
- generic recovery principles and failure behavior;
- derived public challenges with evidence and provenance;
- documented tradeoffs and architecture decisions.

## Public, but not this instance's numbers

Benchmark *code* is public; a benchmark *result* (real throughput, elapsed
time, memory, or headroom measured on this specific hardware) is treated as
private and local (see [ADR 0018](decisions/0018-benchmark-results-local-only.md)).
Publish the method, not the receipts — a hardware class name (e.g. "Raspberry
Pi 3B") is fine in public docs; "this Pi measured 4,630 releases/sec on
2026-07-02" is not.

## Private and local

- credentials, tokens, keys, cookies, and vault contents;
- real addresses, hostnames, MAC addresses, serial numbers, and reservations;
- tunnel identifiers, firewall mappings, remote-access details, and join tokens;
- production inventories and machine-specific variables;
- private collection membership, exports, and account-linked responses;
- database dumps, production snapshots that are not cleared for publication, and raw logs;
- backup destinations, restore credentials, and sensitive incident notes;
- raw saved third-party web pages/HTML and any operator notes describing them (see
  [ADR 0028](decisions/0028-curated-cohort-source-ingestion.md)) — the article's own
  editorial selection and prose are the source author's work, not this project's to
  redistribute.

## Practical pattern

Public files use placeholders such as `worker-01.example.internal`. A local ignored directory or external secret store supplies real values. Public code should fail clearly when required local configuration is absent; it should never include a convenient insecure default.

Measured benchmark output (cluster or single-node) is written under
`local/benchmarks/`, never committed and never transcribed into a public doc
— see `infra/ansible/README.md`'s Benchmarking section for how to reproduce a
measurement yourself.

## Before publishing an artifact

1. Confirm source rights and required attribution.
2. Confirm no personal collection membership can be reconstructed.
3. Inspect files and metadata for addresses, usernames, paths, tokens, and account identifiers.
4. Verify that example configuration cannot reach the real environment.
5. Record provenance, schema, and snapshot versions.

A curated cohort source's extracted-candidates JSON (`data/contracts/album-cohort-extracted-v1.md`)
is a reviewed local intermediate, not yet subject to this checklist — nothing in that
pipeline stage publishes anything.
