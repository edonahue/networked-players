# Game rounds contract (game-rounds-v1)

The derived, committed round pool behind the web game
(`apps/web/public/data/game/rounds.v1.json`), produced and validated by
`apps/web/scripts/build-rounds.mjs` (docs/WEB_PRODUCT_PLAN.md §8). Rounds are
**derived, never hand-edited**: the generator recomputes them deterministically
from the game universe plus the real curated demo dataset, and `--check` (wired
into the web build) fails on drift or any validation problem.

Top-level: `schema_version` (always `1`), `provenance`, `rounds[]`.

One round:

| Field | Meaning |
| --- | --- |
| `id` | `syn-1h-…`, `syn-2h-…`, or `real-1h-…` — unique, deterministic |
| `pool` | `synthetic-universe` \| `real-records` — badged in the UI |
| `kind` | `one_hop` \| `two_hop` |
| `difficulty` | `easy` \| `medium` \| `hard` (derived, see below) |
| `endpoints` | Two `AlbumRef`s: `{id, title, year, act, label, art}` (`label` is the fictional label for synthetic albums, `null` for real records) |
| `middle` | Two-hop only: the hidden album plus shuffled `choices[]` (answer included, distractor middles validated invalid) |
| `answer_set` | **Every** valid connecting contributor — any member is a correct answer |
| `bridge_answer_sets` | Two-hop only: valid bridges per side for the chosen middle |
| `distractors` | Contributor refs validated to **not** satisfy the connection |
| `clues` | Ordered ladder: `years → role → initials → credit_excerpt → eliminate` |
| `evidence` | Credit rows backing every answer on every relevant record |
| `provenance_note` | Rendered in the evidence footer; states the pool honestly |

Pools:

- **`synthetic-universe`** rounds draw only from `universe.v1.json`; endpoints
  are `syn-a` albums; art is generated or absent.
- **`real-records`** rounds derive from `public/data/challenge.v1.json` (real
  curated Discogs data, ADR 0012): endpoints are `real-rel-<release_id>`
  records, art only as `https://i.discogs.com/…` hotlinks, answers restricted
  to linked, playable identities, Discogs placeholder identities (ADR
  0026/0035) excluded from answers and distractors.

Validation guarantees (generator + `apps/web/tests/game-data.spec.ts`, which
re-verifies from first principles so the generator cannot grade its own work):

- no empty `answer_set`; every answer has evidence rows;
- **no distractor satisfies the connection** (the load-bearing invariant);
- two-hop middle distractors are not themselves valid middles;
- pool floors: ≥ 40 synthetic rounds (≥ 8 two-hop, all three difficulties),
  ≥ 6 real rounds;
- forbidden-substring and influence-phrase scans over the serialized artifact;
- a shared credit is described as documented participation on a recording —
  never as influence.

Difficulty derivation: synthetic — non-performer answers or confusable-kin
distractors raise difficulty; real — co-billed release artists on both records
is `easy`, purely non-performer connections are `hard`, otherwise `medium`.

Future pools (a real dump-derived challenge artifact after live gate F, or a
human-reviewed cohort per ADR 0031) plug in as additional `pool` values under
this same round shape without changing consumers.
