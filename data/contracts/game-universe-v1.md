# Game universe contract (game-universe-v1)

The committed synthetic content universe behind the web game
(`apps/web/public/data/game/universe.v1.json`) — the "Meridian Tapes" fictional
studio community described in `docs/WEB_PRODUCT_PLAN.md` §8. Everything in this
artifact is invented: acts, contributors, records, and credits. It exists so the
game interface can be exercised with rich, internally consistent content while
real reviewed data grows behind its own gates.

> **Source of truth.** The authored definition is
> `apps/web/scripts/universe-def.mjs`; `apps/web/scripts/build-rounds.mjs`
> expands it deterministically into the committed JSON and `--check` fails the
> web build on any drift between the two. Edit the definition, regenerate with
> `--write`, and commit both.

Top-level object:

| Key | Meaning |
| --- | --- |
| `schema_version` | Always `1` |
| `provenance` | Must self-identify as synthetic/fictional in `source`, `license`, **and** `note` — each field read in isolation |
| `albums[]` | `{id, title, act, act_id, year, label, art}` |
| `contributors[]` | `{id, name, role_category, performer}` |
| `releases[]` | `{id, album_id, title, year, catalog_stamp}` — one per album |
| `credits[]` | `{release_id, contributor_id, role_text, role_category, credit_scope}` |

Rules (enforced by `build-rounds.mjs` and `apps/web/tests/game-data.spec.ts`):

- **Reserved id ranges.** Album ids match `syn-aNN`; contributor ids are
  ≥ 90 000 000; nothing may collide with plausible Discogs identifiers.
- **`art` is `{kind: "generated"}` or `null`** — never image bytes, never a
  hotlink: fictional records cannot honestly carry real artwork. Generated
  sleeves (`apps/web/src/game/sleeves.ts`) carry an in-art `SYNTHETIC` stamp.
- **Role vocabulary mirrors the real credits schema:** `role_text` preserves a
  display string, `role_category` is the normalized game vocabulary, and
  `credit_scope` uses the real contract's `release_credit` value so evidence
  renders through the same components as real data.
- **Leak/tone scans apply** exactly as for cohort artifacts: no private paths,
  tokens, or influence phrasing anywhere in the serialized JSON.
- Every album must carry at least two credits so every record can appear in at
  least one round.

This artifact is presentation-and-play content only. It is never an input to
the Python pipeline, never mixed into real datasets, and the UI badges every
surface that renders it as the synthetic pool.
