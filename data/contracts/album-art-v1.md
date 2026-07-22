# Album-art registry contract (album-art-v1)

The public, presentation-only cover-art registry
(`apps/web/public/data/catalog/album-art.v1.json`), produced by
`networked-players-catalog build-album-art-registry` and validated by
`validate-album-art-registry` /
`networked_players_contracts.album_art::album_art_failures` (ADR 0044/0045).

> **Deliberately NOT frozen game content.** Cover art is a mutable, refreshable
> presentation detail; it lives here, keyed by canonical album id, and is
> **never** embedded in a Connection Guesser round, universe, or the daily
> manifest. `round_content_fingerprint` and the pool `artifact_version` are
> computed over art-free rounds, so enriching or refreshing art can never
> change a round fingerprint or invalidate the daily manifest. Cover art is
> never evidence (`docs/DATA_AND_RIGHTS.md`).

## Top-level shape

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | int | Always `1`. |
| `catalog_version` | string | The canonical `catalog/albums.v1.json` version this registry belongs to. Validation requires exact agreement; a mismatched registry is refused (and the client ignores it). |
| `art_version` | string | `album-art-v1-<snapshot>-<hash>` — a content hash of the entries **sorted by `album_id`** (order-INSENSITIVE: the registry is a lookup map). Only `album_id` + the two hotlink URLs are hashed, so cosmetic `width`/`height` changes don't move it; a real URL change does. |
| `generated_at` | string | Explicit operator-supplied ISO datetime (never the wall clock) — identical inputs reproduce a byte-identical registry. |
| `source` | string | Provenance: Discogs API `/releases/{id}` images, hotlinked from `i.discogs.com`; no image bytes stored. |
| `license` | string | Presentational-only note; see `docs/DATA_AND_RIGHTS.md`. |
| `albums` | array | See below. May be empty (all placeholders). |

## `albums[]` entry shape

| Field | Type | Meaning |
| --- | --- | --- |
| `album_id` | string | A canonical catalog album id (`master-<n>`). Must exist in the catalog; unique across the array. |
| `main_release_id` | int | The Discogs release the image came from (the catalog album's `main_release_id`). |
| `uri150` | string | Thumbnail hotlink — **https**, host `i.discogs.com`. |
| `uri` | string | Full-size hotlink — **https**, host `i.discogs.com`. |
| `width` / `height` | int | Optional pixel dimensions of the full image. |

**Not every catalog album needs an entry.** An album with no usable image is
simply absent → the frontend renders the polished placeholder.

## Validation

`album_art_failures(registry, catalog)` (pure, Pi-safe) checks: exact
top-level key set; `schema_version`; non-empty `catalog_version`/`art_version`/
`generated_at`/`source`/`license`; **`catalog_version` agreement** with the
canonical catalog; `art_version` recomputation; each entry's keys, `album_id`
membership in the catalog + uniqueness, integer `main_release_id`, and **https
URLs on an approved host** (`i.discogs.com`); and a privacy scan (`/home/`,
`data/private`, `.ssh`, `DISCOGS_TOKEN`, `token=`). An empty registry is valid.

## Enrichment (operator-only)

`build-album-art-registry` runs on the coordination host (`DISCOGS_TOKEN` from
env; raw API cache under `data/private/`, never committed). It reuses the
rate-limited, resumable Discogs client (`discogs/api_client.py`: ~1.1s
throttle, 429/`Retry-After` handling, on-disk `ReleaseCache`). Lookup is
deterministic by `main_release_id` — **no fuzzy title search**, never attach a
wrong pressing to pad coverage. Hotlink URLs only; **no image bytes are
downloaded, proxied, or rehosted**.

## Frontend resolution

- **Game (runtime):** `apps/web/src/game/albumArt.ts::fetchAlbumArt(catalogVersion)`
  fetches the registry once per page, ignores a registry whose `catalog_version`
  disagrees with the pool, and builds an `album_id → {uri150,uri}` map.
  `flagship.ts::renderSleeve` resolves real sleeves by id; a synthetic album's
  `{kind:"generated"}` art still renders an SVG sleeve.
- **Browse (build-time):** `apps/web/src/data/albumArt.ts::coverFor(albumId)`
  reads the registry once at build; `AlbumCard` and the album detail page
  resolve covers by id.
- **Never blocks gameplay.** Any failure (missing/404 registry, malformed,
  catalog-version mismatch, unknown id, missing entry, malformed URL, upstream
  image 403/404, slow/expired) → the polished placeholder; the album title and
  identity stay visible.

## Hotlink / CSP notes

Images are hotlinked from `i.discogs.com` over https. The site CSP
(`apps/web/public/_headers`) does not restrict `img-src`; if it is ever
tightened it must include `img-src 'self' https://i.discogs.com data:`. The
`Referrer-Policy` (`strict-origin-when-cross-origin`) is compatible with
Discogs hotlinking.
