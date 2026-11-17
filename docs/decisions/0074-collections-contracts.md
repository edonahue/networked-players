# ADR 0074: Collections — `collection-v1`, `playable-cohort-v2` and the approval flow

- **Status:** Accepted as a contract decision. It publishes nothing: no Collection exists, is
  approved or is published by the change that adds this ADR.
- **Date:** 2026-11-17
- **Implements:** [ADR 0072](0072-campaign-atlas-lineage-approved-pool-collections.md) section 5
- **Amends (without rewriting them):** [ADR 0028](0028-curated-cohort-source-ingestion.md) and
  [ADR 0031](0031-human-reviewed-cohort-promotion.md), clauses listed below
- **Builds on:** [ADR 0068](0068-performer-only-public-graph.md) (performer-only graph),
  [ADR 0059](0059-recommended-route-selection.md) (the site's ranked route),
  [ADR 0030](0030-cohort-scoped-connectivity-substrate.md)
- **Contracts:** [`collection-v1`](../../data/contracts/collection-v1.md),
  [`playable-cohort-v2`](../../data/contracts/playable-cohort-v2.md)

## Context

ADR 0072 decided that a real, reviewed cohort is publicly a **Collection**, that it is a view over
the published catalog, and that it needs contracts of its own. The existing cohort contract
(`playable-cohort-v1`) is artist-to-artist over the one-hop corpus with `release-...` ids and a
required third-party `source_url`. A Collection is a different object: catalog albums as records,
routes over the performer-only graph, original thematic concepts over CC0 catalogue facts.

## Decision

### Definitions

- **Collection:** an owner-titled, ordered set of 4–24 catalog albums spanning at least three
  distinct primary artists, with the performers who bridge them. A view over the catalog: a theme
  that needs albums the catalog lacks becomes an expansion seed, never a parallel universe.
- **Bridge player:** a performer credited (adjacent to the album anchor in `graph.v4`) on at least
  two of the collection's records **spanning at least two distinct primary artists**. A primary
  artist is adjacent to every one of their own albums, so without this rule one artist's
  discography would "bridge" nothing but itself. A collection's own primary artist may be a bridge
  player only on that basis (credited on a record by a different primary artist). Journey hops and
  playable pairs between two records of the same primary artist are refused.
- **Journey:** an optional, ordered walk through some of the records. Each hop is a documented
  performer path in `graph.v4` from one record's anchor to the next, carrying the graph's own
  evidence release id for every consecutive performer pair.
- **Playable pair:** two records of the collection with a documented route between them
  (`playable-cohort-v2`), used by games and Connect-style play.

### Why `playable-cohort-v2` and not a re-bind of v1

v1's endpoints are artists, its hops are releases with quality flags, and it requires a
third-party source. v2's endpoints are catalog records, its route is a performer path with the
graph's evidence ids, and it has no third-party source. Re-binding would change every field's
meaning under one version number. v1 and its synthetic example are untouched. v2 is embedded in
the collection file (one loader request, one shared version and lineage); see the contract note.

### Approval flow (ADR 0031's boundary, kept and extended)

1. **Review packet** (collection mode, `docs/REVIEW_PACKET.md`) built from a local study. Private.
2. **Private selection file** `collection-selection.private.json`, exported by the owner from the
   page. Kept records, working title, note, cluster status. It never leaves `data/private/` or
   `local/`.
3. **Private approval file** (written by the owner, kept next to the selection): the cluster, the
   exact ordered records (which must equal the selection's kept records), the public journey order
   and whether playable pairs are published. Cluster, record order, journey and playable are
   therefore approved in a reviewable file, not in CLI flags, closing the gap against ADR 0031's
   "a selection file, not flags" rule. The file is `{schema_version: 1, kind:
   "collection-approval", private: true, collection_id, input_hash, cluster, records, journey,
   playable}`; its `input_hash` must equal the selection's, so it cannot be reused for another
   study.
4. **`promote-collection`** (operator-run, never automatic): consumes the selection, the approval,
   the study (the selection's `input_hash` must match), the catalog and `graph.v4.json`, plus
   owner-written public text (title, intro, optional attribution, passed as flags or a text file;
   these are reviewed in the final PR, not approved here). Stages under `local/` by default; writes into
   `apps/web/public/data/` only with an explicit `--publish-to`.
5. **Public artifact**, committed in an owner-reviewed PR. The owner's approval is the commit;
   nothing is promoted by a threshold, a score or a schedule.

### Public vs private

Public: `collection_id`, `title`, `intro`, ordered records, bridge players, journey, playable
pairs, optional attribution, provenance. A working title becomes a public title only through an
explicit field: the owner passes it as `--title` (or in the public text file). Never public, and
never present in an artifact: notes, reviewer identity, rejected or dropped records, cluster
status, the selection file, `input_hash`. The validator enforces an explicit key denylist at any
depth (`notes`, `note`, `review_note`, `reviewer`, `reviewed_by`, `rejected`, `working_title`,
`kept_records`, `input_hash`, `private`, any key ending `_private`) and the builder additionally
refuses output in which the selection's note or working-title text appears (compared against the
decoded string values as whole phrases; text shorter than 12 characters after case and whitespace
folding is not matched, because short private text such as "jazz" is common vocabulary; each
sentence of a longer note is matched too). The precise text checks are listed in the contract note
(`collection-v1.md`, "Private-field guard and text checks"): path/credential text in every string
value; owner-collection phrases in title, intro and attribution label; influence phrases in title
and intro only; `source_url` a public page (no user, collection or wantlist paths on any domain);
`generated_at` an ISO-8601 timestamp. Every entry in `collections/` must be the index or a listed
`<id>.v1.json`; anything else fails validation. Title and intro are
owner-written and are never generated; copy must not suggest the owner's private record collection
or infer influence or a working relationship from a shared credit.

### Staying honest across graph rebuilds

A Collection declares `provenance.inputs.catalog` and `provenance.inputs.pathfinding_graph` (the
ADR 0072 lineage rule) and `collection_version`, a content hash of everything but provenance and
the `generated_at` label. After any graph or catalog rebuild:

- a stale declared input fails validation, naming both versions;
- independently of versions, every bridge adjacency, journey hop and playable pair is re-checked
  against the **current** graph: a hop whose edge no longer exists, or whose evidence release
  changed, fails and **names the hop**;
- nothing silently re-routes. The fix is a deliberate re-run of `promote-collection` and a
  re-review of the diff. There is no auto-heal.

### Route length equals the site's search limit

At most 4 performer-to-performer hops (`len(via) <= 5`): the site's `findAlbumRoute` runs with
`maxHops = 4` plus two anchor hops that `stripAlbumAnchors` removes, and a single shared performer
is 0 hops. Every published pair and journey hop is therefore reachable by the site's own search.

### Formatting

`apps/web/.prettierignore` lists `public/data/collections/`. The builder writes
`json.dumps(indent=2, sort_keys=True)`, which Prettier reflows (the same drift that already exempts
`routes/rounds.v1.json` and others); ignoring the directory keeps re-runs byte-stable, and the
operator updates a collection by re-running `promote-collection`, never `prettier --write`.

### Routing

The site's ranked recommended route (`apps/web/src/game/recommendedRoute.ts`, ADR 0059) has no
Python mirror: `packages/research/.../route_quality.py` enumerates and measures but does not rank,
and the catalog package must not depend on research. The builder therefore finds a **plain
shortest path** over real performer nodes, first discovered in CSR node order (deterministic),
declared as `route_policy: "shortest-first-found-v1"`. It is not the site's ranked route and is
validated only as a real documented path with the graph's evidence, never as the best one.

### Attribution

Optional `attribution {label, source_url}`, only for a genuinely sourced theme. Collections are
original thematic concepts over CC0 catalogue facts; no third-party list is promoted and nothing
is scraped.

### Amendments

- **ADR 0028**, "Decision" paragraphs on saved third-party pages and "This first stage ... publishes
  nothing" (the premise that every cohort derives from a saved third-party source with a required
  `source_url`): does not apply to Collections, which have no third-party source and make
  `attribution` optional. The saved-HTML, never-live-fetch posture for cohort source ingestion is
  unchanged.
- **ADR 0031**, "Decision" (a selection file, not CLI flags, is the human approval; reviewer
  identity and notes stay private): kept, and extended to record-level Collection selections. The
  difference: v1 publishes an optional cohort-level `review_note`; Collections publish no review
  note at all.

### Registration

`collections` joins `PUBLIC_ARTIFACT_GROUPS` and `validate-public-artifacts`, class `live`
(expected inputs `catalog`, `pathfinding_graph`; the collection validator performs this
multi-file lineage check itself). With no `collections/` directory the group passes.

## What this ADR does not decide

Which collections to publish; any page design beyond what S3 builds; whether any Collection is
approved. It claims no real collection exists. A web page must still be given a loader for the new
`collections/` directory (the cohort pages use a hand-maintained static import map); that is S3.

## Consequences

- A new public directory, `collections/`, counted toward the public data payload budget.
- Collections must be re-promoted after graph or catalog rebuilds that touch their routes; the
  validator makes that visible rather than silent.
- Journey and pair routes are shortest paths, not ranked; a site that shows the ranked route for
  the same two records may differ.

## Revisit trigger

Port the ranking to Python (or shared data) if a Collection page needs to show the site's own
recommended route; revisit embedding `playable_cohort` if pair payloads grow past a few hundred
KB per collection.
