# ADR 0006: Stream release gzip into bounded Parquet partitions

- **Status:** Accepted
- **Date:** 2026-06-29

## Context

The release dump is much larger and structurally more complex than the artist, label, and master dumps. The coordination host has SSD storage but modest compute, the Pi 3B workers have 1 GB RAM, and the optional x600 is powerful but should not become an uptime dependency. Expanding XML to disk duplicates tens of gigabytes of transient data without improving the final product.

## Decision

Parse release XML directly from gzip with `lxml.iterparse`, clear completed elements, normalize in bounded release batches, and write immutable Zstandard Parquet parts. Implement release, track, and credit tables first. Preserve source role text and non-linked evidence. Run full parsing on the optional workstation when available or on the coordination host with conservative limits; do not send the full raw dump to Pi workers.

## Consequences

Memory remains bounded and no expanded XML copy is retained. The initial parser is sequential and therefore may not maximize workstation throughput. Downstream Parquet partitions become safe units for parallel transforms and distributed worker jobs. Full artist/master/label parsers remain future work.

## Validation

Synthetic tests must cover release and track artists, release and track extra artists, PAN/ANV separation, missing or zero artist IDs, bounded early termination, Parquet round-trip, and DuckDB invariants.

## Revisit trigger

Revisit the parser architecture after a measured full conversion on both the x600 and coordination host, or if a mature external parser demonstrably meets the project's evidence, schema, reproducibility, and ARM64 requirements with less maintenance.
