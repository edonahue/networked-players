# Discogs REST API v2 schema (release endpoint)

Real structure, confirmed live against `api.discogs.com` during
[ADR 0012](../decisions/0012-real-discogs-api-demo-challenge.md)'s work
(2026-07-01) and encoded in `packages/catalog/src/networked_players_catalog/discogs/api_client.py`
and `demo_challenge.py`. This is a **separate data source and a separate licensing
regime** from the monthly dump XML — see "Licensing" below before assuming API data
can be treated the same way as dump data.

## Access

- **Base URL:** `https://api.discogs.com` (confirmed real; distinct from the dump
  hosting at `data.discogs.com` — see `raw-dump-schema.md`).
- **Endpoint used by this project:** `GET /releases/{id}` — single-release lookup.
  This project has not integrated any other API endpoint (search, artist lookup,
  label lookup) as of 2026-07-01.
- **Auth:** `Authorization: Discogs token=<token>` header, plus
  `Accept: application/vnd.discogs.v2.discogs+json`. A personal access token from a
  Discogs account — see `docs/DISCOGS_INGESTION.md`'s source-role table: API
  credentials stay coordination-host-only, never distributed to workers or browsers.
- **Rate limit:** observed ~60 requests/minute per token; this project throttles to
  ~1.1s/request (`DEFAULT_REQUEST_DELAY_SECONDS` in `api_client.py`) and backs off
  further on `X-Discogs-Ratelimit-Remaining` getting low or a `429` response.
- **Image CDN:** cover art URLs point at `i.discogs.com`, confirmed live — a
  separate host from both the dump/API hosts. Hotlinked directly (never
  downloaded/rehosted) per ADR 0012's decision.

## Response shape (`GET /releases/{id}`)

Real fields consumed by `demo_challenge.py`'s `parse_api_release()`:

| API JSON field | Type | Notes |
| --- | --- | --- |
| `id` | int | Release ID — same numbering as the dump XML's `release id="..."` attribute; **the same release has the same ID in both sources** |
| `status` | string | e.g. `"Accepted"` |
| `title` | string | |
| `country` | string | |
| `released` | string | Full date string when present |
| `year` | int | Fallback when `released` is absent — the dump XML has no equivalent fallback field, it just uses whatever's in `<released>` verbatim |
| `master_id` | int | Same meaning as the dump's `master_id`, but the API response does **not** include the dump's `is_main_release` boolean — that information isn't present on the release-level API response at all |
| `data_quality` | string | |
| `uri` | string | Human-browsable `discogs.com` page URL — preferred as the evidence link over constructing one, since it's the real canonical URL Discogs itself considers authoritative |
| `artists[]` | array | Release-level main artists |
| `extraartists[]` | array | Release-level extra credits |
| `tracklist[]` | array | Each entry can carry its **own** nested `artists[]`/`extraartists[]` for track-scope credits |
| `images[]` | array | **API-only** — the dump XML has no image data whatsoever. Each entry: `uri`, `uri150` (thumbnail), `width`, `height`, `type` (`"primary"` sorts first) |

Each artist-credit object (in `artists[]`, `extraartists[]`, or a track's nested
versions) has the same field names as the dump XML's `<artist>` sub-elements —
this is a real, direct correspondence, not a coincidence of this project's naming:

| API JSON field | Dump XML element | Meaning |
| --- | --- | --- |
| `id` | `<id>` | PAN — the linked artist ID |
| `name` | `<name>` | Credited display name |
| `anv` | `<anv>` | Artist Name Variation |
| `join` | `<join>` | Connector text (e.g. `"&"`, `","`) |
| `role` | `<role>` | Original role text |
| `tracks` | `<tracks>` | Free-text track reference (e.g. `"A2"`) when a release-level credit is scoped to specific tracks but not resolved to a nested track entry |

## Cross-reference: dump XML vs. API JSON, field by field

| Concept | Dump XML | API JSON | Notes |
| --- | --- | --- | --- |
| Release ID | `<release id="N">` (attribute) | `"id": N` | Same numbering |
| Master relationship | `<master_id is_main_release="true/false">N</master_id>` | `"master_id": N` only | API drops `is_main_release`; this project's `parse_api_release()` explicitly leaves `master_is_main_release` as `None` rather than guessing |
| Cover art | *(absent — dumps have no image data)* | `images[]` | API-exclusive |
| Label | `<labels><label name=.. catno=.. id=..>` | *(not fetched by this project's API integration — the API response does include a `labels[]` array with similar fields, but `demo_challenge.py` doesn't consume it)* | A real, currently-unused overlap |
| Genres/styles | `<genres>`/`<styles>` | present in the API response too, not currently consumed | |
| Notes | `<notes>` free text | present as `notes` in the API response, not currently consumed | |
| Track scope resolution | Structural: a `<track>` element genuinely containing nested `<artists>`/`<extraartists>` | Same structural rule, applied to JSON nesting instead of XML nesting — **never** inferred from parsing the free-text `tracks` field (e.g. `"1-2"`) in either source. This is a deliberate, shared design rule between `releases.py` (dump) and `demo_challenge.py` (API), documented in the latter's module docstring |

## A source-specific identity rule: artist ID `194`

Discogs reserves artist ID `194` for **"Various"** — a compilation placeholder, not
an individual — confirmed via the live API and handled explicitly in
`demo_challenge.py` (`NON_INDIVIDUAL_ARTIST_IDS`). Not yet confirmed whether this
same reserved-ID convention is exposed identically in the dump XML (no `artists.xml.gz`
record for ID `194` was inspected during this documentation pass to confirm one way
or the other) — treat this as an API-confirmed fact only until checked against the
dump.

## Licensing (see `docs/DATA_AND_RIGHTS.md` for the authoritative statement)

The monthly dumps are CC0. **API responses are not** — Discogs' API Terms of Use
distinguish CC0 database data from restricted user/collection/marketplace data and
add notice, linking, credential, and freshness requirements on top. A field
appearing in both an API response and a CC0 dump doesn't make the API response
itself CC0. This project's API usage stays "bounded gap filling," per
[ADR 0005](../decisions/0005-discogs-hybrid-acquisition.md), not a bulk-ingestion
substitute for the dumps.
