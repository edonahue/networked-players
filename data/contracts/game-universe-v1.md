# Game universe contract (game-universe-v1)

The committed **real** content universe behind the flagship Connection Guesser
(`apps/web/public/data/game/universe.v1.json`) — real studio albums, real
performers, and real credits derived from the Discogs monthly CC0 data dump
(ADR 0042, ADR 0043). It is produced by
`networked-players-catalog build-connection-rounds`
(`packages/graph-core/.../connection_rounds.py`), not by
`apps/web/scripts/build-rounds.mjs`, which is demoted to a **synthetic test
fixture only** (see the bottom of this document) and never writes to
`public/`.

Top-level object:

| Key | Meaning |
| --- | --- |
| `schema_version` | Always `1` |
| `provenance` | Self-identifies as real in `source`, `license`, and `note` (each field read in isolation); `catalog_version` names the canonical `apps/web/public/data/catalog/albums.v1.json` this universe's album set was resolved from; `pool_version` is a content hash of the paired rounds pool |
| `albums[]` | `{id, title, act, act_id, year, label, art}` — every album actually referenced by a round (endpoint, hidden middle, or a two-hop decoy choice), not the full catalog |
| `contributors[]` | `{id, name, role_category}` — `name` is always the canonical PAN-resolved artist name, never a release-specific ANV (see `EvidenceRow.credited_as` in `game-rounds-v1.md` for that) |
| `releases[]` | `{id, album_id, title, year, catalog_stamp}` — one per used album |
| `credits[]` | `{release_id, contributor_id, role_text, role_category, credit_scope}` |

**`credits[]` is a complete index, not an evidence-only subset.** For every
album in `albums[]`, `credits[]` includes *every* eligible performer credit on
that album — not just the credits cited as evidence for an already-selected
round's answer. This is what makes independent re-derivation possible: a
consumer (e.g. `apps/web/tests/game-data.spec.ts`) can recompute, from this
artifact alone, the full set of performers shared between any two albums and
compare it for exact equality against a round's published `answer_set`/
`bridge_answer_sets` — not merely check that the published set is a subset of
some narrower, differently-purposed artifact (the trap the prior
`challenge.v2.json`-derived check fell into; `challenge.v2.json`'s own
credits are pre-filtered to an unrelated path-discovery process and routinely
under-report real credits).

Rules (enforced by `validate_connection_rounds_artifact` at generation time,
`networked_players_contracts.connection_rounds` independently, and
`apps/web/tests/game-data.spec.ts`):

- **PAN identity, never conflated with ANV.** `contributors[].name` is the
  canonical artist name; the as-credited spelling on a specific release lives
  only in a round's `EvidenceRow.credited_as`.
- **`art` is `{kind: "hotlink", uri150, uri}` (Discogs CDN) or `null`** —
  cover-art enrichment has not yet run for the real pool (a later slice); a
  `null` album falls back to the polished placeholder sleeve client-side.
- **Role vocabulary mirrors the real credits schema:** `role_text` preserves
  the original Discogs display string, `role_category` is the normalized game
  vocabulary (`eligibility.py::performer_role_category`), `credit_scope` is
  the real per-track/per-release scope.
- **Leak/tone scans apply**: no private paths, tokens, or influence phrasing
  anywhere in the serialized JSON; the private collection seed used to build
  the working set is never published.

This artifact is real, played content: `pool: "real-records"` on every round
in the paired `rounds.v1.json`. It is never fetched by any page at runtime
(only `rounds.v1.json` is) — it exists as a published, contract-validated
reference index.

## The synthetic test fixture (not this artifact)

`apps/web/scripts/build-rounds.mjs` still authors a **synthetic-only** test
fixture (the fictional "Meridian Tapes" universe) at
`apps/web/tests/fixtures/game-universe.synthetic.v1.json` — never `public/`,
never played, never mixed into real data. Its shape is otherwise similar
(reserved id ranges `syn-aNN` / contributor ids ≥ 90,000,000, `art` limited to
`{kind: "generated"}` or `null`, provenance that self-identifies as
synthetic/fictional in every field). It exists purely so pure-engine unit
tests have deterministic, hand-authored content independent of the real data
pipeline. Do not confuse it with this contract.
