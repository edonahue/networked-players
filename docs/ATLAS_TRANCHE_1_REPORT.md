# Campaign "Atlas" — tranche 1 report

Date: 2026-11-17 · Decision record: [ADR 0072](decisions/0072-campaign-atlas-lineage-approved-pool-collections.md) ·
Status page: [CAMPAIGN.md](CAMPAIGN.md)

Tranche 1 was scoped as "safe to rebuild, worth arriving at": no catalog growth, no real
Collection published, no public data regenerated. All of its code is merged. It is **not closed**:
two items need the owner (below).

## What shipped

| Area | Work package | Pull request | What changed |
|---|---|---|---|
| Decisions | F0 | #260 | ADR 0072, ADR 0018 addendum, the campaign status page |
| CI and deploy | F5 | #261 | Unique job ids (`python`, `web`), pinned runners, post-deploy smoke check; required checks on `main` |
| Artifact integrity | F1 | #262, #267 | Guesser, Routes and challenge checked against the catalog; evidence registry must cover every cited release; builders declare the upstream versions they read; `challenge_version`; one generic lineage rule |
| Approval boundary | F2 | #264 | `data/albums/approved-pool-v1.json` (217 albums, public fields only); catalog must equal the pool in both directions; the builder refuses unapproved or dropped albums |
| Orchestration | F3 | #272 | `round plan / run / verify / check-cutover`; the expansion runbook rewritten around it |
| Integrity checks | F4 | #271 | Pin over already-played daily dates; payload budgets as a test; determinism tests for the catalog and challenge builders |
| Test robustness | F6 | #275 | Web tests derive their records and pairs from the committed artifacts; a guard fails any spec that names a real catalog entry |
| Record page | P1 | #263 | Performer roster in static HTML, "where these players lead", evidence readable without JavaScript, guessing as an opt-in |
| Search and navigation | P2, P3 | #266, #268 | Site-wide search over records and players; four-item navigation; homepage led by Explore |
| Collections groundwork | S1 (study), RP | #269, #273 | Album-projection clustering study; an offline review packet for rounds and candidate collections |

## What is true now that was not before

- A stale Connection Guesser pool, Record Routes pool, challenge or evidence registry fails
  `validate-public-artifacts`. Before, each passed.
- The published catalog cannot differ from the committed approved pool without failing CI.
- A date already played in the daily game cannot be changed without failing CI (pinned through
  2026-11-09; advancing the pin is part of the schedule-extension routine).
- A failing pull request cannot merge to `main`, and every deploy is compared with the commit
  that produced it.
- A visitor arriving on a record page can read who played on it and where those players lead
  without running JavaScript.

## What is not proven

Stated plainly so that nothing below is mistaken for done.

- **The round runner has only run a synthetic round.** Its album-art stage (which needs an API
  token and a private cache) and its formatting stage ran as stand-ins in tests. The first real
  round is its first real use.
- **No committed artifact declares lineage yet.** `validate-public-artifacts` lists eleven as
  undeclared. They cannot be given lineage retroactively; the Round 2 rebuild is the first to
  carry it. Until then the catalog cross-checks are the protection.
- **The approved pool and its builder check were exercised on synthetic fixtures only.** No real
  catalog build has run with `--approved-pool`.
- **Fleet workers are behind `main`.** The default fleet artifact check now passes the catalog as
  a third input, and rebuilt artifacts will carry a `provenance` field that an older contracts
  install rejects. Workers need the platform runtime redeployed and contracts reinstalled before
  either is used on the fleet. Nothing was deployed in this tranche.
- **The x86 worker's hardware is unverified.** The health check stopped at its disk floor before
  reporting hardware facts, so `docs/HARDWARE.md` has not been changed.
- **Real devices.** All mobile evidence is still emulation.

## Measurements from the committed 217-album catalog

Counts and byte sizes of published artifacts (not performance data).

- Pathfinding graph: 1,149,326 bytes gzipped, against a 2,000,000-byte warning line and a
  2,500,000-byte hard budget. Total public data: 31,000,869 bytes against a 60,000,000-byte
  ceiling.
- Album-projection study at its default parameters (a link requires two shared performers):
  12 qualifying clusters covering 50 % of records; the largest holds 7 %; modularity is above
  both null models (z = 4.2 against the rewired projection, 3.6 against the rewired
  album–performer incidence). The numeric criteria fail when a link requires three shared
  performers, where coverage falls to 24 %. Two of the twelve clusters are held together by
  string-section players rather than by a scene.

## Things the work turned up

- The hand-run runbook the runner replaces omitted `--albums` on the challenge build (so it
  would have built from the wrong album list) and had no daily-manifest freeze or migrate step.
- Eight Round 1 albums, not two, had no committed approval record. The owner has since approved
  all eight; they are recorded in the pool.
- The first homepage rule for a featured pair chose two records that shared a string section.
  The rule now counts only players credited outside the string section on both records.
- Merging two green pull requests produced a red `main`-equivalent once: the runner's verify
  stage picked up the new played-date pin from its default path. The pin and budgets are now
  explicit round inputs. Pull requests that predate another merge are now updated and re-run
  before merging.
- One pull request (#266) was merged before its automated review comments were read; the two
  findings were fixed in #268.

## Open with the owner

1. **Cluster legibility** (ADR 0072 §6, the fourth criterion): whether at least 7 of 10 sampled
   clusters read as real scenes. The result, either way, is recorded as an ADR 0072 addendum.
2. **The x86 worker's disk**, which blocks hardware verification and any fleet redeploy.
3. **Go or no-go for the gated parts of tranche 2**: publishing a first Collection, the Round 2
   candidate review and rebuild, the player-index change (after the owner sees the page-set
   diff), and fleet deployment.

Work that needs none of those decisions — site improvements, platform code, the Collection
contracts on synthetic data, parse hardening — proceeds under the owner's standing go-ahead of
2026-11-17 and is tracked in CAMPAIGN.md.
