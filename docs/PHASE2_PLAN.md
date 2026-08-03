# Phase 2 plan: from static games to an explorable credit network

Status: **in progress**. Companion to `docs/BUILD_PLAN.md` (pipeline/infra track) and
`docs/WEB_PRODUCT_PLAN.md` (the Phase 1 game-launch plan, now shipped). This document
owns the Phase 2 product expansion: making contributors first-class, formalizing role
semantics, measuring a larger exploration graph, and building real path search between
records — while preserving the project's non-negotiables (evidence-before-inference,
static-first delivery, measure-before-optimizing, and the existing publication-integrity
discipline).

Grounded in a full baseline review of the repository as of 2026-08-03 (140-album catalog
`catalog-v1-20260601-0e7ec70fbb7e`, three live game modes, a unified CI publication gate,
and the first real observed Pi/x86 fleet validation run, PR #56). See
`docs/decisions/` for the ADRs referenced throughout.

## How this maps to the roadmap

`docs/ROADMAP.md` §4 (durable contracts), §6 (medium graph and measured expansion), §7
(graph benchmark gate), and §9 (optional live search) are the sections this plan
advances — all still unchecked there as of this writing. This plan does not replace the
roadmap; it is the concrete sequencing for those specific open items, plus new product
surface (contributor pages, a network explorer) the roadmap doesn't itemize at that
granularity.

## Slice sequence

Nine independently-shippable slices, each its own branch/PR:

| Slice | What it ships | Depends on |
|---|---|---|
| A | Homepage/product repositioning (this doc, nav, copy, sitemap fix) | — |
| B | Role taxonomy (`role_taxonomy.py`, diagnostics, ADR 0047) | — |
| C | Contributor index + contributor pages (ADR 0048) | B |
| D | Exploration graph tier measurement (ADR 0049) | — |
| E | Browser/pathfinding benchmark (ADR 0050) | D |
| F | Connect Two Records MVP | B, C, D, E |
| G | Network Explorer (ADR 0052) | B, C, D, E |
| H | Role-aware game mode (ADR 0053) | B |
| I | Daily maturation + publication-train spine | — |

Recommended order: A → B → C → D → E → (F and G in parallel) → H → I, with I movable
earlier as a low-risk win. Full detail for every slice lives in the plan file this
document was generated alongside; see git history / PR descriptions for the as-built
specifics of each slice as it ships.

## Publication train spine

The mission brief describes an eventual `snapshot → parse → build → classify roles →
candidate catalog → semantic diff → regenerate artifacts → validate → fleet canary →
report → PR` pipeline. This plan builds the architectural spine, not full automation.
Status as of Phase 2 (updated as slices land):

| Stage | Status |
|---|---|
| snapshot / parse / build (one-hop) | Real, unchanged by Phase 2 (`manifest`, `download`, `parse-releases`, `expand-one-hop`) |
| classify roles | New in Slice B: `classify-roles` diagnostic — a coverage report, deliberately not a build gate |
| candidate catalog | Slice D extends `rank_album_candidates`/`assemble_album_catalog` to larger tiers via `rank-exploration-tier`, still a manual, measurement-only invocation |
| semantic diff | Not built in Phase 2 — today this is a manual byte-for-byte diff against the prior publish (ADR 0043/0046 practice); a `diff-artifact-version` command would close this gap but is out of scope here |
| regenerate artifacts | Real (`build-connection-rounds`, `build-record-routes`, and Slice C's `build-contributor-index`) |
| validate | Real, comprehensive (`validate-public-artifacts`) |
| fleet canary | Playbooks/scripts exist (`enqueue_cohort_check.py` and siblings) but per issue #53 have never been dispatched for every new artifact type in production — an ops task, explicitly out of scope for this plan |
| report / PR | Manual, human-authored — acceptable per "spine, not full automation" |

## Non-negotiables this plan preserves

- **Evidence before inference**: a documented credit proves participation, never
  influence, friendship, or lineage — enforced mechanically via the `_FORBIDDEN_PHRASES`
  scan in `packages/contracts`, extended to new copy paths as they're added.
- **Static-first**: the core experience never requires a live API or the home lab: this
  is a hard constraint on Slices E, F, and G in particular.
- **Measure before optimizing**: Slices D and E are measurement steps first, decisions
  second — no graph tier size or pathfinding architecture is committed to before its
  benchmark runs. Real hardware/timing numbers stay local (`local/benchmarks/`, ADR
  0018); only methodology and catalog-quality facts are published.
- **Publication integrity**: every new public artifact gets its own dependency-free
  validator, content-derived versioning, and a place in `validate-public-artifacts`,
  following the pattern hardened in ADR 0043/0046.
