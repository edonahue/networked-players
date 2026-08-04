# Phase 3 report: a research lab on top of the same backend

**Status: complete.** All planned slices shipped, each as its own
branch/PR, auto-merged once `make check` was green — the same continuous
discipline Phase 2 established. This report is the closing summary the
plan asked for: what shipped, what was measured, what was rejected, and
what's left.

## What shipped

| Slice | PR | What it is |
|---|---|---|
| A + B | [#73](https://github.com/edonahue/networked-players/pull/73) | `packages/research/` skeleton — the Research Run contract (`request.py`/`runs.py`), the Topic Corpus Builder (`corpus.py`, an artist-seeded generalization of `onehop.py`'s release-seeded expansion), and a real, built Jamiroquai 1-hop corpus (5,395 releases / 196,426 credits) against the already-complete full-corpus parse. ADR 0054 (research lane + promotion boundary). |
| C | [#74](https://github.com/edonahue/networked-players/pull/74) | Graph analytics foundation + a real three-library benchmark (NetworkX/igraph/rustworkx) at topic-corpus scale — closes `docs/ROADMAP.md` §7's long-open item. ADR 0055 selects igraph. |
| D | [#75](https://github.com/edonahue/networked-players/pull/75) | Jamiroquai Analysis v1 — the remaining five analyses (`role_distribution`, `temporal_comparison`, `contributor_network`, `community_detection`, `bridge_analysis`), a forbidden-phrase tripwire over generated findings/report text, and a full real run against the Jamiroquai corpus. |
| E | [#76](https://github.com/edonahue/networked-players/pull/76) | Research compute wiring through the existing ADR 0034 capability platform (`research.corpus-check`, `research.graph-metrics`) — real dispatch to the live x86 worker, plus a real locality benchmark including a bounded, one-off exercise on a live Raspberry Pi 3B. |
| F | *(no PR — investigated and skipped)* | Discogs Artist alias ingestion — investigated against real data, found no concrete gap, skipped with reasoning (see below). |
| G | *(this change)* | Jamiroquai Research Pack v1 — a discography-overview summary and a most-connected-contributors view added to the report, a real promotion-candidates review (nothing promoted), and this closing report. |

## What was measured before being built

- **Slice A/B**: before assuming a multi-hour reparse was needed, checked
  whether the prior full 19.2M-release parse still existed on disk — it
  did (`local/processed/discogs/snapshot=20260601/`), eliminating that
  cost entirely. The Topic Corpus Builder was cross-checked against an
  *already-public* catalog artist (A Tribe Called Quest) before trusting
  it on the new Jamiroquai case — its resolved `artist_id` and known
  `main_release_id` matched exactly.
- **Slice C**: a real three-library graph benchmark at real topic-corpus
  scale, not the full canonical dataset (which the Phase 2 CSR benchmark
  already showed was infeasible for this kind of build). All three
  libraries agreed exactly on node/edge/component counts before any
  timing comparison was trusted. igraph won decisively on both speed and
  memory and was the only one with built-in community detection — see
  ADR 0055 and `docs/RESEARCH_GRAPH_BENCHMARK_METHOD.md`.
- **Slice D**: real findings, including two genuine, honestly-reported
  limitations rather than smoothed-over numbers — `role_taxonomy.py`
  classifies the majority of credits (128,065 of 201,692, ~63%) as
  `unknown` at this corpus's scale, and the 1-hop-from-any-credit corpus
  is compilation-heavy enough that `temporal_comparison` flags turnover
  in nearly every year (33 one-year "eras"), not the multi-year eras a
  cleaner core-discography-only corpus might show.
- **Slice E**: real dispatch to the live x86 worker through the actual
  `select_worker()` scheduler — the dispatched `research.graph-metrics`
  degree distribution (656 nodes / 680 edges) matched Slice D's local
  `contributor_network` analysis exactly, a real cross-validation. A real
  locality benchmark found the identical bounded computation ~4.6x slower
  in raw compute on a Pi 3B than on x86, but dominated in wall-clock terms
  by Ansible/SSH orchestration overhead, not transfer or compute — see
  `docs/RESEARCH_COMPUTE_LOCALITY_METHOD.md`.
- **Slice F**: a direct, real query against the full credits table found
  that Jamiroquai's `artist_id` (8029) already has 17 real ANV
  (name-variation) spellings — `Jamiroquaï`, `Jamiraquai`, CJK scripts,
  etc. — all already correctly resolved to the one canonical `artist_id`
  by the existing PAN/ANV separation. The one other similarly-named
  identity found (`artist_id=7921476`, "Jamiroquai Limited") is a
  genuinely distinct catalogued entity that Discogs' own data already
  keeps separate, not a conflation. No evidence of missed or conflated
  personnel — the trigger condition for building alias ingestion was not
  met.

Real hardware/timing numbers from these benchmarks stayed in
`local/benchmarks/`/`local/research/` (gitignored) per ADR 0018 — only
methodology and catalog-quality facts (real corpus sizes for a public
artist) are in this document or the public docs.

## Rejected or descoped approaches

- **Discogs Artist alias ingestion (Slice F)** — investigated with real
  data, found no concrete gap, skipped rather than built speculatively
  (see above).
- **A `research promote` CLI command** — deliberately not built. The
  existing manual contract-creation workflow (new validator +
  `PUBLIC_ARTIFACT_GROUPS` entry, following Phase 1/2's own pattern) was
  reused as-is; a generic promote command is deferred until a second real
  candidate proves the pattern repeats, mirroring ADR 0039's "extract a
  shared helper only once a third surface needs it."
- **Any Jamiroquai-specific public feature** — explicitly reviewed in
  Slice G's promotion pass and not promoted. The real findings surfaced
  genuine corpus-scope limitations (see above) rather than a clean,
  ready-to-publish result; shipping a public feature on top of known,
  undocumented-to-the-public methodological gaps was judged not low-risk.
  Recorded as a named candidate in `promotion_candidates.json` with
  reasoning, not silently dropped.
- **Full RQ-based onboarding of the Pi fleet onto the ADR 0034 capability
  platform** — investigated in Slice E, found genuinely missing
  prerequisites (`platform_worker_id`/memory-limit configuration,
  unverified systemd-linger state on each real Pi) that make this a
  real, first-time production-configuration project, not a simple
  redeploy of an already-working pattern. Deliberately not attempted
  unsupervised — real Pi compute was still exercised for real (a bounded,
  one-off Ansible run of the exact `research.corpus-check` handler logic
  against a live Pi 3B), but standing RQ participation stays an explicit,
  documented follow-up.
- **Dask as a production dispatch path, a second live source adapter
  (MusicBrainz/Wikidata), LLM/embeddings infrastructure, GPU/x600
  compute, and a full Discogs Artist-dump ingestion** — all explicitly
  named as rejectable in the original plan, and none were justified by
  any real measured workload this phase. Rejected up front, consistent
  with the plan's own "don't build it until a workload justifies it"
  discipline.

## Tests run

- Backend: `make check` (Ruff lint/format, mypy, pytest, both
  public-artifact-gate validators) — green at every slice merge; 928
  backend tests at this report's close (2 skip cleanly without the
  optional `graph` extra installed), up from 916 at the start of this
  phase.
- New coverage this phase: `packages/research/tests/` (request/corpus/
  runs/analyses/report/graph-bench/platform-jobs/CLI end-to-end fixtures)
  and new `packages/platform/tests/` coverage for the two Slice E
  workloads — all fixture/synthetic, no automated test touches a real
  broker or real fleet hardware (matching `test_fleet_check.py`'s own
  precedent).
- Real-hardware validation happened outside the automated test suite, by
  design: the real Jamiroquai corpus build and analysis run, the real
  dispatched x86 job, and the real one-off Pi exercise were all manually
  verified against real output, not asserted on in CI (their real
  findings were "genuinely discovered, not pre-known," per the plan's own
  test-design language).

## Not exercised at Phase 3's close (explicitly out of scope or deferred)

- Full RQ-based Pi-fleet onboarding onto the ADR 0034 capability platform
  (see "Rejected or descoped approaches" above) — a real, larger,
  first-time production-configuration project.
- Any public-facing feature built from this phase's research findings —
  reviewed and explicitly not promoted (see above); named as a real
  candidate for a future phase.
- `role_taxonomy.py`'s real, measured coverage gap (the `unknown`
  category dominating at Jamiroquai's corpus scale) — recorded as a named
  follow-up in `promotion_candidates.json`, not fixed here, since it is
  an unscoped change to stable Phase 2 production code this phase's own
  rules avoid making without dedicated scope.
- A second real research topic corpus (beyond the one already-public
  cross-check artist and Jamiroquai itself) — the plan's dogfood target
  was one real subject, not a breadth test across many.

## Remaining, after this phase

1. **Pi fleet / ADR 0034 capability platform onboarding** — still not
   complete; `docs/ROADMAP.md` §6 already tracked this as open before
   this phase, and Slice E's investigation made the specific missing
   prerequisites concrete rather than closing the gap.
2. **`role_taxonomy.py` coverage** — a real, evidence-backed improvement
   opportunity is on record (see `promotion_candidates.json`), not yet
   scheduled.
3. **Whether any research finding eventually earns public promotion** —
   deliberately left an open, human decision; nothing here forces a
   future phase's hand.
