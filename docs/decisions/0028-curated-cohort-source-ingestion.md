# ADR 0028: Curated cohort source ingestion (saved HTML, never live-fetched)

- **Status:** Accepted
- **Date:** 2026-07-05

## Context

`data/albums/top-albums-v1.json` proves the resolve → path-find → publish flow works
(`match_albums`, `build_challenge_v2`, `CreditGraph.find_path`), but it's a one-off,
hand-typed list. The next product step is a repeatable pipeline: the operator manually
saves a third-party curated page (e.g. a Discogs "Digs"-style "best albums" post),
extracts album candidates from it, and eventually resolves and scores them for gameplay.

This is a genuinely new kind of input for this project. [ADR 0011](0011-private-seed-contract.md)
named its own revisit trigger: *"Revisit if a second private-data input type is ever
added, to decide whether it shares this [private-seed] contract."* A saved third-party
page is exactly that second input type, and the answer is no — it needs its own contract.
`docs/DATA_AND_RIGHTS.md` currently defines three data classes (private seed, monthly
dumps, API responses); none of them fit a manually-saved editorial web page, which is
neither Discogs-authored catalog data nor the operator's own private collection, but a
third party's editorial work that happens to sometimes reference Discogs.

## Decision

**Saved-HTML import only, forever — no live fetching in this pipeline, ever, not even
behind a flag.** The operator saves a page manually, however they choose; this project
never requests one over the network. This is a permanent posture, not a temporary
first-PR limitation to be lifted later: it sidesteps robots/access, rate-limiting, and
anti-bot concerns entirely by never issuing the request those concerns would apply to.

**A new sibling subpackage**, `packages/catalog/src/networked_players_catalog/cohort_source/`
— not nested under `discogs/`. Everything in `discogs/` parses data Discogs itself
produced (dumps, the REST API, a private collection export); a saved third-party page is
structurally and legally different, and nesting it under `discogs/` would blur exactly
the distinction `DATA_AND_RIGHTS.md`'s per-source rights posture depends on.

**Two new contracts**: `data/contracts/cohort-source-v1.md` (provenance for one saved
source — URL, title, saved date, operator note, and a raw-HTML pointer that is a bare
filename only, never a path) and `data/contracts/album-cohort-extracted-v1.md`
(extracted candidate records: rank, artist, title, year, `master_id`/`release_id`,
confidence, warnings). The raw HTML itself lives only under `data/private/source-html/`,
inheriting the same git-ignore and agent-`Read`-deny protection the private seed already
has — no new configuration needed.

**Naming: "cohort source ingestion" / "cohort source importer," never "crawler" or
"scraper,"** in code, docs, commit messages, and CLI help text. Those words describe
automated, recursive, live-fetching systems; this is a manual, single-file, offline
import.

**Never infer a Discogs identity.** `master_id`/`release_id` are populated only from a
literal `/master/<id>` or `/release/<id>` link visible in the saved HTML — never guessed
from title/artist text. A candidate with missing or ambiguous data is never dropped; the
field is left `null` and a `warnings` entry explains why.

**This first stage (PR 1 of the pipeline) publishes nothing.** Extraction produces a
local-only intermediate under `local/analysis/cohorts/<source-id>/`. Resolving candidates
against the real dataset, scoring graph connectivity, and any eventual publication to
`data/albums/` are separate, later, explicitly reviewed stages — not decided by this ADR.

## Consequences

`docs/DATA_AND_RIGHTS.md` gains a fourth data class ("Curated third-party source pages")
and `docs/PUBLIC_PRIVATE_BOUNDARY.md`'s private/local list gains raw saved HTML.
`docs/COHORT_SOURCE_INGESTION.md` documents the pipeline stage in the same style as
`docs/DISCOGS_INGESTION.md`, kept as a separate document rather than folded into it,
since that document's title and scope are specifically the Discogs dump/API pipeline.
`pyproject.toml`'s `packages` list gains `networked_players_catalog.cohort_source`. No
existing file's behavior changes — this is entirely additive.

## Validation

`make check` green (146 tests, up from 135) with the new subpackage under mypy strict.
New tests cover: happy-path extraction against a fully fabricated fixture
(`data/samples/cohort-source-sample.html` — invented artist names, invented Discogs IDs,
no real saved page content anywhere), missing-link and missing-year handling (asserting
`null` + a warning, never a guess), empty/malformed HTML raising a clean error,
a non-list page returning an empty candidate list with a note rather than an error,
`validate_extracted_candidates()` rejecting an unknown top-level key, an invalid
`confidence` value, and a forbidden-substring leak, and a CLI round-trip test plus an
explicit "no absolute path leaks into the output JSON" privacy test. `grep -ri
"crawl|scrape"` over every new file returns nothing. `git check-ignore -v` confirms both
`data/private/source-html/` and `local/analysis/cohorts/` are already covered by the
existing `.gitignore` — no new ignore rule was needed.

## Revisit trigger

Revisit the "never live-fetch" posture only if a future, explicit product decision
chooses to support it — and if so, expect a new ADR, not a quiet change to this one,
given how central the posture is to this pipeline's whole rights/access story. Revisit
whether `master_id`/`release_id` inference should ever move beyond "literal link only"
if a resolver stage downstream finds text-based resolution reliable enough to backfill
these fields with a clearly-labeled lower confidence — a decision for that stage's own
ADR, not this one. Revisit the `cohort_source` package boundary if it ever needs to share
significant code with `discogs/` beyond incidental utility functions.
