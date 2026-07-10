# Local curator

This is a private, local-only review surface for scored cohort artifacts. It is not part
of `apps/web`, is not included in the Astro build, and has no public route.

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
