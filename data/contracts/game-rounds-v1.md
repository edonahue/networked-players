# Game rounds contract (game-rounds-v1)

The committed **real** round pool behind the flagship Connection Guesser
(`apps/web/public/data/game/rounds.v1.json`), produced by
`networked-players-catalog build-connection-rounds`
(`packages/graph-core/.../connection_rounds.py`, ADR 0042, ADR 0043). A
one-hop round's answer is a performer explicitly credited on **both
displayed albums directly**; a two-hop round hides a middle album bridged by
two independently-guessed performer sets.

> **Not the same contract as `rounds-v1.md`.** That document describes the
> separate **Record Routes** path artifact (`from_album_id`/`to_album_id`/
> `hops`, an artist-pair BFS path via a *third* shared release), produced by
> `rounds.py`/`rounds_generator.py`. Both pairs have historically been
> published at the same file names (`universe.v1.json`/`rounds.v1.json`, in
> different directories) — "rounds.v1" alone never identifies which contract
> an artifact satisfies. This document is the Connection Guesser's contract.

Top-level: `schema_version` (always `1`), `provenance`, `rounds[]`.

One round:

| Field | Meaning |
| --- | --- |
| `id` | `conn-<10 hex chars>` — a sha256 digest of the round's own canonical semantic fields (endpoint album ids + sorted answer ids for one-hop; endpoint album ids + middle album id + sorted bridge answer ids per side for two-hop). Stable across pool regeneration: an unchanged round keeps its id even if the rest of the pool is reordered, expanded, or shrunk; the id only changes when the round's actual puzzle semantics change. |
| `pool` | Always `real-records` for this artifact |
| `kind` | `one_hop` \| `two_hop` |
| `difficulty` | `easy` \| `medium` \| `hard` (one-hop: answer-count-derived; two-hop: always `hard`) |
| `endpoints` | Two `AlbumRef`s: `{id, title, year, act, label, art}` (`label` is always `null` for real records) |
| `middle` | Two-hop only: the hidden album plus `choices[]` — the real answer's position is a **deterministic shuffle seeded by the round's own stable id**, never a fixed index and never wall-clock random |
| `answer_set` | One-hop only: **every** valid connecting performer — any member is a correct answer. Always `[]` for a two-hop round (see `bridge_answer_sets`) |
| `bridge_answer_sets` | Two-hop only: `[bridge_a_answers, bridge_c_answers]` — **every** valid performer bridging each side, not a single "primary" pick |
| `distractors` | Contributor refs validated to **not** satisfy the connection at any step — excluded against the full union of `answer_set`/`bridge_answer_sets`, not just one representative id per side |
| `clues` | Ordered ladder: `years → role → initials → credit_excerpt → eliminate`. Role/initials clues are phrased honestly when more than one valid answer exists for that step (e.g. "… work (among other valid answers)") — never worded as if a single answer were exclusive |
| `evidence` | Credit rows backing **every** answer/bridge answer, not just a primary one |
| `provenance_note` | Rendered in the evidence footer; states the pool honestly |

`ContributorRef.name` is always the canonical PAN-resolved artist name;
`EvidenceRow.credited_as` carries the release-specific ANV/as-credited
spelling. The two are never conflated.

Validation guarantees (`validate_connection_rounds_artifact` at generation
time, `networked_players_contracts.connection_rounds` independently, and
`apps/web/tests/game-data.spec.ts`, which re-verifies from first principles
against the universe's own complete credit index — see `game-universe-v1.md`
— so the generator cannot grade its own work):

- no empty `answer_set` for a one-hop round; every answer/bridge answer has
  evidence rows;
- **no distractor satisfies the connection at any step** (the load-bearing
  invariant), checked against the complete answer/bridge sets;
- a two-hop round's eliminate clue never targets a valid answer;
- two-hop middle is unique across the **entire** eligible catalog (not merely
  among selected rounds) and appears in its own `choices`;
- round ids are stable, content-derived, and unique -- recomputable from a
  round's own published semantic fields (endpoints + accepted answers) by
  both the generation-time validator and the dependency-free mirror,
  independent of any presentation-only field (corrective slice 4.6);
- provenance carries `catalog_version` (which canonical
  `apps/web/public/data/catalog/albums.v1.json` this pool's albums came from),
  `pool_version` (a hash of this round set's **ids only** -- membership), and
  `artifact_version` (a hash of this round set's **complete published
  content** -- every player-visible and evidentiary field; see
  `game-universe-v1.md`'s corrective-slice-4.6 note for the distinction);
- forbidden-substring and influence-phrase scans over the serialized
  artifact, including a recursive check for a leaked `seed` key at any depth;
- a shared credit is described as documented participation on a recording —
  never as influence.

Pool floors (real, measured — see the corrective-slice-4.5 PR comment for
current counts): ≥ 50 one-hop, ≥ 20 two-hop.

## The synthetic test fixture (not this artifact)

`apps/web/scripts/build-rounds.mjs` still authors a synthetic-only rounds
fixture at `apps/web/tests/fixtures/game-rounds.synthetic.v1.json` (id
prefixes `syn-1h-…`/`syn-2h-…`, `pool: "synthetic-universe"`) — never
`public/`, exercised only by `build-rounds.mjs --check` and pure-engine unit
tests. Do not confuse it with this contract.

Record Routes (a real published artifact under a distinct path once slice 6
ships) plugs in as a peer mode with its own contract (`rounds-v1.md`), never
this one.
