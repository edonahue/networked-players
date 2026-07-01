# ADR 0012: Real Discogs-API demo challenge -- images, curated subset, ahead of Milestone 8

- **Status:** Accepted
- **Date:** 2026-07-01

## Context

`apps/web` currently ships a 100% synthetic demo (four invented releases, three curated
paths, zero images), explicitly labeled a placeholder in `apps/web/README.md` and
`apps/web/AGENTS.md`. The formal path to real content is `docs/BUILD_PLAN.md`'s
Milestone 8, gated behind Milestones 3/5/6/7 -- the full monthly-dump pipeline -- none of
which are complete; Milestone 3 is still blocked on a 250GB disk floor (ADR 0010).

ADR 0011 produced a real, private, release-ID-only seed. ADR 0005 already anticipated
"bounded gap filling" via the Discogs API as a sanctioned, centralized, coordination-host
acquisition path -- distinct from bulk ingestion, which stays dump-only. Using the API
against the seed's release IDs makes a real demo achievable now, as a deliberate detour
ahead of and separate from Milestone 8, which remains the intended durable replacement.

Two things were confirmed, not assumed, before this decision:

- `docs/DATA_AND_RIGHTS.md`'s "Images and audio" section ("not part of the initial
  ingestion contract") is scoping language, not a rights prohibition -- contrast with the
  same document's API-response language, which does use rights terms ("not assumed safe
  to republish"). Bringing images in is a deliberate scope expansion, recorded here, not
  a rule violation.
- Publishing facts *derived from* the private seed is fine (Discogs release data is
  public), but exposing too many of the seed's specific release IDs starts to
  reconstruct real collection membership, which `docs/PUBLIC_PRIVATE_BOUNDARY.md`
  explicitly asks to avoid. The seed itself is not small.

## Decision

1. **`discogs/api_client.py`**: a stdlib-only (`urllib`), rate-limited (~1.1s/request),
   retrying (429/`Retry-After` aware) client for `GET /releases/{id}`, plus an
   atomic-write on-disk `ReleaseCache` keyed by release ID. `DISCOGS_TOKEN` is read from
   the environment only (`load_token`), never hardcoded or defaulted; credentials and the
   raw response cache stay on the coordination host, matching ADR 0005 and
   `docs/DISCOGS_INGESTION.md`.
2. **`discogs/demo_challenge.py`**: normalizes raw API responses into the existing
   Release/Credit shape (PAN `artist_id` separate from ANV, `credit_scope` vocabulary
   preserved, non-linked credits retained as evidence but excluded from playable
   identity), adds a `images: []` field (hotlinked `uri`/`uri150` straight from Discogs'
   own CDN, never downloaded), builds an artist co-credit adjacency graph from real
   linked credits, and **curates a small subset** -- a handful of 1- and 2-hop paths
   (~8), touching a fraction of the fetched releases -- as the structural mitigation for
   the collection-membership-reconstruction risk above.
3. Track-level credit scope (`track_artist`/`track_credit`) is only assigned when the API
   response genuinely nests `artists`/`extraartists` under a `tracklist[]` entry --
   mirroring how the XML dump parser derives scope from real document nesting. A
   release-level extra-artist with a non-empty `tracks` text field but no nested entry
   stays `release_credit` scope, with `credited_tracks_text` preserved verbatim: evidence
   kept, not silently dropped, but not over-claimed as track-resolved either.
4. New `build-demo-challenge` CLI subcommand: reads the private seed, fetches (cache-first)
   every release, builds and curates the graph, and writes a `challenge.v1`-shaped JSON
   artifact. The operator runs this themselves against their real token and seed; no
   agent session executes it.
5. `apps/web` hotlinks cover art directly from Discogs' CDN (`i.discogs.com`) in
   `<img src>` -- referencing a URL is a scoping decision, not a rights determination
   (republishing an asset would be); the repository never downloads, stores, or rehosts
   image bytes.
6. `docs/DATA_AND_RIGHTS.md`'s "Images and audio" section is updated to state this
   explicitly, replacing the now-stale "not part of the initial ingestion contract"
   framing.

## Consequences

The public demo gets a real experience -- real releases, real artist connections, real
cover art, deployed live -- well ahead of the multi-milestone dump pipeline. This comes
with weaker reproducibility than a dump-derived artifact (a single release's API record
can change between fetches; there is no monthly CC0 snapshot backing it), and a second,
API-sourced code path alongside the eventual dump-based one. Milestone 8 is not retired
by this decision -- when it produces a real dump-derived artifact under the same
`challenge.v1` schema, this project should explicitly decide whether to replace this
artifact, keep both, or retire the API path. The raw per-release API response cache
(`data/private/discogs-api-cache/`) and the seed itself never leave `data/private/` and
are never published.

## Validation

- `packages/catalog/tests/test_api_client.py`: HTTP fixture asserts the `Authorization`
  header, `User-Agent`, 429/`Retry-After` retry behavior, cache round-trip with zero
  extra HTTP calls on a hit, and `MissingCredentialError` on an empty environment.
- `packages/catalog/tests/test_demo_challenge.py`: synthetic ~16-release fixture
  (`data/samples/discogs-api-release-sample.json`) asserts parsing correctness
  (nullability fallbacks, `released`/year fallback, source URL fallback), release- vs.
  track-scope credit assignment, non-linked artists excluded from the graph, no duplicate
  curated path endpoints, and the key privacy assertion:
  `len(build_challenge(...)["releases"]) < len(releases_by_id)`.
- `make check` passes fully offline (no token, no live API calls) for everything except
  the operator-run real fetch and deploy steps.
- After a real run: `git status` / `git check-ignore -v` confirm
  `data/private/discogs-api-cache/` and any staged output under `local/generated/` stay
  out of version control; the CLI's printed `releases_fetched` vs. `releases_published`
  counts make the curated-subset ratio visible on every run.

## Revisit trigger

Revisit when Milestone 8 produces a real dump-derived `challenge.v1` artifact -- decide
explicitly whether to replace, keep both, or retire this API-sourced path. Revisit if
Discogs API Terms of Service change in a way that affects hotlinking, rate limits, or
attribution requirements.
