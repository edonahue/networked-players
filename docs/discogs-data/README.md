# Discogs data reference

A reference for what Discogs' data actually looks like — the raw monthly dump XML,
the REST API v2 JSON, and how this project's own normalized schema derives from
them. This is distinct from two things it might be confused with:

- **`docs/DISCOGS_INGESTION.md`** documents *this project's own pipeline design*
  (architecture, source roles, hardware execution profiles). It's about how we
  ingest; this directory is about what the source data actually contains.
- **`data/contracts/`** documents *this project's own output schemas* (the
  normalized Parquet tables, the private seed format). This directory documents the
  *inputs* those contracts are derived from.

## Files

- [`raw-dump-schema.md`](raw-dump-schema.md) — the monthly XML dump format for all
  four kinds (releases, artists, labels, masters), grounded in a real downloaded and
  inspected snapshot, not just the published spec.
- [`api-schema.md`](api-schema.md) — the REST API v2 JSON shape (used by
  [ADR 0012](../decisions/0012-real-discogs-api-demo-challenge.md)'s live demo),
  cross-referenced against the dump XML field-by-field.
- [`normalized-mapping.md`](normalized-mapping.md) — how raw source fields (from
  either the dump or the API) map to this project's own normalized schema
  (`data/contracts/discogs-release-v2.md`), and why specific mapping decisions were
  made (PAN/ANV, credit scope, playable identity).
- [`one-hop-hub-artists.md`](one-hop-hub-artists.md) — a real-data investigation into
  which credited identities dominate one-hop expansion (Milestone 5), grounded in a
  purely public, seed-independent query against the full credits table; see
  [ADR 0026](../decisions/0026-exclude-placeholder-artists-from-one-hop-frontier.md)
  for the resulting decision.

Real benchmark numbers (dump sizes, record counts, parse throughput, memory) live in
[`docs/DATA_SIZING.md`](../DATA_SIZING.md) rather than being duplicated here — that
document is the single source of truth for sizing claims project-wide, per
`AGENTS.md`'s rule that every sizing claim identify whether it's observed, sourced,
projected, or measured locally.

## Provenance

Everything in this directory grounded in a "real, inspected" example was pulled from
the **June 2026 snapshot** (`20260601`), downloaded and directly inspected on the
coordination host on **2026-07-01**. Every real example XML/JSON fragment quoted
here is CC0 catalog data (see [`docs/DATA_AND_RIGHTS.md`](../DATA_AND_RIGHTS.md) for
the licensing distinction between the dumps and the API). Where this reference
describes something not independently verified against real data (e.g. a field only
documented in Discogs' public API spec, never seen in an actual response during this
project's work), it says so explicitly rather than implying it was observed.

`raw-dump-schema.md`'s "Real full-dataset profiling (2026-07-02)" section goes one
step further: once the same snapshot's full unbounded parse completed
(`docs/BUILD_PLAN.md` Milestone 3), it profiles the actual *output* dataset with
DuckDB (`scripts/profile-discogs-dataset.sh`) — real column-level null rates,
distributions, and encoding/outlier spot checks across all 19.19M releases, not
just hand-inspected single examples.

## For future agent sessions

If you're picking up Milestone 5 (one-hop expansion) or later and need to know what
fields *exist* in the source data before deciding what to extract next, start with
`raw-dump-schema.md`'s "Fields not yet in our schema" callouts in each dump kind's
section — they list real fields Discogs provides that `packages/catalog` doesn't
parse yet, which is exactly the gap those later milestones need to close
deliberately, not by guessing.
