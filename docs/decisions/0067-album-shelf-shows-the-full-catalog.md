# ADR 0067: The album shelf shows the full catalog, not just challenge.v2-connected albums

- **Status:** Accepted
- **Date:** 2026-08-29

## Context

`/albums/` has always sourced its grid from `connectedCatalogAlbums()`
(`apps/web/src/data/connectedAlbums.ts`), which filters the catalog down to albums
appearing as an endpoint of at least one `challenge.v2.json` documented path. Any catalog
album with no such path is silently absent from the shelf. This choice predates this ADR —
it was never written up on its own, only documented in code and test comments
(`apps/web/tests/album-grid-dedup.spec.ts`: "The grids above stay at connectedAlbumCount on
purpose (a deliberate, unrelated curation choice)").

At the 140-album catalog this hid 3 albums — a rounding error, easy to not notice. Phase 7's
catalog expansion (PR #161) grew the published catalog to 179 albums; the exclusion count
grew with it, to 6. The Phase 7 plan (section 10, "Public product at ~180 albums") calls this
out directly: hiding a growing fraction of a genuinely public catalog with no way to reach it
except by already knowing its URL is no longer a rounding error, it's a real gap. Every one of
those 6 albums already has a complete, working `/albums/<id>/` page — Phase 6 PR 6-07
widened `getStaticPaths` specifically so every catalog album gets a real page, and that page
already handles the zero-connection case gracefully ("No documented connection is indexed
from `<title>` yet."). The only thing missing was a way to *find* that page from the browse
surface.

## Decision

`/albums/` now renders every catalog album (`challenge.albums`, not
`connectedCatalogAlbums(challenge)`). An album with no documented path is marked honestly
rather than hidden: its card carries a `tag tag--unconnected` badge reading "Not yet
connected" (plus a `data-album-connected="false"` attribute for tests/tooling), and the page
shows an aggregate line ("N not yet connected to the credit graph") whenever that count is
nonzero. The card's link is unchanged — it still opens the album's real page, which already
tells the honest story on its own.

`connectedCatalogAlbums()`'s underlying id-set computation is extracted into a new exported
`connectedAlbumIds(challenge)` so the shelf page can compute connected/unconnected status
without a second copy of that logic; `connectedCatalogAlbums()` itself is unchanged in
behavior and keeps its remaining callers.

**This decision is scoped to the album shelf only.** Three other consumers of the
connected-only filter are deliberately left as they are:

- **`/explore/`'s grid** stays connected-only. Explore is about hopping through the credit
  graph from a starting point; an album with no documented connection isn't a meaningful
  entry into that specific experience the way it's still a meaningful browse entry on a
  shelf. A visitor can still reach `/explore/<id>/` directly (e.g. via the album page's own
  cross-link), which already handles the zero-connection case too.
- **The homepage's featured section** is untouched — its remaining hardcoded editorial-pick
  text is a separate, still-open item (making homepage examples fully artifact-derived), not
  part of this decision.
- **The sitemap** already lists every real page regardless of connectivity (Phase 6 PR 6-07)
  and needs no change.

## Consequences

`apps/web/tests/album-grid-dedup.spec.ts`'s shelf-count assertion changes from asserting
`/albums/` renders exactly the connected count to asserting it renders the full catalog, with
per-card connected/unconnected assertions added. The file's other tests (excluded-album has a
real page, Explore stays connected-only, sitemap lists the full catalog) are unchanged in
behavior, only in the comments explaining why `/albums/` and `/explore/` now intentionally
diverge.

## Validation

`apps/web/tests/album-grid-dedup.spec.ts` asserts: `/albums/` renders one card per catalog
album (not just the connected subset); the excluded albums render with
`data-album-connected="false"` and visible "No documented path yet" text; a connected album
renders with `data-album-connected="true"` and no such text; `/explore/`'s grid and the
sitemap are unaffected.

## Addendum (2026-08-30)

The badge and summary line originally shipped as "Not yet connected" / "N not yet connected
to the credit graph." A retroactive Codex bot review of this PR (caught in a later
audit -- see the `codex-review-retroactive-fixes-progress` memory) flagged that wording as a
real overclaim: `connectedAlbumIds` only tests challenge.v2 path-endpoint membership, not
whether the album has any real graph connections at all. Every one of these albums is a real
pathfinding-graph node with real credited neighbors, individually reachable and explorable at
`/explore/<id>/` -- exactly the opposite of "not connected." The copy now reads "No
documented path yet" / "N without a documented path yet," mirroring the album detail page's
own established phrasing for the same case (`No documented connection is indexed from
{title} yet.`). No behavior changed, only the wording.

## Revisit trigger

Revisit if the catalog ever regenerates with zero unconnected albums for a sustained period
(the honest-state UI becomes permanently inert) or if `/explore/`'s own scope is later
widened to make disconnected browsing meaningful there too, at which point the "explicitly
out of scope" list above should be reconsidered explicitly rather than assumed unchanged.
