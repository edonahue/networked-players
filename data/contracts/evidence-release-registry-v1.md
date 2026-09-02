# Evidence-release registry contract (evidence-release-registry-v1)

The public evidence-release registry
(`apps/web/public/data/evidence/release-registry.v1.json`), produced by
`networked-players-catalog build-evidence-release-registry` and validated
by `validate-evidence-release-registry` /
`networked_players_contracts.evidence_release_registry::evidence_release_registry_failures`
(ADR 0058).

> **A deduplicated, addressable lookup for every evidence release, not just
> the ones already described elsewhere.** Before this artifact, release
> metadata (title/year/country/source) existed only inside
> `challenge.v3.json` and `routes/rounds.v1.json` — a real but small subset
> (432 and 326 releases respectively). The pathfinding graph's broader ego
> network reaches far more releases than either of those describes
> (measured: over 17,000 release ids reachable only through it). This
> registry is the union of all three, so any hop anywhere in the product
> can render a real evidence card instead of a bare release id.

## Sizing decision: parallel arrays, not objects

At this scale (roughly two orders of magnitude past `contributor-index`'s
549 entries, closer to the pathfinding graph's own scale), this artifact is
shipped as **parallel arrays** (`titles[i]` describes `release_ids[i]`,
etc.), never an array of `{key: value, ...}` objects — the same
compactness principle `pathfinding-graph-v1.md` already documents (JSON
object-key repetition compresses far worse than repeated values in a flat
array at this size).

## Top-level shape

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | int | `1` or `2`. New builds emit `2`; `1` payloads still validate, since an artifact on disk regenerates independently of the validator that ships. |
| `catalog_version` | string | The canonical `catalog/albums.v1.json` version this registry belongs to. |
| `evidence_release_registry_version` | string | `evidence-release-registry-v<schema>-<snapshot>-<hash>` — a content hash over every published field array. The identity pool is schema-aware, so v2's `caveat_flags` is folded in and cannot leave a v1 hash describing content it never saw. |
| `generated_at` | string | Explicit operator-supplied ISO datetime (never the wall clock). |
| `source` | string | Provenance note naming the three union sources. |
| `license` | string | See `docs/DATA_AND_RIGHTS.md`. |
| `release_ids` | array of int | Sorted, deduplicated. Index `i` in every array below describes this same release. |
| `titles` | array of string | Non-empty. |
| `years` | array of int \| null | Parsed leading 4-digit year from the release's own `released` field; `null` where unavailable or implausible (outside 1900–2100). |
| `countries` | array of string \| null | |
| `master_ids` | array of int \| null | |
| `source_urls` | array of string | The dataset's own `source_url` provenance field (the Discogs monthly dump download URL) — **not** a per-release Discogs page link. Any consumer wanting a clickable release page constructs `https://www.discogs.com/release/{release_id}` directly from `release_ids[i]`, the same one-line pattern `connect.ts` and `pathfinding-graph-v1.md`'s evidence rendering already use; storing that as a second, derivable field here would be redundant. |
| `cover_uri150s` | array of string \| null | Hotlinked `i.discogs.com` cover art URL, populated only where the release is a catalog album's own `main_release_id` **and** that album already has an `album-art.v1.json` entry (reused verbatim — no new Discogs calls, no rehosting). `null` everywhere else — honestly, not a broken-image placeholder. |
| `relation_to_catalog_album_ids` | array of string \| null | The catalog `album_id` when this release is that album's `main_release_id`, else `null`. |
| `caveat_flags` | array of int | **v2 only.** Bitmask of format-descriptor caveats for this release, bit order given by `caveat_flag_names`. |
| `caveat_flag_names` | array of string | **v2 only.** The published bit order — the legend travels with the data so the integers are self-describing. Validated to equal the contract's own order exactly; a payload that disagrees is one whose integers mean something else. |

### `caveat_flags` (v2)

| Bit | Name | Set when `release_formats.descriptions` contains |
| --- | --- | --- |
| 0 | `compilation` | `Compilation` |
| 1 | `mixed` | `Mixed` |
| 2 | `promo` | `Promo` |
| 3 | `reissue` | `Reissue` or `Repress` |
| 4 | `sampler` | `Sampler` |
| 5 | `unofficial` | `Unofficial Release` |

These say what a release **is tagged as**, never what it is. Discogs format
descriptors are reliable for *exclusion* and not for confirmation:
`docs/RELEASE_FORMAT_RESEARCH.md` measured 94.7% of a known false-positive
population carrying only a bare `Album` descriptor. There is therefore
deliberately no `studio_album` flag and no positive quality enum, and
`caveat_flags[i] == 0` means "nothing here warrants a caveat" — never
"confirmed studio album". Zero is also what a dataset generation without a
`release_formats` table produces, which is the second reason the flags are
only ever used to de-prefer and to caveat.

Bit order is append-only. Reordering or removing a flag silently relabels
every published integer.

## Validation

`evidence_release_registry_failures(registry, catalog)` checks: exact
top-level key set for the payload's own schema version, `schema_version`
in `{1, 2}`, `catalog_version` agreement,
`evidence_release_registry_version` recomputation, `release_ids` sorted
and deduplicated, every parallel array the same length as `release_ids`,
non-empty titles, years within a plausible range, `source_urls` all
well-formed `https://` URLs, `cover_uri150s` entries (where non-null)
hotlinking `i.discogs.com` specifically, and every non-null
`relation_to_catalog_album_ids` entry resolving to a real catalog album.
For `schema_version == 2` it additionally checks that `caveat_flag_names`
matches the contract's published bit order exactly and that no
`caveat_flags` entry sets a bit outside it.

## Revisit trigger

If a future build's real measured gzip size meaningfully exceeds the
pathfinding graph's own ~1.8MB budget, revisit this artifact's shape (e.g.
splitting metadata the browser needs immediately from a lazily-fetched
detail tier) before publishing it as-is — the parallel-array decision above
is the first mitigation, not a guarantee the result stays small
indefinitely as the underlying pathfinding graph's ego network grows.
