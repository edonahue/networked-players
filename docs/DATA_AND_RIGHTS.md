# Data, provenance, and rights

Technical access to music metadata does not automatically grant permission to republish every field or response. Review current source terms again before each public release.

## Data classes

### Private seed

The owner's collection membership, exports, account identifiers, notes, folders, ratings, and other user-associated fields remain local. The repository may publish the import contract and synthetic examples, not the real seed. The first adapter should reduce a local export to release IDs before catalog processing.

### Monthly catalog dumps

Discogs describes its monthly artist, label, master, and release XML exports as CC0. These dumps are the preferred durable source for bulk catalog facts. The project still records source, snapshot date, object URL, checksum, parser version, and schema version so an output can be reproduced and corrected.

### API responses

API access is a separate contractual path. Current terms distinguish CC0 database data from restricted user, collection, wantlist, marketplace, and other account-associated data; they also include notice, linking, credential, and freshness requirements. API integration therefore remains centralized, bounded, and optional for the initial graph build. Raw API responses are not assumed safe to republish merely because some fields overlap a dump.

### Images and audio

Cover art may be hotlinked directly from Discogs' own image CDN (`i.discogs.com`) by
referencing its URL in an `<img src>` -- the repository never downloads, stores, or
rehosts the image bytes themselves. Hotlinking is a scoping decision (pointing at a
URL Discogs already serves publicly), not a rights determination (republishing an
asset would be); see ADR 0012. Artist images, preview audio, and marketplace assets
remain out of scope. A playable release must still work from textual evidence first --
cover art is presentation, not load-bearing evidence.

### Curated third-party source pages

An operator may manually save a third-party editorial page (e.g. a "best albums" blog
post) as a starting point for a curated gameplay cohort — see
[ADR 0028](decisions/0028-curated-cohort-source-ingestion.md). The raw saved page is
never committed and never republished: its selection, ranking, and prose are the
original author's own editorial work, not this project's to redistribute. Only small
factual metadata that Discogs itself would also expose for the same release — artist,
title, year, and a Discogs master/release identifier, and only when visibly linked in
the saved source — is ever extracted, and even that minimal metadata stays a local-only
intermediate until a separate, explicit, human-reviewed promotion step (never the
extraction pipeline itself) moves anything toward a committed cohort file. There is no
live fetching anywhere in this pipeline, by design, not merely by current omission.

### Derived artifacts

Paths, aggregate findings, graph statistics, and challenges should retain enough provenance to show the source release and credit behind each step. Derived does not mean rights-free. Public artifacts should contain only fields needed to understand and verify the experience.

## Required provenance

A published dataset or challenge should record:

- source and access method;
- retrieval or snapshot date;
- source identifiers and evidence links where appropriate;
- compressed object size and SHA-256 when locally available;
- schema and parser versions;
- transformation and graph snapshot versions;
- restricted or omitted fields;
- redistribution, notice, linking, freshness, and deletion obligations reviewed for that output.

## Identity semantics

- A positive linked artist ID is the initial playable identity key.
- PAN and ANV are not interchangeable: the stable artist identity and the credited display name are retained separately.
- Alias and namesake resolution belongs to explicit artist data and later rules, not string similarity.
- A missing or zero artist ID is retained as non-linked evidence and excluded from playable identity nodes until a documented resolution exists.
- Main release artists and extra artists, plus release and track scope, remain distinguishable.
- Original role text is preserved before any role taxonomy or normalization.

## Influence versus participation

A credit is evidence of documented participation or collaboration. It is not proof of influence, friendship, mentorship, or creative lineage. Editorial claims beyond the credit graph require separate sources and careful wording.
