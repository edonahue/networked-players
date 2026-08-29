# Local curator / research workbench

This is a private, local-only review server with two modes (`review_server.py --mode
cohort|workbench`). Neither is part of `apps/web`, included in the Astro build, or has a
public route.

## Cohort mode (default) — review scored cohort artifacts

Generate the local editorial packet first:

```bash
uv run networked-players-catalog draft-cohort-editorial-review \
  --resolved local/analysis/cohorts/<source-id>/resolved.json \
  --connectivity local/analysis/cohorts/<source-id>/connectivity.json \
  --output-json local/analysis/cohorts/<source-id>/editorial-review.json \
  --output-markdown local/analysis/cohorts/<source-id>/editorial-review.md
```

Run on loopback for the same machine:

```bash
make curator SOURCE_ID=<source-id>
```

For another device on the trusted LAN, bind explicitly and use the coordination host's
LAN address in a browser:

```bash
make curator SOURCE_ID=<source-id> ARGS="--host 0.0.0.0 --reviewed-by <your-name>"
```

The UI writes only `data/private/cohort-review/<source-id>-selection.json`. Selection is
still human-authored and promotion remains a separate CLI step. The editorial packet uses
the saved Discogs API cache's `uri150` values as hotlinked cover thumbnails when available;
no image bytes are downloaded or rehosted. `--art-dir` is reserved for an optional future
local-art source.

To populate missing release metadata before starting the curator, explicitly opt into the
existing rate-limited Discogs API cache flow. This needs a local `DISCOGS_TOKEN` and makes
network requests only for cache misses:

```bash
uv run networked-players-catalog draft-cohort-editorial-review \
  --resolved local/analysis/cohorts/<source-id>/resolved.json \
  --connectivity local/analysis/cohorts/<source-id>/connectivity.json \
  --output-json local/analysis/cohorts/<source-id>/editorial-review.json \
  --output-markdown local/analysis/cohorts/<source-id>/editorial-review.md \
  --enrich-images
```

## Workbench mode — run `research-compare` comparisons from a browser

Phase 7 PR D's third mode: a form for `compare_albums`/`compare_artists`/`compare_scenes`
instead of the `research-compare` CLI, writing the exact same run bookkeeping under
`local/research/<topic>/runs/<run-id>/`. See `packages/research/README.md` for what each
comparison type covers.

```bash
make workbench
```

Then open <http://127.0.0.1:8765/>, pick a comparison type, a `corpus_root` (a
`research-build-corpus` topic corpus or the full canonical snapshot -- either way it must
resolve under `local/`), a run topic, and the album/artist/scene ids to compare.

For another device on the trusted LAN:

```bash
make workbench ARGS="--host 0.0.0.0"
```

Invariants this mode holds to (plan section 11): loopback by default, no Cloudflare, not in
the public build, no accounts or analytics, every run written only under `local/research/`.
`corpus_root` and `topic` are both validated server-side (not just trusted from the form) --
`corpus_root` must resolve under `local/`, and `topic` must be a single plain name, never a
path -- since this mode, like cohort mode, can be bound to `0.0.0.0` for LAN access.

### Explore (Slice 1) — search a corpus and open a result's evidence

Below the compare form, "Explore" searches album titles or artist names in a given
`corpus_root` (defaults to the compare form's own field) and, on click, shows that
release's or artist's real credit rows inline. This is Slice 1 of the plan's fuller
"Explore" bullet -- route filters, scope selection, bounded graph rendering, compare/pin,
and saved reproducible request files are a larger follow-up, not built yet.

`corpus_root` is validated the same way as the compare form's (`_safe_corpus_root`); a
release or artist id with no match in the corpus is a clean 400, never a crash.
