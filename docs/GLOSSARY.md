# Glossary

**Artist** — A credited person or group represented by a stable normalized identity while preserving source names.

**Cohort source** — An operator-saved third-party page (e.g. an editorial "best albums" post) used as the starting point for a curated gameplay cohort; the raw page is never committed, only reviewed factual metadata is ever extracted from it.

**Contributor** — Any credited person or organization, including performers, writers, producers, engineers, arrangers, designers, and others.

**Credit evidence** — The source release, role text, contributor identity, and provenance that justify one graph relationship.

**Evidence-bearing path** — A route that retains the release and credit information for every connection rather than returning only artist names.

**Extracted candidate** — One album record (rank, artist, title, year, optional Discogs master/release link) pulled from a cohort source's saved HTML, before any resolution against the real dataset.

**Private seed** — Locally supplied collection membership used to choose an initial catalog slice without being committed or published.

**Release** — A source catalog entity representing an issued recording or edition; exact treatment of masters, versions, and formats will be defined by data contracts.

**Snapshot** — An immutable, versioned set of normalized data or graph structures used consistently by jobs and requests.

**Static-first** — A delivery model in which the core public experience is generated ahead of time and remains usable without a live backend.

**Worker job** — A bounded, repeatable task with declared inputs, snapshot version, resource expectations, retry behavior, and output contract.
