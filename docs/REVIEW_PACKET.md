# Review packet

A review packet is one self-contained, offline `.html` file that turns a machine output into a
page the owner reviews with the keyboard. It is a **private working file**: using it publishes
nothing and approves nothing by itself. Generator: `packages/catalog/src/networked_players_catalog/review_packet.py`,
command `networked-players-catalog build-review-packet`.

The page has no network requests (no fonts, images, CDN or links) and shows no cover art. Progress
is kept in `localStorage`, keyed by a hash of the input, so a reload does not lose work; the page
works without storage.

## Generating

The output must resolve under `data/private/` or `local/` (both git-ignored). Anything else,
especially `apps/web/public/`, is refused. Output is deterministic; `--generated-at` is an
optional label and the only date in the file.

Round mode (one review of the round's scored candidates):

```sh
uv run networked-players-catalog build-review-packet --mode round --round 3 \
  --scored-candidates local/scored.json \
  --catalog apps/web/public/data/catalog/albums.v1.json \
  --output local/round-3-review.html
```

Inputs: `--scored-candidates` is the `score-expansion-candidates` output (required). Optional:
`--catalog`, `--approved-pool` (already-published masters cannot be approved),
`--review-packet` (the `build-expansion-review-packet` JSON, joined by `master_id` to supply year and
lane), `--guidance` (JSON `{"<lane>": <count>}`, shown against approved counts per lane). The
scorer does not emit year, lane or connection lists; the page shows them only when the review
packet or a row's optional `connections` carries them. The scorer has no "ambiguous" marker
either; a row with `ambiguous` or `needs_review` set shows an "ambiguous - needs review" state,
and any eligibility value other than `eligible` is shown as the reason it failed. No blended score
is shown or computed; sort by any single column.

Collection mode (one review of a candidate set of records):

```sh
uv run networked-players-research research-album-projection --output local/study.json
uv run networked-players-catalog build-review-packet --mode collection \
  --study local/study.json --output local/collection-review.html
```

## Keys

`j`/`k` or arrows move; `a` approve (collection: keep cluster), `r` reject (drop cluster), `d`
defer (needs work), `u` clear; round mode `s` cycles the public selection source; `/` filters;
`Esc` leaves a field. In collection mode, tab to a record checkbox and press space to keep or drop
that record; type a working title and note per cluster.

## Exports

| File | Mode | What it is | Where it goes |
|---|---|---|---|
| `approved-pool-additions.json` | round | JSON array of `{master_id, round, selection_source}` for approved albums only | You append it to `data/albums/approved-pool-v1.json` (sorted by `master_id`) and commit; that is the approval |
| `review-notes.private.json` | round | Every decision (including rejections and deferrals), notes, timestamps | Stays private; never committed |
| `collection-selection.private.json` | collection | Kept records per cluster, working titles, notes, cluster status | Stays private (ADR 0031 selection file); approves nothing by itself |

## Privacy rules and how they are enforced

- Additions carry exactly three fields. The page refuses to export an entry with any other field,
  a missing field, a duplicate, an already-published album, or a `selection_source` outside ADR 0069's
  public enum (`editorial`, `already_published`, `graph_rich`, `coverage_gap`,
  `generic_candidate`). Scores, notes and rejected or deferred items never enter the file.
- The scorer's `in_private_seed` flag is dropped by the generator and never reaches the page. A
  personal-collection pick is labelled `editorial`.
- All titles and names are untrusted: embedded as ASCII JSON with `<`, `>`, `&` escaped and rendered
  with `textContent`.
- Tests: `packages/catalog/tests/test_review_packet.py` (determinism, path refusal, escaping,
  offline markup, round trip, export logic under Node, and the real `approved_pool_failures`
  contract on a pool with the additions appended).

## Publishing a Collection

Every step needs the owner; nothing here runs automatically and no step is implied by the one
before it. Contracts: `data/contracts/collection-v1.md`, ADR 0074.

1. **Export.** Review a collection packet (above) and download
   `collection-selection.private.json`. Keep it, and the study JSON it came from, under
   `data/private/` or `local/`.
2. **Write the public text.** Title, intro and (only for a genuinely sourced theme) an attribution,
   as a small JSON file `{"title": ..., "intro": ..., "attribution": {"label": ..., "source_url": ...}}`
   or as `--title` / `--intro`. These are written by the owner and never generated. The working
   title in the selection is not copied; use it as the title only by passing it explicitly.
3. **Promote to a staging directory.**

   ```sh
   uv run networked-players-catalog promote-collection \
     --selection local/collection-selection.private.json --study local/study.json \
     --collection-id my-slug --cluster 0 --text-file local/collection-text.json \
     --journey master-1,master-2,master-3 --generated-at 2026-12-01T00:00:00+00:00
   ```

   Output goes to `local/collections-staging/` (an index plus `<id>.v1.json`). The command refuses
   a selection whose records fail the rules and names each failure; `--journey` is optional.
4. **Review the staged files.** Read them as the public would. Nothing is published yet.
5. **Publish, explicitly.** Re-run with `--publish-to apps/web/public/data`, which writes
   `apps/web/public/data/collections/`; format with Prettier as for any artifact, and run
   `make check` (`validate-public-artifacts` validates the `collections` group).
6. **Open a PR** with the artifact files only. The owner's approval of that PR is the approval.
   After any later catalog or graph rebuild, re-run steps 3-6 if `make check` reports a stale
   collection; nothing is re-routed automatically.
